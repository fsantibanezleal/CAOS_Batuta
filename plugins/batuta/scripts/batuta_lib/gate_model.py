"""The gate model: lifecycle order, the status file (C10), the hash-bound approval (C06) and the rules of `gate check`.

Every lifecycle gate ends with an evidence file from an agent that did not build the result (`evidence.py`). `check_feature`
enforces, on artifacts and never on prompts: strict gate order, valid evidence for every passed gate on the routed role and
model, evidence commits that belong to the history and never go backwards, a valid approval for the freeze (hashes recomputed
here from the contract's definition), dated human waivers, a phase that follows the gates, and the release rules at L9.

Git is reached only through the `Git` class (module variable `GIT`), so a test can stand in for it: a real git process is
slow on a loaded machine.
"""
import datetime
import hashlib
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from batuta_lib import config, evidence
from batuta_lib import contract as core
from batuta_lib import frontmatter as fm
from batuta_lib.output import item

GATES = evidence.core_gates()
COMPLETE = ("passed", "waived")
STATES = ("pending", "passed", "failed", "waived")
EVIDENCE_VERDICTS = ("PASS", "PASS-WITH-FIXES")
AGENT_TOKENS = {"searcher", "runner", "implementer", "test-author", "doc-writer", "adversary", "reviewer", "script",
                "agent", "subagent", "assistant", "claude", "batuta", "bot"}
COMMIT_HEX = re.compile(r"[0-9a-fA-F]{4,64}\Z", re.ASCII)


# ------------------------------------------------------------------ git

class Git:
    """The questions the gates ask of a repository. Paths are relative to the folder asked about."""

    def __init__(self, timeout=60):
        self.timeout = timeout
        self._prefixes = {}

    def _run(self, root, *args):
        try:
            p = subprocess.run(["git", "-c", "core.quotepath=off", "-C", str(root), *args], capture_output=True, text=True,
                               encoding="utf-8", errors="replace", timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 127, f"git could not run: {exc}"
        return p.returncode, (p.stdout if p.returncode == 0 else (p.stderr or p.stdout))

    def info(self, root):
        """(prefix of root inside its repository, full HEAD sha), or None when root is not in a repository or has no commit."""
        rc, out = self._run(root, "rev-parse", "--show-prefix", "HEAD")
        lines = out.splitlines()
        if rc != 0 or len(lines) < 2:
            return None
        self._prefixes[str(root)] = lines[0].strip()
        return lines[0].strip(), lines[1].strip()

    def _prefix(self, root):
        key = str(root)
        if key not in self._prefixes:
            rc, out = self._run(root, "rev-parse", "--show-prefix")
            self._prefixes[key] = out.strip() if rc == 0 else ""
        return self._prefixes[key]

    def history(self, root, head):
        rc, out = self._run(root, "rev-list", "--topo-order", head)
        return out.split() if rc == 0 else []

    def is_ancestor(self, root, a, b):
        return self._run(root, "merge-base", "--is-ancestor", a, b)[0] == 0

    def changed(self, root, a, b):
        rc, out = self._run(root, "diff", "--name-only", "--relative", a, b)
        return out.splitlines() if rc == 0 else []

    def dirty(self, root):
        """Paths with uncommitted changes (modified, staged, untracked), or None outside a repository."""
        rc, out = self._run(root, "status", "--porcelain", "-z", "--untracked-files=all", ".")
        if rc != 0:
            return None
        prefix, paths, entries, i = self._prefix(root), [], out.split("\0"), 0
        while i < len(entries):
            entry = entries[i]
            i += 1
            if len(entry) < 4:
                continue
            path = entry[3:]
            if entry[0] in "RC":
                i += 1
            paths.append(path[len(prefix):] if prefix and path.startswith(prefix) else path)
        return paths

    def last_commit(self, root, relpath):
        rc, out = self._run(root, "log", "-1", "--format=%H", "--", relpath)
        return out.strip() or None if rc == 0 else None

    def count_since(self, root, since, head, excludes):
        """Commits in since..head that changed a path outside every exclusion (a folder or a file; one or a list)."""
        excludes = [excludes] if isinstance(excludes, str) else list(excludes)
        rc, out = self._run(root, "rev-list", "--count", f"{since}..{head}", "--", ".", *[f":(exclude){e}" for e in excludes])
        return int(out.strip()) if rc == 0 and out.strip().isdigit() else 0

    def merge_base(self, root, ref):
        """The newest common ancestor of `ref` and HEAD, or None."""
        rc, out = self._run(root, "merge-base", ref, "HEAD")
        return out.strip() or None if rc == 0 else None

    def log_files(self, root, head, limit):
        """[(sha, [paths])], newest first, for at most `limit` commits ending at `head`."""
        rc, out = self._run(root, "log", "--name-only", "--format=%x01%H", "--relative", "-n", str(limit), head)
        if rc != 0:
            return []
        commits = []
        for block in out.split("\x01")[1:]:
            lines = block.split("\n")
            commits.append((lines[0].strip(), [x for x in lines[1:] if x.strip()]))
        return commits

    def show(self, root, ref, relpath):
        rc, out = self._run(root, "show", f"{ref}:./{relpath}")
        return out if rc == 0 else None

    def branch(self, root):
        rc, out = self._run(root, "rev-parse", "--abbrev-ref", "HEAD")
        return out.strip() if rc == 0 else None

    def rev(self, root, ref):
        rc, out = self._run(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        return out.strip() if rc == 0 and out.strip() else None

    def merge(self, root, sha, message):
        return self._run(root, "merge", "--no-ff", "-m", message, sha)


GIT = Git()


# ------------------------------------------------------------------ files

def today_iso():
    return datetime.date.today().isoformat()


def write_atomic(path, text):
    """Write UTF-8 with LF through a temp file in the same folder, then `os.replace`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=path.suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.replace("\r\n", "\n").encode("utf-8"))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read(path):
    return Path(path).read_text(encoding="utf-8-sig")


def sha256_variants(path):
    """The SHA-256 of a file as written and with CRLF read as LF: a checkout on another platform may change line
    endings, and the approval holds when either matches."""
    data = Path(path).read_bytes()
    return {hashlib.sha256(data).hexdigest(), hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()}


def spec_dir(root, feature):
    return Path(root) / "specs" / feature


def evidence_path(root, feature, gate):
    return spec_dir(root, feature) / "evidence" / f"{gate}.md"


def project_config(args_config, root):
    return config.load(config_arg=args_config, project_root=root).config


# ------------------------------------------------------------------ status file (C10)

def _schema_spec(cid):
    sp = core.find_schema(config.contracts_dir(), cid)
    if sp is None:
        raise ValueError(f"the {cid} schema is not found in {config.contracts_dir()}")
    return core.load_schema(sp), core.load_sections_spec(sp) if sp.with_name(sp.name.replace(".schema.json", ".sections.json")).is_file() else None


def status_errors(text):
    """Problems of a status text against C10, comments stripped first."""
    schema, spec = _schema_spec("C10")
    return core.validate_markdown(evidence.strip_comments(text), schema, spec)


class Status:
    def __init__(self, path, prefix, meta, body, text):
        self.path, self.prefix, self.meta, self.body, self.text = path, prefix, meta, body, text

    def state(self, gate):
        return self.meta.get("gates", {}).get(gate, "pending")

    def first_incomplete(self):
        return next((g for g in GATES if self.state(g) not in COMPLETE), None)

    def expected_phase(self):
        return self.first_incomplete() or "done"

    def waivers(self):
        w = self.meta.get("waivers", [])
        return w if isinstance(w, list) else []


def load_status(root, feature):
    """(Status or None, items). The text is read with comments stripped, so an example in a comment never counts."""
    path = spec_dir(root, feature) / "status.md"
    rel = path.relative_to(root).as_posix() if str(path).startswith(str(root)) else path.as_posix()
    if not path.is_file():
        return None, [item("FAIL", f"status file not found: {rel}", rel)]
    try:
        text = read(path)
    except (OSError, UnicodeDecodeError) as exc:
        return None, [item("FAIL", f"cannot read {rel}: {exc}", rel)]
    errors = status_errors(text)
    if errors:
        return None, [item("FAIL", f"{rel} does not satisfy C10: {e}", rel) for e in errors]
    stripped = evidence.strip_comments(text)
    meta, stripped_body = fm.parse(stripped)
    try:
        body = fm.parse(text)[1]
    except ValueError:
        body = stripped_body
    prefix = ""
    for line in text.lstrip("ï»¿").split("\n"):
        if line.strip() == "---":
            break
        prefix += line + "\n"
    if meta.get("feature") != feature:
        return None, [item("FAIL", f"{rel} is the status of {meta.get('feature')!r}, not {feature!r}", rel)]
    return Status(path, prefix, meta, body, text), []


def _scalar(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return "null"
    if isinstance(v, int):
        return str(v)
    s = str(v)
    if re.fullmatch(r"[A-Za-z0-9_./ -]+", s) and s == s.strip() and not re.fullmatch(r"-?\d+|true|false|null", s) \
            and not s.startswith("- ") and s != "-":
        return s
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _value(v):
    if isinstance(v, list):
        return "[" + ", ".join(_scalar(x) for x in v) + "]"
    return _scalar(v)


def render_status(prefix, meta, body):
    """The status text again: the front matter in the subset `frontmatter.py` reads, the body untouched."""
    lines = ["---"]
    for key, val in meta.items():
        if isinstance(val, dict):
            if not val:
                lines.append(f"{key}: {{}}")
                continue
            lines.append(f"{key}:")
            lines.extend(f"  {k}: {_value(v)}" for k, v in val.items())
        elif isinstance(val, list) and val and all(isinstance(x, dict) for x in val):
            lines.append(f"{key}:")
            for entry in val:
                lines.append("  - {" + ", ".join(f"{k}: {_value(v)}" for k, v in entry.items()) + "}")
        else:
            lines.append(f"{key}: {_value(val)}")
    lines.append("---")
    return prefix + "\n".join(lines) + "\n" + body


def recompute_phase(meta):
    states = meta.get("gates", {})
    meta["gates"] = {g: states[g] for g in GATES if g in states}
    first = next((g for g in GATES if states.get(g, "pending") not in COMPLETE), None)
    meta["phase"] = first or "done"


# ------------------------------------------------------------------ waivers and approvals

def is_agent_name(by, roles=()):
    tokens = set(re.split(r"[^a-z0-9]+", str(by).lower())) - {""}
    names = {r.lower() for r in roles} | AGENT_TOKENS
    return bool(tokens & names) or str(by).lower().strip() in names


def waiver_problems(status, cfg, today):
    out, roles = [], cfg.get("roles", {})
    waived = [g for g in GATES if status.state(g) == "waived"]
    by_gate = {}
    for w in status.waivers():
        by_gate.setdefault(w.get("gate"), []).append(w)
        gate = w.get("gate")
        if is_agent_name(w.get("by", ""), roles):
            out.append(item("FAIL", f"waiver for {gate} is written by an agent role (by: {w.get('by')!r}); only a human grants a waiver"))
        if str(w.get("date", "")) > today:
            out.append(item("FAIL", f"waiver for {gate} is dated {w.get('date')}, after today ({today})"))
        if not str(w.get("reason", "")).strip():
            out.append(item("FAIL", f"waiver for {gate} has a blank reason"))
        if status.state(gate) not in ("waived", "passed"):   # a human waiver of L9-promote may also cover a threshold decrease
            out.append(item("WARN", f"waiver for {gate} is recorded but the gate is {status.state(gate)}"))
    for gate in waived:
        if gate not in by_gate:
            out.append(item("FAIL", f"gate {gate} is waived but has no waiver line (gate, reason, by, date) written by a human"))
    return out


def find_approval(root, feature):
    """(record dict, path) of the newest approval record, or (None, reason)."""
    folder = spec_dir(root, feature) / "approvals"
    records = []
    for p in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            doc = core.loads_strict(p.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            doc = {}
        records.append((str(doc.get("approved_at", "")) if isinstance(doc, dict) else "", p.name, p, doc))
    if not records:
        return None, f"no approval record in specs/{feature}/approvals/"
    records.sort(key=lambda r: (r[0], r[1]))
    return records[-1][3], records[-1][2]


def approval_problems(root, feature, cfg):
    """Problems that void the freeze approval of a feature (empty when it is valid): the record satisfies C06, a human
    typed the phrase, and every hashed file still has its hash."""
    root = Path(root)
    doc, where = find_approval(root, feature)
    rel = f"specs/{feature}/approvals"
    if doc is None:
        return [f"L5-freeze has no approval: {where}"]
    name = Path(where).name
    sp = core.find_schema(config.contracts_dir(), "C06")
    problems = [f"approval {name}: {e}" for e in core.validate_instance("C06", doc, core.load_schema(sp))]
    if problems:
        return problems
    if doc["spec_id"] != feature:
        problems.append(f"approval {name} is for spec {doc['spec_id']!r}, not {feature!r}")
    if is_agent_name(doc["approved_by"], cfg.get("roles", {})):
        problems.append(f"approval {name} was recorded by {doc['approved_by']!r}: an approval comes from a human")
    phrase = re.compile(rf"\b(?i:approve)\s+{re.escape(doc['spec_id'])}\s+(?i:{doc['approved_spec_sha256_prefix']})\b")
    if not phrase.search(doc["prompt_excerpt"]):
        problems.append(f"approval {name}: prompt_excerpt does not hold the typed phrase "
                        f"'approve {doc['spec_id']} {doc['approved_spec_sha256_prefix']}'")
    checks = [(f"specs/{feature}/spec.md", doc["spec_sha256"])]
    for key in ("contracts_sha256", "adrs_sha256", "named_tests_sha256"):
        checks.extend(doc[key].items())
    for relpath, want in checks:
        target = (root / relpath)
        try:
            target.resolve().relative_to(root.resolve())
        except ValueError:
            problems.append(f"approval {name}: {relpath} is outside the project")
            continue
        if not target.is_file():
            problems.append(f"approval {name} is void: {relpath} no longer exists")
        elif want not in sha256_variants(target):
            problems.append(f"approval {name} is void: {relpath} changed after it was approved")
    return problems


# ------------------------------------------------------------------ commits

def resolve_commit(history, text):
    """The full sha in `history` that `text` names (a full sha or a unique prefix of at least 4 characters), or None."""
    if not COMMIT_HEX.fullmatch(str(text)):
        return None
    hits = [h for h in history if h.startswith(str(text).lower())]
    return hits[0] if len(hits) == 1 else None


LOG_LIMIT = 500
READINESS_FILES = ("data/derived/readiness.json", "docs/design/readiness.json", "docs/design/previews.json")
RECORD_PATH = "docs/design/contract-tests.json"


def _under(path, *prefixes):
    return any(path.startswith(p) for p in prefixes)


def is_contract_path(path):
    return _under(path, "contracts/", "docs/contracts/")


def is_code_path(path):
    """The unit's code, tests and models: everything that is not a record of the method (specs, docs, contracts, the
    coordination folder, changelog fragments, top-level Markdown) nor the readiness document."""
    if _under(path, "specs/", "docs/", "contracts/", ".batuta/", "changes/") or path in READINESS_FILES:
        return False
    return not ("/" not in path and path.endswith(".md"))


def judged(gate, feature):
    """The predicate over repository paths of what a gate judges, or None when the gate has none (L9 is current against the
    whole head instead; L10 judges the lesson line)."""
    spec = {f"specs/{feature}/spec.md", f"specs/{feature}/tasks.md", f"specs/{feature}/trace.json"}
    sizing = lambda p: p == "sizing.md" or p.endswith("/sizing.md")   # noqa: E731
    decisions = lambda p: _under(p, "docs/decisions/", "docs/design/tech/")   # noqa: E731
    table = {
        "L0-understand": lambda p: p in spec,
        "L1-size": lambda p: p in spec or sizing(p),
        "L2-decide": decisions,
        "L3-contracts": is_contract_path,
        "L4-boundaries": lambda p: is_contract_path(p) or p.startswith("models/"),
        "L5-freeze": lambda p: p in spec or is_contract_path(p) or decisions(p),
        "L6-skeleton": lambda p: is_code_path(p) or p in READINESS_FILES,
        "L7-build": is_code_path,
        "L8-integrate": lambda p: is_code_path(p) or p in READINESS_FILES,
    }
    return table.get(gate)


class Repo:
    """What one `gate check` knows of the repository, gathered once."""

    def __init__(self, root, head=None):
        self.root = root
        info = GIT.info(root)
        self.ok = info is not None
        self.head = head or (info[1] if info else None)
        self.history = GIT.history(root, self.head) if self.ok and self.head else []
        self._anc = {}
        self._log = None

    def newest_change(self, predicate):
        """(commit, path) of the newest commit that changed a path the predicate accepts, or None."""
        if self._log is None:
            self._log = GIT.log_files(self.root, self.head, LOG_LIMIT) if self.ok and self.head else []
        for sha, paths in self._log:
            for p in paths:
                if predicate(p):
                    return sha, p
        return None

    def full(self, text):
        return resolve_commit(self.history, text)

    def ancestor(self, a, b):
        key = (a, b)
        if key not in self._anc:
            self._anc[key] = a == b or GIT.is_ancestor(self.root, a, b)
        return self._anc[key]


def commit_items(repo, root, feature, gate, meta_commit, path, *, current):
    """Items for one gate's evidence commit. Returns (items, full sha or None)."""
    out = []
    full = repo.full(meta_commit)
    if full is None:
        return [item("FAIL", f"evidence for {gate} names commit {meta_commit!r}, which is not in the history of "
                             f"{repo.head[:12] if repo.head else 'head'} (evidence for the wrong commit)", path)], None
    if current:
        changed = [p for p in GIT.changed(root, full, repo.head) if not p.startswith(f"specs/{feature}/")]
        dirty = [p for p in (GIT.dirty(root) or []) if not p.startswith(f"specs/{feature}/")]
        if changed or dirty:
            sample = ", ".join((changed + dirty)[:3])
            out.append(item("FAIL", f"evidence for {gate} is for {full[:12]} but files changed since outside specs/{feature}/ "
                                    f"({sample}); the evidence must describe the head", path))
    return out, full




def gate_evidence_items(root, feature, g, cfg, repo, today, current, prev):
    """Items for the evidence of one passed gate (also used by `gate status --set <gate>=passed`). `prev` is
    (gate, full commit) of the previous passed gate's evidence. Returns (items, full commit or None)."""
    out = []
    path = evidence_path(root, feature, g)
    prel = path.relative_to(root).as_posix()
    if not path.is_file():
        return [item("FAIL", f"gate {g} is passed but {prel} does not exist: a passed gate needs independent evidence", prel)], None
    found, meta = evidence.lint_text(read(path), cfg, expect_gate=g, expect_feature=feature, path=prel, today=today)
    out.extend(found)
    if meta is None:
        return out, None
    if meta.get("verdict") not in EVIDENCE_VERDICTS:
        out.append(item("FAIL", f"gate {g} is passed but its evidence verdict is {meta.get('verdict')}", prel))
    full = None
    if repo is not None and repo.ok:
        c_items, full = commit_items(repo, root, feature, g, meta.get("commit", ""), prel, current=current)
        out.extend(c_items)
        predicate = judged(g, feature)
        if full and predicate:
            newest = repo.newest_change(predicate)
            if newest and not repo.ancestor(newest[0], full):
                out.append(item("FAIL", f"evidence for {g} predates the change: {newest[1]} changed in {newest[0][:12]}, after the "
                                        f"evidence commit {full[:12]}; the gate judges it, so its evidence must be for that commit or later", prel))
        if full and prev and not repo.ancestor(prev[1], full):
            out.append(item("FAIL", f"evidence for {g} is for {full[:12]}, which is earlier than the evidence for {prev[0]} "
                                    f"({prev[1][:12]}): evidence commits never go backwards", prel))
    if not any(i["tag"] == "FAIL" for i in out):
        out.append(item("OK", f"gate {g} passed with {meta.get('role')} evidence ({meta.get('model')}, verdict {meta.get('verdict')})", prel))
    return out, full


# ------------------------------------------------------------------ settings that can weaken a gate

TARGET_CANDIDATES = ("origin/develop", "develop", "origin/main", "main")
PROJECT_CONFIG = f"{config.PROJECT_DIR}/{config.FILE_NAME}"


def base_revision(root, against=None):
    """(base sha or None, problem or None): the revision that thresholds and routing are read from. `against` names it;
    otherwise it is the merge-base of HEAD with the target branch (the first of TARGET_CANDIDATES that exists), which is
    HEAD itself when HEAD is on the target, so an uncommitted edit is still compared with what was committed."""
    if against:
        sha = GIT.rev(root, against)
        return (sha, None) if sha else (None, f"cannot resolve the base revision {against!r}")
    for ref in TARGET_CANDIDATES:
        sha = GIT.merge_base(root, ref)
        if sha:
            return sha, None
    return None, None


def settings_from_base(root, cfg, base, from_project):
    """(cfg whose `gates` block is the base revision's, items). A change to the routing inside the range is a WARN naming the
    commit; the check itself uses the base revision's routing, so the change under review cannot weaken it. A configuration
    named by `--config` or the environment is the caller's explicit choice and is used as given."""
    if base is None or not from_project:
        return cfg, []
    defaults = config.default_config()["gates"]
    text, items, base_gates = GIT.show(root, base, PROJECT_CONFIG), [], defaults
    if text is not None:
        try:
            doc = core.loads_strict(text)
            found = doc.get("gates") if isinstance(doc, dict) else None
            base_gates = found if isinstance(found, dict) else defaults
        except ValueError:
            items.append(item("WARN", f"{PROJECT_CONFIG} at the base revision {base[:12]} is not valid JSON; the default routing is used", PROJECT_CONFIG))
    now = cfg.get("gates", {})
    if now == base_gates:
        return cfg, items
    dirty = GIT.dirty(root) or []
    where = "an uncommitted change" if PROJECT_CONFIG in dirty else f"commit {(GIT.last_commit(root, PROJECT_CONFIG) or 'unknown')[:12]}"
    items.append(item("WARN", f"the gates settings (critical gates, critical units, adversary models) differ from the base revision "
                              f"{base[:12]}, changed by {where}: this check routes by the base revision's settings", PROJECT_CONFIG))
    effective = dict(cfg)
    effective["gates"] = base_gates
    return effective, items


# ------------------------------------------------------------------ gate check

def check_feature(root, feature, cfg, *, head=None, today=None, release=False, strict_commits=False, commit_check=True,
                  readiness_path=None, catalog=None, lag=0, against=None, project_config=True):
    """The items of `gate check`: FAIL for every violated rule, OK lines for what holds. The thresholds and the gates
    routing are read from the base revision of the checked range (`against`, or the merge-base with the target branch)."""
    root = Path(root)
    today = today or today_iso()
    status, items = load_status(root, feature)
    if status is None:
        return items
    base, problem = base_revision(root, against)
    if problem:
        items.append(item("FAIL", problem))
    cfg, base_items = settings_from_base(root, cfg, base, project_config)
    items.extend(base_items)
    rel = status.path.relative_to(root).as_posix()
    gates = {g: status.state(g) for g in GATES}
    first_open = None
    for g in GATES:
        s = gates[g]
        if s == "failed":
            items.append(item("FAIL", f"gate {g} is failed", rel))
        if s in COMPLETE and first_open:
            items.append(item("FAIL", f"gate {g} is {s} but the earlier gate {first_open} is {gates[first_open]}: gates pass in order", rel))
        if s not in COMPLETE and first_open is None:
            first_open = g
    expected = status.expected_phase()
    if status.meta.get("phase") != expected:
        items.append(item("FAIL", f"phase is {status.meta.get('phase')!r} but the gates put it at {expected!r}", rel))
    items.extend(waiver_problems(status, cfg, today))
    from batuta_lib import thresholds as th   # imported here: thresholds imports this module
    items.extend(th.check_range(root, cfg, base))
    if status.meta.get("blocked") and not str(status.meta.get("blocked_reason", "")).strip():
        items.append(item("WARN", "the unit is blocked and states no blocked_reason", rel))

    passed = [g for g in GATES if gates[g] == "passed"]
    repo = Repo(root, head) if commit_check and (passed or release) else None
    if passed and commit_check and not repo.ok:
        items.append(item("FAIL", "cannot verify the evidence commits: the project is not a git repository with a commit "
                                  "(use --no-commit-check to skip the check, reported as a WARN)"))
    elif passed and not commit_check:
        items.append(item("WARN", "evidence commits were not verified (--no-commit-check)"))
    prev = None
    for g in passed:
        # the release evidence describes the head being promoted; once L10 is done the head has moved on legitimately
        current = strict_commits or (g == "L9-promote" and gates["L10-lessons"] not in COMPLETE)
        found, full = gate_evidence_items(root, feature, g, cfg, repo, today, current, prev)
        items.extend(found)
        if full:
            prev = (g, full)

    if gates["L5-freeze"] == "passed":
        problems = approval_problems(root, feature, cfg)
        items.extend(item("FAIL", p, f"specs/{feature}/approvals") for p in problems)
        if not problems:
            items.append(item("OK", "L5-freeze approval is valid: every hashed file still has its hash", f"specs/{feature}/approvals"))
    release = release or gates["L9-promote"] == "passed"
    from batuta_lib import readiness as rd   # imported here: readiness imports this module
    found = rd.find_readiness(root, readiness_path)
    if found is None:
        if gates["L6-skeleton"] in COMPLETE:
            items.append(item("FAIL", "L6-skeleton is passed but no readiness document exists (data/derived/readiness.json "
                                      "or docs/design/readiness.json)"))
        else:
            items.append(item("SKIP", "no readiness document yet (before L6-skeleton)"))
    elif release:
        items.extend(rd.check_readiness(root, found, catalog=catalog, head=head, lag=lag, release=True, tests=False,
                                        age=gates["L10-lessons"] not in COMPLETE))
    if release:
        cat = rd._abs(root, catalog or rd.CATALOG_PATH)
        rows = rd.catalog_rows(root, cat)[0] if cat.is_file() else None
        if rows is not None:
            items.extend(rd.check_tests(root, rows, None, RECORD_PATH, head=head))
    return items
