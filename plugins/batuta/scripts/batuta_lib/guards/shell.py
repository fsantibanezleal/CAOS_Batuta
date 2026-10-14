"""A small, tolerant shell reader for the guards: segments, words, redirects, write and read targets.

It reads bash, PowerShell and cmd spellings well enough to answer two questions about a command line: which paths
does it write, and which paths does it read. Backslashes are literal (Windows paths); quotes group words; the
operators `; & | && ||`, newlines and parentheses split segments; `>`, `>>`, `>|`, `&>`, `N>` and `<` are redirects.
PowerShell assignment prefixes (`$x = ...`, `[type]$x = ...`), block braces and shell keywords (`then`, `do`) are
skipped so the command is found. Nested commands (`bash -c`, `cmd /c`, `pwsh -c`, `wsl`, `xargs`, `eval`, `iex`,
`$(...)`, backticks, PowerShell encoded commands) are flattened by `all_segments`. Commands that take their operands
from a pipe (`xargs`, a bare `Remove-Item`) and `find ... -delete|-exec` are resolved from the rest of the command.
A guard decides on the paths; it never executes anything.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

from . import text as textlib

WRAPPERS = {"sudo", "env", "command", "nohup", "time", "exec", "call", "start", "builtin", "nice", "doas", "stdbuf"}
KEYWORDS = {"then", "do", "else", "elif", "if", "while", "until", "!", "{", "}"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish", "cmd", "powershell", "pwsh", "eval", "iex", "invoke-expression",
          "xargs", "su", "wsl", "script"}
CD = {"cd", "pushd", "chdir", "set-location", "sl"}
WRITE_ANY = {"rm", "rmdir", "del", "erase", "rd", "mv", "move", "ren", "rename", "truncate", "tee", "shred", "unlink",
             "patch", "ed", "ex", "remove-item", "move-item", "rename-item", "set-content", "add-content",
             "clear-content", "out-file", "new-item", "set-item", "mkdir", "md", "touch", "ni", "ri", "mi", "rni",
             "vi", "vim", "nvim", "nano", "emacs", "notepad", "code", "gedit", "subl", "attrib", "icacls", "chmod",
             "chown", "set-itemproperty", "export-csv", "export-clixml", "sc", "ac", "tee-object", "clc", "si",
             "ln", "mklink", "mkfifo", "mknod"}
WRITE_DEST = {"cp", "copy", "install", "copy-item", "xcopy", "robocopy", "rsync", "scp", "cpi"}
MOVERS = {"mv", "move", "move-item", "mi"}
GIT_WRITES = {"checkout", "restore", "rm", "mv", "stash", "clean", "reset", "revert", "switch", "merge",
              "cherry-pick", "pull", "rebase"}
GIT_PATCHERS = {"apply", "am"}
INPLACE = {"sed", "perl", "ruby", "gsed"}
READERS = {"cat", "type", "head", "tail", "less", "more", "most", "bat", "nl", "tac", "rev", "grep", "egrep", "fgrep",
           "rg", "ag", "ack", "awk", "gawk", "sed", "gsed", "cut", "sort", "uniq", "strings", "xxd", "od", "hexdump",
           "base64", "openssl", "gpg", "source", ".", "curl", "wget", "get-content", "gc", "select-string", "sls",
           "import-csv", "import-clixml", "diff", "cmp", "comm", "paste", "fold", "jq", "yq", "tar", "zip", "7z", "file",
           "stat", "certutil", "findstr", "find", "fc", "get-filehash"}
READ_COPY = {"cp", "copy", "copy-item", "scp", "rsync", "mv", "move", "move-item", "cpi", "xcopy", "robocopy"}
PIPE_FED = {"remove-item", "ri", "rm", "del", "erase", "rd", "rmdir"}
FIND_EXEC = ("-exec", "-execdir", "-ok", "-okdir")
LINK_TYPES = re.compile(r"symboliclink|junction|hardlink", re.IGNORECASE)
DOTNET_LINK = re.compile(r"Create(?:Symbolic|Hard)Link\w*\s*\(([^)]*)\)|CreateJunction\w*\s*\(([^)]*)\)", re.IGNORECASE)
QUOTED = re.compile(r"['\"]([^'\"]+)['\"]")
EXCLUDE_FLAGS = {"--exclude", "--exclude-dir", "--include", "--glob", "-g", "--exclude-from", "--ignore-file"}


@dataclass
class Segment:
    words: list = field(default_factory=list)
    outs: list = field(default_factory=list)
    ins: list = field(default_factory=list)
    raw: str = ""
    piped: bool = False     # the segment follows a single `|`: it may take its operands from the previous command


_VAR = r"(?:\[[\w.\[\]]+\])*\$(?:\w+|\{[^}]+\}|env:\w+)"
_BARE_VAR = re.compile(_VAR)
_ASSIGN_OP = re.compile(r"[+\-*/%]?=")
_ASSIGN_WORD = re.compile(_VAR + r"[+\-*/%]?=(.*)", re.DOTALL)


def _clean_words(words: list) -> list:
    """Drop PowerShell assignment prefixes, block braces and keywords from the front of a segment."""
    braced = False
    while words:
        w = words[0]
        if w in ("{", "}", "!"):
            braced = braced or w == "{"
            del words[0]
        elif w.startswith("{") and len(w) > 1:
            braced = True
            words[0] = w[1:]
        elif _BARE_VAR.fullmatch(w) and len(words) > 1 and _ASSIGN_OP.fullmatch(words[1]):
            del words[0:2]
        elif _ASSIGN_WORD.fullmatch(w):
            rest = _ASSIGN_WORD.fullmatch(w).group(1)
            if rest:
                words[0] = rest
            else:
                del words[0]
        else:
            break
    if braced:
        while words and words[-1] in ("}", ""):
            words.pop()
        if words and words[-1].endswith("}") and len(words[-1]) > 1:
            words[-1] = words[-1][:-1]
    return words


def segments(command: str) -> list[Segment]:
    """Split `command` into segments of words with their redirect targets."""
    out: list[Segment] = []
    words: list[str] = []
    cur: list[str] = []
    state = {"had_quote": False}
    seg = Segment()
    pending = None  # "out" or "in": the next word is a redirect target
    quote = None
    start = 0
    i, n = 0, len(command)

    def take_word():
        nonlocal pending
        if not cur and not state["had_quote"]:
            return
        value = "".join(cur)
        cur.clear()
        state["had_quote"] = False
        if pending == "out":
            seg.outs.append(value)
        elif pending == "in":
            seg.ins.append(value)
        else:
            words.append(value)
        pending = None

    def end_segment(at, piped=False):
        nonlocal seg, words, start, pending
        take_word()
        pending = None
        seg.words = _clean_words(words)
        seg.raw = command[start:at]
        if seg.words or seg.outs or seg.ins:
            out.append(seg)
        seg, words, start = Segment(piped=piped), [], at + 1

    while i < n:
        ch = command[i]
        if quote:
            if ch == quote:
                quote = None
            elif quote == '"' and ch == "\\" and i + 1 < n and command[i + 1] == '"':
                cur.append('"')
                i += 1
            else:
                cur.append(ch)
            i += 1
            continue
        if ch in "'\"":
            quote = ch
            state["had_quote"] = True
        elif ch == "\\" and i + 1 < n and command[i + 1] == " " and not (cur and cur[-1] == ":") \
                and command[i + 2:i + 3] not in ("", "|", ";", "&", ">", "<", ")", " ", "\t", "\r", "\n"):
            cur.append(" ")          # an escaped space (bash); `C:\ |` is a drive root followed by a pipe
            i += 1
        elif ch.isspace() and ch not in "\r\n":
            take_word()
        elif ch in "\r\n;()":
            end_segment(i)
        elif ch == "|":
            single = not (i + 1 < n and command[i + 1] == "|")
            if not single:
                i += 1
            end_segment(i, piped=single)
        elif ch == "&":
            if i + 1 < n and command[i + 1] == ">":  # &> and &>> redirect both streams
                take_word()
                i += 1
                if i + 1 < n and command[i + 1] == ">":
                    i += 1
                pending = "out"
            else:
                if i + 1 < n and command[i + 1] == "&":
                    i += 1
                end_segment(i)
        elif ch == ">":
            if cur and "".join(cur).isdigit() and not state["had_quote"]:
                cur.clear()  # a file descriptor such as the 2 of 2>
            else:
                take_word()
            while i + 1 < n and command[i + 1] in ">|":
                i += 1
            if i + 1 < n and command[i + 1] == "&":  # >&2: a descriptor, not a file
                j = i + 2
                while j < n and (command[j].isdigit() or command[j] == "-"):
                    j += 1
                i = j - 1
                pending = None
            else:
                pending = "out"
        elif ch == "<":
            take_word()
            if i + 1 < n and command[i + 1] == "<":
                i += 1
                pending = None
            else:
                pending = "in"
        else:
            cur.append(ch)
        i += 1
    end_segment(n)
    return out


def command_index(seg: Segment) -> int:
    """Index in `seg.words` of the command proper (after assignments, keywords and wrappers); len(words) when none."""
    i = 0
    words = seg.words
    while i < len(words):
        word = words[i]
        if re.match(r"^[A-Za-z_]\w*=", word) or word.lower() in KEYWORDS:
            i += 1
        elif _base(word) in WRAPPERS:
            i += 1
            while i < len(words) and (words[i].startswith("-") or re.match(r"^[A-Za-z_]\w*=", words[i])):
                i += 1
        else:
            return i
    return len(words)


def _base(word: str) -> str:
    name = re.split(r"[\\/]", word.strip())[-1].lower()
    return re.sub(r"\.(exe|cmd|bat|com|ps1)$", "", name)


def command_name(seg: Segment) -> str:
    i = command_index(seg)
    return _base(seg.words[i]) if i < len(seg.words) else ""


def args_of(seg: Segment) -> list[str]:
    return seg.words[command_index(seg) + 1:]


def _positional(args: list[str]) -> list[str]:
    """Arguments that are not flags (`-x`, `--long`, `/q`)."""
    return [a for a in args if a and not a.startswith("-") and not re.fullmatch(r"/[A-Za-z?]{1,2}", a)]


def _git_sub(args: list[str]) -> tuple[str, list[str]]:
    i = 0
    while i < len(args):
        if args[i] in ("-C", "-c", "--git-dir", "--work-tree", "--namespace"):
            i += 2
        elif args[i].startswith("-"):
            i += 1
        else:
            return args[i].lower(), args[i + 1:]
    return "", []


def _basename(token: str) -> str:
    return re.split(r"[\\/]", token.rstrip("\\/"))[-1]


def _join_dest(dest: str, source: str) -> str:
    return dest.rstrip("\\/") + "/" + _basename(source)


def _is_writer(inner: Segment) -> bool:
    """Does this (inner) command write, delete or move files?"""
    name = command_name(inner)
    args = args_of(inner)
    if name in WRITE_ANY or name in WRITE_DEST:
        return True
    if name in INPLACE:
        return any(re.fullmatch(r"-[A-Za-z]*i[A-Za-z0-9.]*", a) or a.startswith("--in-place") for a in args)
    if name == "git":
        sub, _ = _git_sub(args)
        return sub in GIT_WRITES or sub in GIT_PATCHERS
    return False


def _find_parts(args: list[str]) -> tuple[list[str], bool, bool]:
    """(path operands, deletes, runs a writer) of a `find` command line."""
    operands: list[str] = []
    for a in args:
        if a.startswith("-") or a in ("(", ")", "!"):
            break
        operands.append(a)
    deletes = "-delete" in args
    runs_writer = False
    for i, a in enumerate(args):
        if a in FIND_EXEC and i + 1 < len(args):
            inner = Segment(words=args[i + 1:])
            runs_writer = runs_writer or _is_writer(inner)
    return operands, deletes, runs_writer


def _dest_tag(name: str) -> str:
    """A folder that receives copied files is not replaced, except by tools that mirror unknown contents."""
    return "" if name in ("rsync", "robocopy", "xcopy") else "dest"


def write_targets(seg: Segment) -> list[str]:
    """Paths a segment writes, creates, deletes, moves or overwrites (operands given on its own line)."""
    return [t for t, _ in write_items(seg)]


def write_items(seg: Segment) -> list[tuple[str, str]]:
    """(target, tag) pairs; the tag is `dest` for the destination operand of a move or copy (a folder that receives
    files is not itself deleted or replaced)."""
    items: list[tuple[str, str]] = [(t, "") for t in seg.outs]
    targets: list[str] = []
    name, args = command_name(seg), args_of(seg)
    if not name:
        return items
    pos = _positional(args)
    if name in WRITE_ANY and name in MOVERS and len(pos) >= 2:
        items += [(t, "") for t in pos[:-1]]
        items.append((pos[-1], "dest"))
        items += [(_join_dest(pos[-1], s), "") for s in pos[:-1]]
    elif name in WRITE_ANY:
        targets += pos
    elif name in INPLACE:
        if any(re.fullmatch(r"-[A-Za-z]*i[A-Za-z0-9.]*", a) or a.startswith("--in-place") for a in args):
            targets += pos
    elif name in WRITE_DEST:
        dests = [v for f, v in zip(args, args[1:]) if f.lower() in ("-destination", "-dest")]
        if dests:
            sources = [p for p in pos if p not in dests]
            for d in dests:
                items.append((d, _dest_tag(name)))
                items += [(_join_dest(d, s), "") for s in sources]
        elif pos:
            items.append((pos[-1], _dest_tag(name)))
            items += [(_join_dest(pos[-1], s), "") for s in pos[:-1]]
    elif name == "git":
        sub, rest = _git_sub(args)
        if sub in GIT_WRITES:
            targets += _positional(rest)
        elif sub in GIT_PATCHERS:
            targets.append("*")      # a patch can change any file: treated as a write to every protected path
    elif name == "dd":
        targets += [a[3:] for a in args if a.startswith("of=")]
    elif name in ("curl", "wget"):
        for flag, value in zip(args, args[1:]):
            if flag in ("-o", "--output", "-O", "--output-document"):
                targets.append(value)
        targets += [a.split("=", 1)[1] for a in args if a.startswith(("--output=", "--output-document="))]
    elif name == "find":
        operands, deletes, runs_writer = _find_parts(args)
        if deletes or runs_writer:
            targets += operands or ["."]
    return items + [(t, "") for t in targets]


def read_targets(seg: Segment) -> list[str]:
    """Paths a segment reads (known readers and copies), including `<` redirects."""
    targets = list(seg.ins)
    name, args = command_name(seg), args_of(seg)
    if name in READ_COPY:
        pos = _positional(args)
        targets += pos[:-1] if len(pos) > 1 else pos
    elif name == "git":
        sub, rest = _git_sub(args)
        if sub in ("show", "cat-file", "blame"):
            for a in _positional(rest):
                if ":" in a and not re.match(r"^[A-Za-z]:[\\/]", a):
                    targets.append(a.rsplit(":", 1)[1])
    elif name in READERS:
        skip_next = False
        for arg in args:
            if skip_next:
                skip_next = False
                continue
            if arg in EXCLUDE_FLAGS:       # a pattern that is left out of a search is not a file that is read
                skip_next = True
                continue
            if arg.startswith("-"):
                if "=" in arg and arg.split("=", 1)[0] not in EXCLUDE_FLAGS:
                    targets.append(arg.split("=", 1)[1])
                continue
            targets.append(arg.rsplit("@", 1)[1] if (name in ("curl", "wget") and "@" in arg) else arg)
    return [t for t in targets if t]


def _flag_value_skip(name: str, args: list[str]) -> int:
    """Index of the first word of the command a launcher runs (after its own flags and their values)."""
    i = 0
    takes_value = {"-i", "-n", "-p", "-l", "-s", "-e", "-d", "-a", "-p"}
    while i < len(args) and args[i].startswith("-"):
        i += 2 if (name == "xargs" and args[i] in takes_value) else 1
    return i


def _shell_payloads(seg: Segment) -> list[str]:
    """The command strings a launcher segment (bash -c, cmd /c, pwsh -c, wsl, xargs, eval, iex) runs."""
    name, args = command_name(seg), args_of(seg)
    out: list[str] = []
    if name in ("cmd",):
        for i, a in enumerate(args):
            if a.lower() in ("/c", "/k", "/r"):
                out.append(" ".join(args[i + 1:]))
                break
            if a.lower().startswith(("/c", "/k")) and len(a) > 2:
                out.append(" ".join([a[2:], *args[i + 1:]]).strip())
                break
    elif name in ("powershell", "pwsh"):
        for i, a in enumerate(args):
            la = a.lower()
            if la.startswith("-c") and "command".startswith(la[1:]) or la == "-cmd":
                out.append(" ".join(args[i + 1:]))
                break
        else:
            for i, a in enumerate(args):
                if not a.startswith("-") and a.lower() not in ("bypass", "unrestricted", "remotesigned", "hidden", "normal",
                                                               "minimized", "maximized", "allsigned", "restricted"):
                    out.append(" ".join(args[i:]))
                    break
    elif name in ("bash", "sh", "zsh", "dash", "ksh", "fish", "su"):
        for i, a in enumerate(args):
            if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", a):
                out.append(" ".join(args[i + 1:]))
                break
    elif name == "wsl":
        rest = [a for a in args if not a.startswith("-")]
        if rest:
            out.append(" ".join(rest))
    elif name == "xargs":
        i = _flag_value_skip(name, args)
        if i < len(args):
            out.append(" ".join(args[i:]))
    elif name in ("eval", "iex", "invoke-expression"):
        out.append(" ".join(args))
    return [p for p in out if p.strip()]


def all_segments(command: str, depth: int = 3) -> list[Segment]:
    """Segments of `command` plus those of every nested command (shell -c strings, eval, subshells, encoded payloads)."""
    found: list[Segment] = []
    seen: set[str] = set()

    def visit(text: str, left: int) -> None:
        if text in seen:
            return
        seen.add(text)
        segs = segments(text)
        found.extend(segs)
        if left <= 0:
            return
        for decoded in textlib.decoded_commands(text):
            if decoded:
                visit(textlib.normalize(decoded), left - 1)
        for body in textlib.nested_texts(text, 1):
            visit(body, left - 1)
        for seg in segs:
            if command_name(seg) in SHELLS:
                for payload in _shell_payloads(seg):
                    visit(payload, left - 1)
                for word in args_of(seg):
                    if not word.startswith("-") and re.search(r"\s|[;&|<>]", word):
                        visit(word, left - 1)

    visit(command, depth)
    return found


def _cd_target(seg: Segment) -> str | None:
    pos = _positional(args_of(seg))
    return pos[0] if pos else None


def _join(prefix: str, target: str) -> str:
    t = target.replace("\\", "/")
    if not prefix or t.startswith("/") or re.match(r"^[A-Za-z]:/", t) or t.startswith(("~", "$")):
        return t
    return posixpath.normpath(prefix + "/" + t)


def _producer_operands(segs: list[Segment], skip: Segment) -> list[str]:
    """Operands of the other commands of a pipeline: what a pipe-fed `xargs rm` or `Remove-Item` will receive."""
    out: list[str] = []
    for other in segs:
        if other is skip or command_name(other) in CD:
            continue
        out += _positional(args_of(other))
    return out


CONTENT_PRODUCERS = {"cat", "type", "get-content", "gc", "grep", "egrep", "fgrep", "rg", "awk", "sed", "sort", "head", "tail",
                     "select-string", "sls", "xargs", "tee", "uniq"}


def _fed_targets(segs: list[Segment], skip: Segment) -> list[str]:
    """What a pipe-fed writer will receive: the operands of the other commands, plus `*` (every protected path) when
    nothing is named or when a producer prints the content of a file (the names in it are unknown)."""
    fed = _producer_operands(segs, skip)
    unknown = any(command_name(o) in CONTENT_PRODUCERS for o in segs if o is not skip)
    return fed + (["*"] if (not fed or unknown) else [])


def is_link_command(seg: Segment) -> bool:
    """ln, mklink, or New-Item with a link item type: every operand names a path that gets linked."""
    name = command_name(seg)
    if name in ("ln", "mklink"):
        return True
    return name in ("new-item", "ni") and any(LINK_TYPES.search(a) for a in args_of(seg))


def link_operands(seg: Segment) -> list[str]:
    return _positional(args_of(seg)) if is_link_command(seg) else []


def dotnet_link_operands(text: str) -> list[str]:
    """The quoted path arguments of `[IO.File]::CreateSymbolicLink(...)`-style .NET calls."""
    out: list[str] = []
    for m in DOTNET_LINK.finditer(text):
        out += QUOTED.findall(m.group(1) or m.group(2) or "")
    return out


def link_targets_of(command: str) -> list[str]:
    """Every path operand of every link creation in the command (nested commands included)."""
    out: list[str] = []
    texts = [command] + textlib.nested_texts(command)
    for seg in all_segments(command):
        out += link_operands(seg)
    for text in texts:
        out += dotnet_link_operands(text)
    return out


def write_pairs(command: str) -> list[tuple[str, str]]:
    """(command name, target) over all segments, each target also spelled relative to the folder a `cd` moved into.
    A pipe-fed writer takes the operands of the rest of the command, or `*` (every protected path) when it has none."""
    segs = all_segments(command)
    out: list[tuple[str, str]] = []
    prefix = ""
    for seg in segs:
        name = command_name(seg)
        if name in CD:
            target = _cd_target(seg)
            if target:
                prefix = _join(prefix, target) if target != ".." else posixpath.normpath((prefix or ".") + "/..")
            continue
        picked = [(name if tag == "" else name + "-dest", t) for t, tag in write_items(seg)]
        if is_link_command(seg):
            picked = [("mklink", t) for t in link_operands(seg)] + picked
        if name == "xargs":
            payload = _shell_payloads(seg)
            inner_words = args_of(seg)[_flag_value_skip("xargs", args_of(seg)):]
            inner = Segment(words=inner_words)
            if payload and _is_writer(inner):
                inner_name = command_name(inner)
                picked += [(inner_name, t) for t in _fed_targets(segs, seg)]
        elif name in PIPE_FED and seg.piped and not _positional(args_of(seg)):
            picked += [(name, t) for t in _fed_targets(segs, seg)]
        for nm, t in picked:
            out.append((nm, t))
            joined = _join(prefix, t) if prefix else t
            if joined != t:
                out.append((nm, joined))
    for text in [command] + textlib.nested_texts(command):
        for token in dotnet_link_operands(text):
            out.append(("mklink", token))
    return out


def read_pairs(command: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    prefix = ""
    for seg in all_segments(command):
        name = command_name(seg)
        if name in CD:
            target = _cd_target(seg)
            if target:
                prefix = _join(prefix, target) if target != ".." else posixpath.normpath((prefix or ".") + "/..")
            continue
        for t in read_targets(seg):
            out.append((name, t))
            joined = _join(prefix, t) if prefix else t
            if joined != t:
                out.append((name, joined))
    return out


def write_targets_of(command: str) -> list[str]:
    return [t for _, t in write_pairs(command)]


def read_targets_of(command: str) -> list[str]:
    return [t for _, t in read_pairs(command)]
