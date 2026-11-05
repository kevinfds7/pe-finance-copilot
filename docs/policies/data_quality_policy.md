# Data quality policy (illustrative, fictional)

## Severity
Critical rules protect reported numbers. Records failing a critical rule are quarantined and excluded from curated tables. Warning rules keep the record but flag it in the dq_flags column.

## Critical rules
Missing revenue, negative revenue, duplicate company and quarter records, currency mismatch with the fund, a company pointing to an unknown fund, and negative NAV.

## Warning rules
EBITDA greater than revenue, reporting more than 120 days after quarter end, and NAV above 15 times cost.

## Remediation
Each quarantined record has a data owner. Corrections are proposed, reviewed by a human reviewer, and only then applied at source. The assistant never changes data.
