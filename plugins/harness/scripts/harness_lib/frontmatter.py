"""Stdlib reader for the front matter subset of the harness Markdown artifacts, plus section and table scanners.

Front matter subset (contracts.md section 2), between two lines of three dashes:

    key: value                 scalar: quoted string, integer, true/false, null, or a plain string
    key: [a, b, 'c, d']        inline list of scalars
    key: {k: v, n: [1, 2]}     inline map: scalars, or inline lists of scalars
    key:                       block list of scalars or of inline maps
      - item
      - {k: v, k2: "v, 2"}
    key:                       one-level map (values: scalars or inline lists of scalars)
      sub: value

Nothing nests deeper than one level: a map in a map, a list in a list and a map in an inline list are refused with
an error (never read as something else).

A plain string may contain colons (`review_trigger: review-by: 2027-04-11`). Leading HTML comment lines and blank
lines before the opening line are skipped (fixtures carry their `why` there). Errors raise ValueError that start
with `line N` (N counts lines of the whole text for `parse`, lines of the body for `sections` and `tables`).
"""
import re

_COMMENT = re.compile(r"^\s*<!--.*-->\s*$")
_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_-]*):(?:\s+(.*))?$")
_INT = re.compile(r"^-?\d+$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_SEP = re.compile(r"^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$")
_NEWLINE = re.compile(r"\r\n|\n|\r")


def _lines(text):
    return _NEWLINE.split(text)


# ------------------------------------------------------------------ scalars


def _split_top(s, n):
    """Split a flow body on commas outside quotes and outside nested brackets."""
    parts, cur, quote, i, depth = [], [], None, 0, 0
    while i < len(s):
        ch = s[i]
        if quote:
            cur.append(ch)
            if quote == '"' and ch == "\\" and i + 1 < len(s):
                i += 1
                cur.append(s[i])
            elif ch == quote:
                if quote == "'" and i + 1 < len(s) and s[i + 1] == "'":
                    i += 1
                    cur.append(s[i])
                else:
                    quote = None
        elif ch in "\"'":
            quote = ch
            cur.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            if ch in "[{":
                depth += 1
            elif ch in "]}":
                depth -= 1
            cur.append(ch)
        i += 1
    if quote:
        raise ValueError(f"line {n}: unterminated quoted string")
    last = "".join(cur).strip()
    if last or parts:
        parts.append(last)
    return [p for p in parts if p != ""] if parts else []


def _quoted(v, n):
    q = v[0]
    out, i = [], 1
    while i < len(v):
        ch = v[i]
        if q == '"' and ch == "\\" and i + 1 < len(v):
            nxt = v[i + 1]
            out.append({"n": "\n", "t": "\t", '"': '"', "\\": "\\"}.get(nxt, "\\" + nxt))
            i += 2
            continue
        if ch == q:
            if q == "'" and i + 1 < len(v) and v[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            if v[i + 1:].strip():
                raise ValueError(f"line {n}: unexpected text after the closing quote")
            return "".join(out)
        out.append(ch)
        i += 1
    raise ValueError(f"line {n}: unterminated quoted string")


_DEEP = "line {n}: structures deeper than one level are not supported (nested maps, lists of lists, maps in inline lists)"


def _scalar(v, n, allow="both"):
    """Parse one value. `allow` says which inline containers this position may hold: both, list, map or none."""
    v = v.strip()
    if v == "":
        return ""
    if v[0] in "\"'":
        return _quoted(v, n)
    if v[0] == "[":
        if allow not in ("both", "list"):
            raise ValueError(_DEEP.format(n=n))
        if not v.endswith("]"):
            raise ValueError(f"line {n}: unterminated inline list (missing ']')")
        return [_scalar(p, n, "none") for p in _split_top(v[1:-1], n)]
    if v[0] == "{":
        if allow not in ("both", "map"):
            raise ValueError(_DEEP.format(n=n))
        return _flow_map(v, n)
    if _INT.match(v):
        return int(v)
    if v == "true":
        return True
    if v == "false":
        return False
    if v in ("null", "~"):
        return None
    return v


def _flow_map(v, n):
    if not v.endswith("}"):
        raise ValueError(f"line {n}: unterminated inline map (missing '}}')")
    out = {}
    for tok in _split_top(v[1:-1], n):
        idx, quote = None, None
        for i, ch in enumerate(tok):
            if quote:
                if ch == quote:
                    quote = None
            elif ch in "\"'":
                quote = ch
            elif ch == ":" and (i + 1 == len(tok) or tok[i + 1] == " "):
                idx = i
                break
        if idx is None:
            raise ValueError(f"line {n}: inline map entry '{tok}' is not 'key: value'")
        key = tok[:idx].strip()
        if key in out:
            raise ValueError(f"line {n}: duplicate key '{key}'")
        out[key] = _scalar(tok[idx + 1:], n, "list")
    return out


# ------------------------------------------------------------------ blocks


def _indent(line):
    return len(line) - len(line.lstrip(" \t"))


def _block(block):
    """block: list of (lineno, raw line), non-blank. Returns a list, a map, or '' when empty."""
    if not block:
        return ""
    for n, raw in block:
        lead = raw[:_indent(raw)]
        if "\t" in lead:
            raise ValueError(f"line {n}: tab indentation is not allowed")
    first = block[0][1].strip()
    if first == "-" or first.startswith("- "):
        items = []
        for n, raw in block:
            s = raw.strip()
            if s == "-" or s.startswith("- "):
                items.append(_scalar(s[1:].strip(), n, "map"))
            elif _KEY.match(s):
                raise ValueError(f"line {n}: cannot mix list items and key: value entries")
            else:
                raise ValueError(f"line {n}: expected '- item'")
        return items
    out = {}
    base = _indent(block[0][1])
    for n, raw in block:
        s = raw.strip()
        if s == "-" or s.startswith("- "):
            raise ValueError(f"line {n}: cannot mix list items and key: value entries")
        if _indent(raw) != base:
            raise ValueError(_DEEP.format(n=n))
        m = _KEY.match(s)
        if not m:
            raise ValueError(f"line {n}: expected 'key: value'")
        key, val = m.group(1), (m.group(2) or "").strip()
        if key in out:
            raise ValueError(f"line {n}: duplicate key '{key}'")
        out[key] = _scalar(val, n, "list")
    return out


def parse(text):
    """Return (meta, body). meta is a dict; body is the text after the closing dashes line."""
    lines = _lines(text)
    i = 0
    while i < len(lines) and (not lines[i].strip() or _COMMENT.match(lines[i])):
        i += 1
    if i >= len(lines) or lines[i].strip() != "---":
        raise ValueError(f"line {min(i + 1, max(len(lines), 1))}: front matter must start with a '---' line")
    j = i + 1
    while j < len(lines) and lines[j].strip() != "---":
        j += 1
    if j >= len(lines):
        raise ValueError(f"line {i + 1}: front matter not closed (no closing '---' line)")
    meta = {}
    k = i + 1
    while k < j:
        raw = lines[k]
        n = k + 1
        if not raw.strip():
            k += 1
            continue
        if raw[0] in " \t":
            raise ValueError(f"line {n}: indented line without a key above it")
        m = _KEY.match(raw.rstrip())
        if not m:
            raise ValueError(f"line {n}: expected 'key: value'")
        key, val = m.group(1), (m.group(2) or "").strip()
        if key in meta:
            raise ValueError(f"line {n}: duplicate key '{key}'")
        k += 1
        if val == "":
            block = []
            while k < j and (not lines[k].strip() or lines[k][0] in " \t"):
                if lines[k].strip():
                    block.append((k + 1, lines[k]))
                k += 1
            meta[key] = _block(block)
        else:
            meta[key] = _scalar(val, n)
    return meta, "\n".join(lines[j + 1:])


# ------------------------------------------------------------------ sections and tables


def _walk(body):
    """Yield (lineno, line, in_fence) for every body line."""
    fence = None
    for n, line in enumerate(_lines(body), 1):
        m = _FENCE.match(line)
        if m:
            if fence is None:
                fence = m.group(1)
                yield n, line, True
                continue
            if m.group(1) == fence:
                fence = None
                yield n, line, True
                continue
        yield n, line, fence is not None


def sections(body):
    """Level-2 titles in order (fenced code is ignored)."""
    return [line[3:].strip() for _, line, fenced in _walk(body) if not fenced and line.startswith("## ")]


def section_bodies(body):
    """Map of level-2 title to its text (first occurrence wins)."""
    out, title, buf = {}, None, []
    for _, line, fenced in _walk(body):
        if not fenced and line.startswith("## "):
            if title is not None and title not in out:
                out[title] = "\n".join(buf)
            title, buf = line[3:].strip(), []
        elif title is not None:
            buf.append(line)
    if title is not None and title not in out:
        out[title] = "\n".join(buf)
    return out


def _cells(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|") and not s.endswith("\\|"):
        s = s[:-1]
    return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]


def section_tables(body):
    """List of (section title or None, headers, rows) for every pipe table outside code fences."""
    walked = list(_walk(body))
    out, title, i = [], None, 0
    while i < len(walked):
        n, line, fenced = walked[i]
        if not fenced and line.startswith("## "):
            title = line[3:].strip()
        if (not fenced and line.strip().startswith("|") and i + 1 < len(walked) and not walked[i + 1][2]
                and "|" in walked[i + 1][1] and _SEP.match(walked[i + 1][1].strip())):
            headers = _cells(line)
            rows = []
            i += 2
            while i < len(walked) and not walked[i][2] and walked[i][1].strip().startswith("|"):
                rn, rline, _ = walked[i]
                cells = _cells(rline)
                if len(cells) != len(headers):
                    raise ValueError(f"line {rn}: row has {len(cells)} cells, the header has {len(headers)}")
                rows.append(cells)
                i += 1
            out.append((title, headers, rows))
            continue
        i += 1
    return out


def tables(body):
    """List of (headers, rows) for every pipe table outside code fences."""
    return [(h, r) for _, h, r in section_tables(body)]
