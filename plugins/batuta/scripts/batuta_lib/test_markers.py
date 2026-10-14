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
# Settings files that can deselect or ignore tests; read for these options (`pyproject.toml` and `setup.cfg` only in their
# pytest sections).
INI_NAMES = {"pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml"}
INI_PATTERN = re.compile(r"--deselect|--ignore(?:-glob)?\b|(?<![\w-])-k\b|-m\s+[\"']?not\b|xfail_strict\s*=\s*(?:false|0)\b|"
                         r"\b(?:python_files|python_classes|python_functions|testpaths|norecursedirs)\b\s*[=:]", re.IGNORECASE)
_PYTEST_SECTIONS = {"pyproject.toml": ("[tool.pytest",), "setup.cfg": ("[tool:pytest]", "[pytest]")}
# Names whose definition in a Python file changes what the runner collects.
COLLECTION_FUNCTIONS = {"load_tests", "pytest_collection_modifyitems"}
COLLECTION_VARIABLES = {"collect_ignore", "collect_ignore_glob"}
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


def is_test_config_file(path):
    """A file that configures how the runner collects tests: `conftest.py` and the settings files of the runner."""
    base = _base(path)
    return base in INI_NAMES or base == "conftest.py"


def _pytest_text(path, text):
    """The part of a settings file that configures pytest: all of `pytest.ini` and `tox.ini`, the pytest sections of
    `pyproject.toml` and `setup.cfg`."""
    prefixes = _PYTEST_SECTIONS.get(_base(path))
    if prefixes is None:
        return text
    kept, keep = [], False
    for line in text.splitlines():
        if line.lstrip().startswith("["):
            keep = line.strip().lower().startswith(prefixes)
        if keep:
            kept.append(line)
    return "\n".join(kept)


def test_config_text(path, text):
    """What of a file counts as test configuration: all of a `conftest.py`, the pytest part of a settings file; None for
    any other file."""
    if not is_test_config_file(path):
        return None
    return text if _base(path) == "conftest.py" else _pytest_text(path, text)


# ------------------------------------------------------------------ JavaScript and TypeScript text

_REGEX_AFTER_CHAR = set("(,=:[!&|?{};+-*%<>~^")
_REGEX_AFTER_WORD = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw", "yield", "await"}


def strip_js(text, keep_strings=False):
    """The text with comments and regular-expression literals blanked out, and the content of string literals too
    (quotes, template literals) unless `keep_strings`. Newlines inside comments stay."""
    out, i, n = [], 0, len(text)
    parens, closed_by_keyword = [], False   # was each open parenthesis opened by if, while, for or with

    def regex_allowed():
        tail = "".join(out[-24:]).rstrip()
        if not tail or tail[-1] in _REGEX_AFTER_CHAR:
            return True
        if tail[-1] == ")":
            return closed_by_keyword   # `if (x) /re/.test(y)` is a regular expression, `(a) / b` a division
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
            if ch == "(":
                m = re.search(r"([A-Za-z_$][\w$]*)$", "".join(out[-12:]).rstrip())
                parens.append(bool(m and m.group(1) in ("if", "while", "for", "with")))
            elif ch == ")":
                closed_by_keyword = parens.pop() if parens else False
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
        (re.compile(prefix + base + r"\s*\[\s*['\"`]" + member + r"['\"`]\s*\]"), True),
        (re.compile(r"\{[^{}]*\b" + member + r"\b[^{}]*\}\s*=\s*(?:[\w$]+\s*\.\s*)*" + base + r"(?![\w$])"), False),
    ]


# ------------------------------------------------------------------ Python


def _is_import_call(call):
    func = call.func if isinstance(call, ast.Call) else None
    name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
    return name in ("import_module", "__import__")


def _import_target(node):
    """The module named by `importlib.import_module('m')`, `__import__('m')` or `sys.modules['m']`, else None."""
    if isinstance(node, ast.Call) and _is_import_call(node):
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            return node.args[0].value
    elif isinstance(node, ast.Subscript) and _dotted(node.value) == "sys.modules":
        key = node.slice
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            return key.value
    return None


def _dotted(node):
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    target = _import_target(node)
    if target:   # `importlib.import_module('unittest').skip`
        parts.append(target)
        return ".".join(reversed(parts))
    return None


def _aliases(tree):
    """{local name: what it stands for}: `import unittest as u` gives u -> unittest; `from unittest import skip as s`
    gives s -> unittest.skip; `u = importlib.import_module('unittest')`, `u = unittest` and `s = unittest.skip` too."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out[(a.asname or a.name).split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    for _ in range(2):   # an alias of an alias
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                target = _import_target(node.value)
                if target is None and isinstance(node.value, (ast.Name, ast.Attribute)):
                    dotted = _dotted(node.value)
                    target = _canonical(dotted, out) if dotted else None
                if target:
                    out[node.targets[0].id] = target
    return out


_CANONICAL_PREFIXES = (("unittest.case.", "unittest."), ("unittest.async_case.", "unittest."), ("_pytest.outcomes.", "pytest."),
                       ("_pytest.mark.structures.", "pytest.mark."), ("_pytest.", "pytest."))


def _canonical(dotted, aliases):
    """The name with its alias resolved and the modules that define the public names mapped to them (`unittest.case.skip` is
    `unittest.skip`, `_pytest.outcomes.skip` is `pytest.skip`)."""
    first, _, rest = dotted.partition(".")
    if first in aliases:
        dotted = aliases[first] + ("." + rest if rest else "")
    for old, new in _CANONICAL_PREFIXES:
        if dotted.startswith(old):
            return new + dotted[len(old):]
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
            if _is_import_call(node) and _import_target(node) is None:
                found["import of a module by a computed name"] += 1   # nothing static can follow where it leads
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            candidates.extend(d for d in node.decorator_list if not isinstance(d, ast.Call))
            if not isinstance(node, ast.ClassDef) and node.name in COLLECTION_FUNCTIONS:
                found[node.name] += 1   # a hook that decides which tests the runner collects
        elif isinstance(node, ast.Raise) and isinstance(node.exc, (ast.Name, ast.Attribute)):
            candidates.append(node.exc)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and id(node) not in used:
            candidates.append(node)
        elif isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id in COLLECTION_VARIABLES:
                    found[target.id] += 1
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


_PURE_NODES = (ast.Constant, ast.Compare, ast.BoolOp, ast.UnaryOp, ast.BinOp, ast.operator, ast.cmpop, ast.boolop, ast.unaryop)


def _const_truth(node):
    """True or False for a test made only of numbers, booleans and None (`False`, `0`, `1 == 2`), None when it is not constant."""
    for sub in ast.walk(node):
        if not isinstance(sub, _PURE_NODES) or isinstance(sub, (ast.Pow, ast.LShift)):
            return None
        if isinstance(sub, ast.Constant) and not (sub.value is None or isinstance(sub.value, (bool, int, float))):
            return None
        if isinstance(sub, ast.Constant) and isinstance(sub.value, int) and abs(sub.value) > 10 ** 6:
            return None
    try:
        return bool(eval(compile(ast.Expression(body=node), "<constant>", "eval"), {"__builtins__": {}}, {}))   # noqa: S307 (constants only)
    except Exception:   # noqa: BLE001
        return None


_SWALLOWED = ("AssertionError", "Exception", "BaseException")


def _catches_assertion(handler):
    if handler.type is None:
        return True
    types = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any((_dotted(t) or "").split(".")[-1] in _SWALLOWED for t in types)


def _suppresses_assertions(item):
    call = item.context_expr
    if not (isinstance(call, ast.Call) and (_dotted(call.func) or "").split(".")[-1] == "suppress"):
        return False
    return any((_dotted(a) or "").split(".")[-1] in _SWALLOWED for a in call.args)


def _asserts_in(fn):
    """Whether a function holds an assertion that can fail on what it is given: an `assert` that mentions one of its
    parameters, or a call of an `assert*` method."""
    args = fn.args
    params = {a.arg for a in args.posonlyargs + args.args + args.kwonlyargs}
    params |= {a.arg for a in (args.vararg, args.kwarg) if a}
    for sub in ast.walk(fn):
        if isinstance(sub, ast.Assert) and any(isinstance(n, ast.Name) and n.id in params for n in ast.walk(sub.test)):
            return True
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr.startswith("assert"):
            return True
    return False


_TERMINATORS = (ast.Return, ast.Raise, ast.Continue, ast.Break)


class _AssertionCounter(ast.NodeVisitor):
    def __init__(self, trusted, local_defs, referenced):
        self.count = 0
        self.trusted = trusted
        self.local_defs = local_defs   # {function name: whether it asserts}
        self.referenced = referenced   # names read somewhere in the file
        self.depth = 0                 # function nesting

    def block(self, statements):
        for child in statements:
            self.visit(child)
            if isinstance(child, _TERMINATORS):
                break   # nothing after a return, raise, continue or break runs

    def generic_visit(self, node):
        for field, value in ast.iter_fields(node):
            if isinstance(value, list):
                if value and all(isinstance(v, ast.stmt) for v in value):
                    self.block(value)
                else:
                    for child in value:
                        if isinstance(child, ast.AST):
                            self.visit(child)
            elif isinstance(value, ast.AST):
                self.visit(value)

    def visit_Assert(self, node):
        if isinstance(node.test, ast.Constant) and node.test.value:
            return   # `assert True` says nothing
        self.count += 1

    def visit_If(self, node):
        truth = _const_truth(node.test)
        if truth is None:
            self.generic_visit(node)
        else:
            self.block(node.body if truth else node.orelse)

    def visit_While(self, node):
        if _const_truth(node.test) is False:
            self.block(node.orelse)
        else:
            self.generic_visit(node)

    def visit_Try(self, node):
        if not any(_catches_assertion(h) for h in node.handlers):
            self.block(node.body)
        for handler in node.handlers:
            self.visit(handler)
        self.block(node.orelse)
        self.block(node.finalbody)

    visit_TryStar = visit_Try

    def visit_With(self, node):
        if any(_suppresses_assertions(i) for i in node.items):
            return
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_ClassDef(self, node):
        saved, self.depth = self.depth, 0
        self.generic_visit(node)
        self.depth = saved

    def visit_FunctionDef(self, node):
        if self.depth > 0 and node.name not in self.referenced:
            return   # a nested function nobody uses runs nothing
        self.depth += 1
        self.generic_visit(node)
        self.depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr.startswith("assert"):
            if self.local_defs.get(func.attr, True):   # a method the file defines counts only when it asserts
                self.count += 1
        elif isinstance(func, ast.Name) and func.id.startswith("assert"):
            if func.id in self.trusted or self.local_defs.get(func.id, False):
                self.count += 1
        self.generic_visit(node)


def _python_assertions(path, text, extra_modules=()):
    tree = _parse_python(path, text)
    modules = tuple(ASSERT_MODULES) + tuple(extra_modules)
    trusted = {name for name, target in _aliases(tree).items()
               if any(target.rsplit(".", 1)[0] == m or target.rsplit(".", 1)[0].startswith(m + ".") for m in modules)}
    local_defs = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            local_defs[n.name] = local_defs.get(n.name, False) or _asserts_in(n)
    referenced = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    counter = _AssertionCounter(trusted, local_defs, referenced)
    counter.visit(tree)
    return counter.count


# ------------------------------------------------------------------ public


def weakening_markers(path, text, markers=None):
    """Counter of the weakening markers in a file (keyed by the name as written, or resolved for Python). `markers` is
    `{"python": [...], "javascript": [...]}` and adds to the default list of a language it names. A Python file that
    does not parse raises UnparsableTestFile. The settings files of the test runner are read for options that deselect
    tests."""
    if _base(path) in INI_NAMES:
        return Counter(m.group(0).strip().lower() for m in INI_PATTERN.finditer(_pytest_text(path, text)))
    lang = language_of(path)
    if lang is None:
        return Counter()
    # a configured name adds to the defaults: a project cannot remove a default marker by configuration
    names = list(DEFAULT_MARKERS[lang]) + [m for m in (markers or {}).get(lang, []) if m not in DEFAULT_MARKERS[lang]]
    if lang == "python":
        return _python_markers(path, text, names)
    code, with_strings = strip_js(text), strip_js(text, keep_strings=True)
    aliases = {}   # `const t = it;` makes t another name of it
    for m in re.finditer(r"\b(?:const|let|var)\s+([\w$]+)\s*=\s*([\w$]+)\s*(?:;|\n|$)", code):
        aliases.setdefault(m.group(2), []).append(m.group(1))
    found = Counter()
    for marker in names:
        spellings = [marker]
        if "." in marker:
            base, member = marker.split(".", 1)
            spellings += [f"{alias}.{member}" for alias in aliases.get(base, [])]
        for spelling in spellings:
            for pattern, wants_strings in _js_patterns(spelling):
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
