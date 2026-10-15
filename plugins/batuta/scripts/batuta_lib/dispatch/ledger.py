"""Ledger records of a dispatch run (C04): the Model, Provider, Tokens in, Tokens out, Cost USD and Status cells of a row.

The only writer of the ledger file is `delegation.update_ledger` (lock, temp file in the same folder, re-read just before
the replace, C04 check). This module supplies the pure text change that function applies: set cells of one row, adding
the optional columns to the header when the ledger does not have them yet, and every other byte stays as it was. When
`delegation` gains a cell setter of its own, `set_cells` moves there (see the unit report); it is a text function, not a
second writer.
"""
from __future__ import annotations

from batuta_lib import delegation

_d = delegation


def _cell(value):
    return " ".join(str(value).replace("|", "\\|").split())


def _ensure_pipe(content):
    return content if content.rstrip().endswith("|") else content.rstrip() + " |"


def set_cells(text, row_id, values):
    """The ledger text with the cells `values` (column name -> value) of the row `row_id` set. Columns the header lacks are
    appended (header, separator and every row). KeyError for an unknown id or a text without a table."""
    lines = _d._lines(text)
    found = _d._find_table(lines)
    if found is None:
        raise KeyError(row_id)
    head, sep, last = found
    columns = [_d._canonical(lines[head][0][s:e]) for s, e in _d._spans(lines[head][0])]
    if "ID" not in columns:
        raise KeyError(row_id)
    id_at = columns.index("ID")
    target = None
    for n in range(sep + 1, last + 1):
        spans = _d._spans(lines[n][0])
        if len(spans) > id_at and lines[n][0][spans[id_at][0]:spans[id_at][1]].strip() == row_id:
            target = n
            break
    if target is None:
        raise KeyError(row_id)
    missing = [c for c in values if c not in columns]
    if missing:
        for n in range(head, last + 1):
            content, eol = lines[n]
            if n == head:
                content = _ensure_pipe(content) + "".join(f" {c} |" for c in missing)
            elif n == sep:
                content = _ensure_pipe(content) + "---|" * len(missing)
            else:
                content = _ensure_pipe(content) + " |" * len(missing)
            lines[n] = (content, eol)
        columns += missing
    content, eol = lines[target]
    content = _ensure_pipe(content)
    while len(_d._spans(content)) < len(columns):
        content += " |"
    for name, value in values.items():
        spans = _d._spans(content)
        a, b = spans[columns.index(name)]
        if content[a:b].strip() == _cell(value):
            continue
        content = content[:a] + " " + _cell(value) + " " + content[b:]
    lines[target] = (content, eol)
    return "".join(c + e for c, e in lines)


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
        return set_cells(text, row_id, values)

    return _d.update_ledger(path, mutate)
