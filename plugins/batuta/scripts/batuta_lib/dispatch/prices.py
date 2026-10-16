"""The versioned price table (`prices.json`): USD per million tokens by provider and model, each entry with its source
URL and the date it was read. An entry that is not `verified`, or a model that is not listed, is unknown: the caller
refuses a paid lane unless `--allow-unpriced` is given.

An entry may carry a `long_context` tier (`above_input_tokens`, `input`, `output`): when a call's input passes that
threshold the whole call is billed at the tier's rates. Where a page lists a higher rate for long prompts and the entry has
no tier field, the entry holds the higher rate so a cap is never under-counted.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PRICE_FILE = Path(__file__).resolve().parent / "prices.json"


@dataclass(frozen=True)
class Price:
    model: str
    input: float                  # USD per million input tokens
    output: float                 # USD per million output tokens
    long_above: int = 0           # input tokens above which the long-context rates apply (0: no tier)
    long_input: float = 0.0
    long_output: float = 0.0

    def rates(self, tokens_in):
        """(input rate, output rate) for a call with `tokens_in` input tokens."""
        if self.long_above and tokens_in > self.long_above:
            return self.long_input, self.long_output
        return self.input, self.output


def load_prices(path=None):
    return json.loads(Path(path or PRICE_FILE).read_text(encoding="utf-8"))


def resolve(provider, model, table=None):
    """The model id an alias stands for (the model itself when it is not an alias)."""
    table = table or load_prices()
    return table.get("aliases", {}).get(provider, {}).get(model, model)


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def lookup(provider, model, kind=None, table=None):
    """The Price of a verified entry for `provider` (then for its `kind`), or None when unknown."""
    table = table or load_prices()
    for name in dict.fromkeys(n for n in (provider, kind) if n):
        resolved = resolve(name, model, table)
        entry = table.get("prices", {}).get(name, {}).get(resolved)
        if entry and entry.get("status") == "verified" and _number(entry.get("input")) and _number(entry.get("output")):
            tier = entry.get("long_context") or {}
            if tier and all(_number(tier.get(k)) for k in ("above_input_tokens", "input", "output")):
                return Price(resolved, float(entry["input"]), float(entry["output"]), int(tier["above_input_tokens"]),
                             float(tier["input"]), float(tier["output"]))
            return Price(resolved, float(entry["input"]), float(entry["output"]))
    return None


def cost_usd(price, tokens_in, tokens_out):
    """The cost of a call in USD, rounded to six decimals (the long-context rates when the input passes the tier)."""
    rate_in, rate_out = price.rates(tokens_in)
    return round((tokens_in * rate_in + tokens_out * rate_out) / 1_000_000, 6)
