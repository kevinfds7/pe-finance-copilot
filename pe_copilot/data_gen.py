"""Deterministic synthetic private-equity finance data.

Everything here is fictional. Fund and company names are invented and any resemblance to real
entities is coincidental. The generator deliberately injects a known number of data quality
problems so that the pipeline's rules can be tested against ground truth.
"""
from __future__ import annotations

import random
from datetime import date, timedelta

LATEST_QUARTER = "2024Q4"
QUARTERS = [f"{y}Q{q}" for y in (2023, 2024) for q in (1, 2, 3, 4)]

FUND_DEFS = [
    ("F1", "Meridian Partners I", 2019),
    ("F2", "Meridian Partners II", 2021),
    ("F3", "Meridian Growth III", 2023),
]

# (company name, fund id, sector, region)
COMPANY_DEFS = [
    ("Aurelia Logistics", "F1", "Industrials", "Europe"),
    ("Brightpath Software", "F1", "Technology", "North America"),
    ("Cobalt Renewables", "F1", "Energy", "Asia"),
    ("Delphi Health", "F1", "Healthcare", "North America"),
    ("Everline Foods", "F1", "Consumer", "Europe"),
    ("Fathom Analytics", "F1", "Technology", "Asia"),
    ("Granite Infrastructure", "F2", "Infrastructure", "North America"),
    ("Halcyon Pharma", "F2", "Healthcare", "Europe"),
    ("Ironwood Materials", "F2", "Industrials", "North America"),
    ("Juniper Fintech", "F2", "Financials", "Europe"),
    ("Kestrel Components", "F2", "Industrials", "North America"),
    ("Lumen Telecom", "F2", "Telecom", "Asia"),
    ("Marlow Education", "F3", "Consumer", "Europe"),
    ("Nimbus Cloud", "F3", "Technology", "North America"),
    ("Orchard Retail", "F3", "Consumer", "Asia"),
    ("Pinnacle Water", "F3", "Infrastructure", "Europe"),
    ("Quartz Field Services", "F3", "Energy", "North America"),
    ("Riverbend Hospitality", "F3", "Consumer", "Europe"),
]

# Rule id -> number of rows that the pipeline is expected to flag.
EXPECTED_FAILURES = {
    "DQ001": 3,  # missing revenue
    "DQ002": 1,  # negative revenue
    "DQ003": 2,  # duplicate company-quarter rows
    "DQ004": 2,  # EBITDA greater than revenue
    "DQ005": 2,  # reported more than 120 days after quarter end
    "DQ006": 1,  # currency differs from the fund currency
    "DQ007": 1,  # company points to a fund that does not exist
    "DQ008": 1,  # negative NAV
    "DQ009": 1,  # NAV above 15x cost
}


def quarter_end(quarter: str) -> date:
    year, q = int(quarter[:4]), int(quarter[5])
    month = q * 3
    day = 31 if month in (3, 12) else 30
    return date(year, month, day)


def _fund_year_window(fund_id: str) -> tuple[int, int]:
    return {"F1": (2019, 2020), "F2": (2021, 2022), "F3": (2023, 2023)}[fund_id]


def generate(seed: int = 42) -> dict:
    rng = random.Random(seed)

    companies: list[dict] = []
    financials: list[dict] = []
    valuations: list[dict] = []

    for i, (name, fund_id, sector, region) in enumerate(COMPANY_DEFS, start=1):
        company_id = f"C{i:02d}"
        first_year, last_year = _fund_year_window(fund_id)
        invest_date = date(rng.randint(first_year, last_year), rng.randint(1, 2) if fund_id == "F3" else rng.randint(1, 12), rng.randint(1, 28))

        base_revenue = rng.uniform(15, 80)
        growth = rng.uniform(0.01, 0.04)
        margin = rng.uniform(0.12, 0.34)
        leverage = rng.uniform(0.6, 2.2)
        multiple = rng.uniform(8.5, 12.5)
        ownership = rng.uniform(0.45, 0.9)

        series = []
        for k, quarter in enumerate(QUARTERS):
            revenue = base_revenue * (1 + growth) ** k * (1 + rng.uniform(-0.02, 0.02))
            ebitda = revenue * (margin + rng.uniform(-0.015, 0.015))
            net_debt = ebitda * 4 * leverage * (1 - 0.01 * k)
            enterprise_value = ebitda * 4 * multiple
            nav = (enterprise_value - net_debt) * ownership
            series.append((quarter, revenue, ebitda, net_debt, nav))

        # Cost is set from the first NAV so that unrealised MOIC stays in a sensible range.
        cost = round(series[0][4] / rng.uniform(1.05, 1.6), 2)
        companies.append(
            {
                "company_id": company_id,
                "fund_id": fund_id,
                "company_name": name,
                "sector": sector,
                "region": region,
                "invest_date": invest_date.isoformat(),
                "cost_musd": cost,
            }
        )
        for quarter, revenue, ebitda, net_debt, nav in series:
            q_end = quarter_end(quarter)
            financials.append(
                {
                    "company_id": company_id,
                    "quarter": quarter,
                    "revenue_musd": round(revenue, 2),
                    "ebitda_musd": round(ebitda, 2),
                    "net_debt_musd": round(net_debt, 2),
                    "currency": "USD",
                    "as_of_date": (q_end + timedelta(days=rng.randint(25, 45))).isoformat(),
                }
            )
            valuations.append(
                {
                    "company_id": company_id,
                    "quarter": quarter,
                    "nav_musd": round(max(nav, 0.2 * cost), 2),
                    "valuation_method": rng.choice(["EV/EBITDA multiple", "Discounted cash flow", "Recent transaction"]),
                    "as_of_date": (q_end + timedelta(days=rng.randint(30, 50))).isoformat(),
                }
            )

    funds = []
    cash_flows: list[dict] = []
    for fund_id, fund_name, vintage in FUND_DEFS:
        total_cost = round(sum(c["cost_musd"] for c in companies if c["fund_id"] == fund_id), 2)
        funds.append(
            {
                "fund_id": fund_id,
                "fund_name": fund_name,
                "vintage_year": vintage,
                "currency": "USD",
                "fund_size_musd": float(round(total_cost * rng.uniform(1.05, 1.25))),
            }
        )
        # Capital calls: five calls that sum exactly to the cost invested.
        weights = [rng.uniform(0.5, 1.5) for _ in range(5)]
        amounts = [round(total_cost * w / sum(weights), 2) for w in weights]
        amounts[-1] = round(total_cost - sum(amounts[:-1]), 2)
        first_year, last_year = _fund_year_window(fund_id)
        window_start = date(first_year, 1, 1)
        window_days = (date(last_year, 12, 31) - window_start).days
        for amount in amounts:
            cash_flows.append(
                {
                    "fund_id": fund_id,
                    "flow_date": (window_start + timedelta(days=rng.randint(0, window_days))).isoformat(),
                    "flow_type": "call",
                    "amount_musd": amount,
                }
            )
        # Distributions: older funds have returned more capital.
        share, count = {"F1": (rng.uniform(0.12, 0.22), 3), "F2": (rng.uniform(0.04, 0.08), 2), "F3": (0.0, 0)}[fund_id]
        if count:
            dist_start = date(2024, 1, 1) if fund_id == "F2" else date(2023, 3, 1)
            dist_days = (date(2024, 11, 30) - dist_start).days
            parts = [rng.uniform(0.5, 1.5) for _ in range(count)]
            for part in parts:
                cash_flows.append(
                    {
                        "fund_id": fund_id,
                        "flow_date": (dist_start + timedelta(days=rng.randint(0, dist_days))).isoformat(),
                        "flow_type": "distribution",
                        "amount_musd": round(total_cost * share * part / sum(parts), 2),
                    }
                )

    cost_by_company = {c["company_id"]: c["cost_musd"] for c in companies}
    _inject_issues(seed, companies, financials, valuations, cost_by_company)

    return {
        "funds": funds,
        "companies": companies,
        "quarterly_financials": financials,
        "valuations": valuations,
        "cash_flows": cash_flows,
        "expected_failures": dict(EXPECTED_FAILURES),
    }


def _inject_issues(seed: int, companies: list[dict], financials: list[dict], valuations: list[dict], cost_by_company: dict) -> None:
    """Corrupt a known number of rows. Issues never touch the latest quarter, so headline metrics stay clean."""
    rng = random.Random(seed + 1)

    fin_pool = [i for i, r in enumerate(financials) if r["quarter"] != LATEST_QUARTER]
    rng.shuffle(fin_pool)
    for i in fin_pool[0:3]:
        financials[i]["revenue_musd"] = None
    for i in fin_pool[3:4]:
        financials[i]["revenue_musd"] = -abs(financials[i]["revenue_musd"])
    for i in fin_pool[4:6]:
        financials[i]["ebitda_musd"] = round(financials[i]["revenue_musd"] * 1.3, 2)
    for i in fin_pool[6:8]:
        financials[i]["as_of_date"] = (quarter_end(financials[i]["quarter"]) + timedelta(days=200)).isoformat()
    for i in fin_pool[8:9]:
        financials[i]["currency"] = "EUR"
    duplicates = [dict(financials[i]) for i in fin_pool[9:11]]
    financials.extend(duplicates)

    val_pool = [i for i, r in enumerate(valuations) if r["quarter"] != LATEST_QUARTER]
    rng.shuffle(val_pool)
    for i in val_pool[0:1]:
        valuations[i]["nav_musd"] = -abs(valuations[i]["nav_musd"])
    for i in val_pool[1:2]:
        valuations[i]["nav_musd"] = round(cost_by_company[valuations[i]["company_id"]] * 25, 2)

    companies.append(
        {
            "company_id": "C99",
            "fund_id": "F9",
            "company_name": "Zenith Holdings",
            "sector": "Industrials",
            "region": "Europe",
            "invest_date": "2022-06-15",
            "cost_musd": 40.0,
        }
    )
