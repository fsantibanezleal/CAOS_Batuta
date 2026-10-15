"""The versioned price table (`prices.json`): USD per million tokens by provider and model, each entry with its source
URL and the date it was read. An entry that is not `verified`, or a model that is not listed, is unknown: the caller
refuses a paid lane unless `--allow-unpriced` is given.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PRICE_FILE = Path(__file__).resolve().parent / "prices.json"


@dataclass(frozen=True)
class Price:
    model: str
    input: float      # USD per million input tokens
    output: float     # USD per million output tokens


def load_prices(path=None):
    return json.loads(Path(path or PRICE_FILE).read_text(encoding="utf-8"))


def resolve(provider, model, table=None):
    """The model id an alias stands for (the model itself when it is not an alias)."""
    table = table or load_prices()
    return table.get("aliases", {}).get(provider, {}).get(model, model)


def lookup(provider, model, kind=None, table=None):
    """The Price of a verified entry for `provider` (then for its `kind`), or None when unknown."""
    table = table or load_prices()
    for name in dict.fromkeys(n for n in (provider, kind) if n):
        resolved = resolve(name, model, table)
        entry = table.get("prices", {}).get(name, {}).get(resolved)
        if entry and entry.get("status") == "verified" and isinstance(entry.get("input"), (int, float)) \
                and isinstance(entry.get("output"), (int, float)):
            return Price(resolved, float(entry["input"]), float(entry["output"]))
    return None


def cost_usd(price, tokens_in, tokens_out):
    """The cost of a call in USD, rounded to six decimals."""
    return round((tokens_in * price.input + tokens_out * price.output) / 1_000_000, 6)
