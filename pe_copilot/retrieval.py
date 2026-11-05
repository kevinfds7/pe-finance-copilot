"""Small BM25 retriever over the policy markdown files (no external dependencies)."""
from __future__ import annotations

import math
import re
from collections import Counter
from functools import lru_cache

from . import config

STOP = {"the", "a", "an", "of", "to", "is", "are", "and", "or", "in", "on", "for", "be", "by", "with", "as", "it", "this", "that", "what", "how", "does", "do"}


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOP]


@lru_cache(maxsize=1)
def _index() -> list[dict]:
    chunks = []
    for path in sorted(config.POLICY_DIR.glob("*.md")):
        title, buf = path.stem, []
        def flush():
            body = "\n".join(buf).strip()
            if any(l.strip() and not l.startswith('#') for l in buf):
                chunks.append({"source": path.name, "title": title, "text": body, "tokens": _tokens(body)})
        for line in path.read_text().splitlines():
            if line.startswith("## "):
                flush(); buf = [line]
                title = line[3:].strip()
            else:
                buf.append(line)
        flush()
    return chunks


def search(query: str, k: int = 3) -> list[dict]:
    chunks = _index()
    q = _tokens(query)
    if not chunks or not q:
        return []
    n = len(chunks)
    avg = sum(len(c["tokens"]) for c in chunks) / n
    df = Counter(t for c in chunks for t in set(c["tokens"]))
    scored = []
    for c in chunks:
        tf = Counter(c["tokens"])
        score = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            score += idf * tf[t] * 2.2 / (tf[t] + 1.2 * (0.25 + 0.75 * len(c["tokens"]) / avg))
        if score > 0:
            scored.append((score, c))
    scored.sort(key=lambda x: -x[0])
    return [{"source": c["source"], "section": c["title"], "text": c["text"], "score": round(s, 3)} for s, c in scored[:k]]
