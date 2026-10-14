"""What the tdd area reads out of a test file: its normalized hash, the requirement ids it names, the markers that
weaken a test and its assertion count.

Python is read with the `ast` module (a marker or assertion inside a string or a comment is never counted, an import
alias is resolved to the module it names, an assertion that cannot run or that is swallowed is not counted); JavaScript
and TypeScript are read on the text with comments, string literals and regular-expression literals removed.
"""
import ast
import hashlib
import re
from collections import Counter

LANG_BY_EXT = {".py": "python", ".js": "javascript", ".jsx": "javascript", ".ts": "javascript", ".tsx": "javascript",
               ".mjs": "javascript", ".cjs": "javascript", ".mts": "javascript", ".cts": "javascript"}

# The markers that make a test weaker without deleting it. A Python entry with a dot is compared with the dotted name
# after its import aliases are resolved (`import unittest as u; @u.skip` is `unittest.skip`); an entry without a dot
# matches the last part of any dotted name (`self.skipTest`). A JavaScript entry is a name or `base.member`; the member
# is also found through brackets (`it['only']`), a member prefix (`globalThis.it.only`) and destructuring.
DEFAULT_MARKERS = {
    "python": ["unittest.skip", "unittest.skipIf", "unittest.skipUnless", "unittest.expectedFailure", "unittest.SkipTest",
               "pytest.mark.skip", "pytest.mark.skipif", "pytest.mark.xfail", "pytest.skip", "pytest.importorskip", "skipTest"],
    "javascript": ["it.only", "describe.only", "test.only", "it.skip", "describe.skip", "test.skip", "xit", "xdescribe",
                   "test.todo", "describe.todo", "it.todo", "fit", "fdescribe", "xtest"],
}
# Settings files that can deselect or ignore tests; read for these options.
INI_NAMES = {"pytest.ini", "tox.ini", "setup.cfg"}
INI_PATTERN = re.compile(r"--deselect|--ignore(?:-glob)?\b|-m\s+[\"']?not\b|xfail_strict\s*=\s*(?:false|0)\b", re.IGNORECASE)
SUPPORT_DIRS = {"tests", "test", "__tests__", "fixtures"}
# Modules whose assert functions count when imported by name.
ASSERT_MODULES = ("unittest", "pytest", "numpy.testing", "pandas.testing", "hypothesis", "nose", "testtools", "django.test")

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


def _base(path):
    return str(path).replace("\\", "/").rsplit("/", 1)[-1]


def is_test_path(path):
    """A test file by its name: `test_*.py`, `*_test.py`, `*.test.*`, `*.spec.*` or anything under `__tests__`."""
    p = str(path).replace("\\", "/")
    lang = language_of(p)
    if lang is None:
        return False
    base = _base(p)
    if lang == "python":
        return base.startswith("test_") or base.rsplit(".", 1)[0].endswith("_test")
    return bool(re.search(r"\.(test|spec)\.[a-z]+$", base)) or "/__tests__/" in "/" + p


def is_test_support(path):
    """A test file, or any file under a `tests`, `test`, `__tests__` or `fixtures` folder."""
    p = str(path).replace("\\", "/")
    return is_test_path(p) or bool(set(p.split("/")[:-1]) & SUPPORT_DIRS)


def is_marker_file(path):
    """A file that is not a test but can skip or neuter every test: `conftest.py`, an `__init__.py` under a test folder
    and the settings files of the test runner."""
    p = str(path).replace("\\", "/")
    base = _base(p)
    if base in INI_NAMES or base == "conftest.py":
        return True
    return base == "__init__.py" and bool(set(p.split("/")[:-1]) & SUPPORT_DIRS)


# ------------------------------------------------------------------ JavaScript and TypeScript text

_REGEX_AFTER_CHAR = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_AFTER_WORD = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw", "yield", "await"}


def strip_js(text, keep_strings=False):
    """The text with comments and regular-expression literals blanked out, and the content of string literals too
    (quotes, template literals) unless `keep_strings`. Newlines inside comments stay."""
    out, i, n = [], 0, len(text)

    def regex_allowed():
        tail = "".join(out[-24:]).rstrip()
        if not tail or tail[-1] in _REGEX_AFTER_CHAR:
            return True
        m = re.search(r"([A-Za-z_$][\w$]*)$", tail)
        return bool(m and m.group(1) in _REGEX_AFTER_WORD)

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
                    if keep_strings:
                        out.append(text[i])
                    i += 1
                if i < n and text[i] == "\n" and ch != "`":
                    break
                if i < n:
                    if text[i] == "\n":
                        out.append("\n")
                    elif keep_strings:
                        out.append(text[i])
                i += 1
            out.append(ch)
            i += 1
        elif ch == "/" and regex_allowed():
            j, in_class, end = i + 1, False, None
            while j < n:
                c = text[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "\n":
                    break
                if c == "[":
                    in_class = True
                elif c == "]":
                    in_class = False
                elif c == "/" and not in_class:
                    end = j
                    break
                j += 1
            if end is None:
                out.append(ch)
                i += 1
            else:
                out.append("/ /")
                i = end + 1
                while i < n and text[i].isalpha():
                    i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _js_patterns(marker):
    """The regular expressions that find one marker, as (pattern, uses the text with strings kept)."""
    prefix = r"(?<![\w$])(?:[\w$]+\s*\.\s*)*"
    if "." not in marker:
        return [(re.compile(prefix + re.escape(marker) + r"(?![\w$])"), False)]
    base, member = (re.escape(part) for part in marker.split(".", 1))
    return [
        (re.compile(prefix + base + r"\s*\.\s*" + member + r"(?![\w$])"), False),
        (re.compile(prefix + base + r"\s*\[\s*['\"]" + member + r"['\"]\s*\]"), True),
        (re.compile(r"\{[^{}]*\b" + member + r"\b[^{}]*\}\s*=\s*(?:[\w$]+\s*\.\s*)*" + base + r"(?![\w$])"), False),
    ]


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


def _aliases(tree):
    """{local name: what it stands for}: `import unittest as u` gives u -> unittest; `from unittest import skip as s`
    gives s -> unittest.skip."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[(a.asname or a.name).split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _canonical(dotted, aliases):
    first, _, rest = dotted.partition(".")
    if first in aliases:
        return aliases[first] + ("." + rest if rest else "")
    return dotted


def _py_matches(raw, canon, markers, aliases):
    first = raw.split(".")[0]
    for m in markers:
        if "." not in m:
            if raw.split(".")[-1] == m:
                return True
        elif canon == m or (first not in aliases and m.endswith("." + raw)):
            return True
    return False


def _parse_python(path, text):
    try:
        return ast.parse(text)
    except (SyntaxError, ValueError) as exc:
        raise UnparsableTestFile(f"{path}: cannot parse ({exc.__class__.__name__}: {getattr(exc, 'msg', exc)})") from exc


def _getattr_module(call, aliases):
    """The `unittest` or `pytest` module a `getattr(module, name)` call reaches into, else None."""
    if isinstance(call.func, ast.Name) and call.func.id == "getattr" and call.args:
        dotted = _dotted(call.args[0])
        if dotted:
            canon = _canonical(dotted, aliases)
            if canon.split(".")[0] in ("unittest", "pytest"):
                return canon
    return None


def _python_markers(path, text, markers):
    tree = _parse_python(path, text)
    aliases = _aliases(tree)
    found, used = Counter(), set()
    for node in ast.walk(tree):   # parents come before children, so a chain used as a call or decorator is counted once
        candidates = []
        if isinstance(node, ast.Call):
            candidates.append(node.func)
            module = _getattr_module(node, aliases)
            if module:
                found[f"getattr({module}, ...)"] += 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            candidates.extend(d for d in node.decorator_list if not isinstance(d, ast.Call))
        elif isinstance(node, ast.Raise) and isinstance(node.exc, (ast.Name, ast.Attribute)):
            candidates.append(node.exc)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and id(node) not in used:
            candidates.append(node)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                dotted = _dotted(target) if isinstance(target, ast.Attribute) else None
                if dotted:
                    canon = _canonical(dotted, aliases)
                    if canon.startswith(("unittest.TestCase", "unittest.TestResult", "unittest.TestSuite", "unittest.TestLoader")):
                        found[f"assignment to {canon}"] += 1
        for target in candidates:
            used.add(id(target))
            dotted = _dotted(target)
            if dotted:
                canon = _canonical(dotted, aliases)
                if _py_matches(dotted, canon, markers, aliases):
                    found[canon] += 1
    return found


def _const_truth(node):
    """True or False for a constant test, None when the test is not constant."""
    if isinstance(node, ast.Constant):
        return bool(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        inner = _const_truth(node.operand)
        return None if inner is None else not inner
    return None


def _catches_assertion(handler):
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any((_dotted(t) or "").split(".")[-1] in ("AssertionError", "Exception", "BaseException") for t in types)


def _asserts_in(node):
    """Whether a function body holds an assertion of its own."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assert):
            return True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr.startswith("assert"):
            return True
    return False


class _AssertionCounter(ast.NodeVisitor):
    def __init__(self, trusted, asserting):
        self.count = 0
        self.trusted = trusted
        self.asserting = asserting

    def visit_Assert(self, node):
        self.count += 1

    def visit_If(self, node):
        truth = _const_truth(node.test)
        if truth is None:
            self.generic_visit(node)
        else:
            for child in (node.body if truth else node.orelse):
                self.visit(child)

    def visit_While(self, node):
        if _const_truth(node.test) is False:
            for child in node.orelse:
                self.visit(child)
        else:
            self.generic_visit(node)

    def visit_Try(self, node):
        if not any(_catches_assertion(h) for h in node.handlers):
            for child in node.body:
                self.visit(child)
        for child in node.handlers + node.orelse + node.finalbody:
            self.visit(child)

    visit_TryStar = visit_Try

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr.startswith("assert"):
            self.count += 1
        elif isinstance(func, ast.Name) and func.id.startswith("assert") and (func.id in self.trusted or func.id in self.asserting):
            self.count += 1
        self.generic_visit(node)


def _python_assertions(path, text, extra_modules=()):
    tree = _parse_python(path, text)
    modules = tuple(ASSERT_MODULES) + tuple(extra_modules)
    trusted = {name for name, target in _aliases(tree).items()
               if any(target.rsplit(".", 1)[0] == m or target.rsplit(".", 1)[0].startswith(m + ".") for m in modules)}
    asserting = {n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _asserts_in(n)}
    counter = _AssertionCounter(trusted, asserting)
    counter.visit(tree)
    return counter.count


# ------------------------------------------------------------------ public


def weakening_markers(path, text, markers=None):
    """Counter of the weakening markers in a file (keyed by the name as written, or resolved for Python). `markers` is
    `{"python": [...], "javascript": [...]}` and replaces the default list of a language it names. A Python file that
    does not parse raises UnparsableTestFile. The settings files of the test runner are read for options that deselect
    tests."""
    if _base(path) in INI_NAMES:
        return Counter(m.group(0).lower() for m in INI_PATTERN.finditer(text))
    lang = language_of(path)
    if lang is None:
        return Counter()
    names = list((markers or {}).get(lang) or DEFAULT_MARKERS[lang])
    if lang == "python":
        return _python_markers(path, text, names)
    code, with_strings = strip_js(text), strip_js(text, keep_strings=True)
    found = Counter()
    for marker in names:
        for pattern, wants_strings in _js_patterns(marker):
            n = len(pattern.findall(with_strings if wants_strings else code))
            if n:
                found[marker] += n
    return found


def assertion_count(path, text):
    """Assertions in a test file. Python: `assert` statements and calls of `assert*` methods, plus `assert*` functions
    imported from unittest, pytest and the like or defined in the file with an assertion in their body; an assertion
    that cannot run (a constant false branch) or whose failure is swallowed (a try that catches AssertionError) is not
    counted. JavaScript and TypeScript: `expect(` and `assert(` (also `assert.x(`) calls. None for another language."""
    lang = language_of(path)
    if lang is None:
        return None
    if lang == "python":
        return _python_assertions(path, text)
    code = strip_js(text)
    return len(re.findall(r"(?<![\w$.])(?:expect\s*\(|assert(?:\s*\.\s*\w+)?\s*\()", code))
