"""What the tdd area reads out of a test file: its normalized hash, the requirement ids it names, the markers that
weaken a test and its assertion count.

Python is read with the `ast` module (a marker or assertion inside a string or a comment is never counted);
JavaScript and TypeScript are read on the text with comments and string literals removed.
"""
import ast
import hashlib
import re
from collections import Counter

LANG_BY_EXT = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "javascript", ".tsx": "javascript",
               ".mjs": "javascript", ".cjs": "javascript", ".mts": "javascript", ".cts": "javascript"}

# The markers that make a test weaker without deleting it. A Python entry matches a dotted name as written
# (`unittest.skip`, `pytest.mark.xfail`) or its tail (`skip`, `mark.xfail`, as after `from unittest import skip`).
DEFAULT_MARKERS = {
    "python": ["unittest.skip", "unittest.skipIf", "unittest.skipUnless", "unittest.expectedFailure",
               "pytest.mark.skip", "pytest.mark.skipif", "pytest.mark.xfail", "pytest.skip"],
    "javascript": ["it.only", "describe.only", "test.only", "it.skip", "describe.skip", "test.skip", "xit", "xdescribe",
                   "test.todo"],
}

REQ_ID = re.compile(r"REQ-[A-Z0-9]+-\d{3}", re.ASCII)
REQ_LINE = re.compile(r"^\W*REQ:(.*)$", re.ASCII)


class UnparsableTestFile(ValueError):
    """A test file that cannot be read, so its markers and assertions cannot be counted."""


def normalized_sha256(data):
    """SHA-256 of the bytes with CRLF read as LF, so a Windows checkout hashes like a Unix one."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def requirement_ids(text):
    """Requirement ids named on marker lines (`# REQ: REQ-X-001, REQ-X-002` or `// REQ: ...`), in order, once each."""
    found = []
    for line in text.splitlines():
        m = REQ_LINE.match(line.strip())
        if m:
            for rid in REQ_ID.findall(m.group(1)):
                if rid not in found:
                    found.append(rid)
    return found


def language_of(path):
    name = str(path).lower()
    for ext, lang in LANG_BY_EXT.items():
        if name.endswith(ext):
            return lang
    return None


def is_test_path(path):
    """A test file by its name: `test_*.py`, `*_test.py`, `*.test.*`, `*.spec.*` or anything under `__tests__`."""
    p = str(path).replace("\\", "/")
    lang = language_of(p)
    if lang is None:
        return False
    base = p.rsplit("/", 1)[-1]
    if lang == "python":
        return base.startswith("test_") or base.rsplit(".", 1)[0].endswith("_test")
    return bool(re.search(r"\.(test|spec)\.[a-z]+$", base)) or "/__tests__/" in "/" + p


# ------------------------------------------------------------------ JavaScript and TypeScript text


def strip_js(text):
    """The text with comments and the content of string literals (quotes, template literals) blanked out. Newlines stay."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if ch == "/" and nxt == "/":
            while i < n and text[i] != "\n":
                i += 1
        elif ch == "/" and nxt == "*":
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append("\n" * text.count("\n", i, end))
            i = end
        elif ch in "'\"`":
            out.append(ch)
            i += 1
            while i < n and text[i] != ch:
                if text[i] == "\\":
                    i += 1
                if i < n and text[i] == "\n" and ch != "`":
                    break
                if i < n and text[i] == "\n":
                    out.append("\n")
                i += 1
            out.append(ch)
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _js_marker_pattern(marker):
    return re.compile(r"(?<![\w$.])" + r"\s*\.\s*".join(re.escape(part) for part in marker.split(".")) + r"(?![\w$])")


# ------------------------------------------------------------------ Python


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _py_matches(dotted, markers):
    return any(dotted == m or m.endswith("." + dotted) for m in markers)


def _parse_python(path, text):
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        raise UnparsableTestFile(f"{path}: cannot parse ({exc.__class__.__name__}: {getattr(exc, 'msg', exc)})") from exc


def _python_markers(path, text, markers):
    tree = _parse_python(path, text)
    found, used = Counter(), set()
    for node in ast.walk(tree):   # parents come before children, so a chain used as a call or decorator is counted once
        candidates = []
        if isinstance(node, ast.Call):
            candidates.append(node.func)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            candidates.extend(d for d in node.decorator_list if not isinstance(d, ast.Call))
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and id(node) not in used:
            candidates.append(node)
        for target in candidates:
            used.add(id(target))
            dotted = _dotted(target)
            if dotted and _py_matches(dotted, markers):
                found[dotted] += 1
    return found


def _python_assertions(path, text):
    tree = _parse_python(path, text)
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            count += 1
        elif isinstance(node, ast.Call):
            name = node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id if isinstance(node.func, ast.Name) else ""
            if name.startswith("assert"):
                count += 1
    return count


# ------------------------------------------------------------------ public


def weakening_markers(path, text, markers=None):
    """Counter of the weakening markers in a test file (keyed by the name as written). `markers` is
    `{"python": [...], "javascript": [...]}` and replaces the default list of a language it names. A Python file that does
    not parse raises UnparsableTestFile."""
    lang = language_of(path)
    if lang is None:
        return Counter()
    names = list((markers or {}).get(lang) or DEFAULT_MARKERS[lang])
    if lang == "python":
        return _python_markers(path, text, names)
    code = strip_js(text)
    found = Counter()
    for marker in names:
        n = len(_js_marker_pattern(marker).findall(code))
        if n:
            found[marker] += n
    return found


def assertion_count(path, text):
    """Assertions in a test file: Python `assert` statements plus calls to `assert*` functions and methods; JavaScript and
    TypeScript `expect(` and `assert(` (also `assert.x(`) calls. None for a file of another language."""
    lang = language_of(path)
    if lang is None:
        return None
    if lang == "python":
        return _python_assertions(path, text)
    code = strip_js(text)
    return len(re.findall(r"(?<![\w$.])(?:expect\s*\(|assert(?:\s*\.\s*\w+)?\s*\()", code))
