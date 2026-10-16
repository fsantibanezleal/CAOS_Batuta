"""Ledger records of a dispatch run (C04): the Model, Provider, Tokens in, Tokens out, Cost USD and Status cells of a row.

The only writer of the ledger file is `delegation.update_ledger` (lock, temp file in the same folder, re-read just before
the replace, C04 check); the text change it applies comes from `delegation.ledger_set_cells` (and `ledger_add_row` for a
brief that has no row yet). Nothing here parses or writes the ledger by itself.
"""
from __future__ import annotations

from batuta_lib import delegation as _d


def record(path, row_id, values, defaults=None, title=None):
    """Set the cells of the row `row_id` of the ledger file `path` (a row is added from `defaults` when the ledger has none,
    and the file is created when it does not exist). Raises delegation.LedgerError when the result would not satisfy C04
    (a billed row without its token and cost numbers, for one); the file is then untouched."""
    defaults = dict(defaults or {})

    def mutate(text):
        ids = {r["ID"] for r in _d.ledger_rows(text)[1]} if text.strip() else set()
        if row_id not in ids:
            row = {"ID": row_id, "Agent": "-", "Model": "-", "Brief": "-", "Report": "-", "Status": "drafted", "Accepted": "no"}
            row.update(defaults)
            row.update({k: v for k, v in values.items() if k in _d.LEDGER_COLUMNS})
            text = _d.ledger_add_row(text, row, title=title)
        return _d.ledger_set_cells(text, row_id, values)

    return _d.update_ledger(path, mutate)
