"""A small, tolerant shell reader for the guards: segments, words, redirects, write and read targets.

It reads bash, PowerShell and cmd spellings well enough to answer two questions about a command line: which paths
does it write, and which paths does it read. Backslashes are literal (Windows paths); quotes group words; the
operators `; & | && ||`, newlines and parentheses split segments; `>`, `>>`, `>|`, `&>`, `N>` and `<` are redirects.
Nested commands (`bash -c '...'`, `pwsh -Command "..."`, `eval`, `iex`, `$(...)`, backticks, PowerShell encoded
commands) are flattened by `all_segments`. A guard decides on the paths; it never executes anything.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass, field

from . import text as textlib

WRAPPERS = {"sudo", "env", "command", "nohup", "time", "exec", "call", "start", "builtin", "nice", "doas", "stdbuf"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "fish", "cmd", "powershell", "pwsh", "eval", "iex", "invoke-expression",
          "xargs", "su", "wsl", "script"}
CD = {"cd", "pushd", "chdir", "set-location", "sl"}
WRITE_ANY = {"rm", "rmdir", "del", "erase", "rd", "mv", "move", "ren", "rename", "truncate", "tee", "shred", "unlink",
             "patch", "ed", "ex", "remove-item", "move-item", "rename-item", "set-content", "add-content",
             "clear-content", "out-file", "new-item", "set-item", "mkdir", "md", "touch", "ni", "ri", "mi", "rni",
             "vi", "vim", "nvim", "nano", "emacs", "notepad", "code", "gedit", "subl", "attrib", "icacls", "chmod",
             "chown", "set-itemproperty", "export-csv", "export-clixml"}
WRITE_DEST = {"cp", "copy", "install", "ln", "copy-item", "xcopy", "robocopy", "rsync", "scp", "cpi"}
GIT_WRITES = {"checkout", "restore", "rm", "mv", "apply", "stash", "clean", "reset", "revert", "am", "switch", "merge",
              "cherry-pick", "pull", "rebase"}
INPLACE = {"sed", "perl", "ruby", "gsed"}
READERS = {"cat", "type", "head", "tail", "less", "more", "most", "bat", "nl", "tac", "rev", "grep", "egrep", "fgrep",
           "rg", "ag", "ack", "awk", "gawk", "sed", "gsed", "cut", "sort", "uniq", "strings", "xxd", "od", "hexdump",
           "base64", "openssl", "gpg", "source", ".", "curl", "wget", "get-content", "gc", "select-string", "sls",
           "import-csv", "import-clixml", "diff", "cmp", "comm", "paste", "fold", "jq", "yq", "tar", "zip", "7z", "file",
           "stat", "certutil", "findstr", "find", "fc", "get-filehash"}
READ_COPY = {"cp", "copy", "copy-item", "scp", "rsync", "mv", "move", "move-item", "cpi", "xcopy", "robocopy"}


@dataclass
class Segment:
    words: list = field(default_factory=list)
    outs: list = field(default_factory=list)
    ins: list = field(default_factory=list)
    raw: str = ""


def _flush(word: list, words: list, state: dict) -> None:
    if word or state["had_quote"]:
        value = "".join(word)
        words.append(value)
    word.clear()
    state["had_quote"] = False


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

    def end_segment(at):
        nonlocal seg, words, start, pending
        take_word()
        pending = None
        seg.words = words
        seg.raw = command[start:at]
        if seg.words or seg.outs or seg.ins:
            out.append(seg)
        seg, words, start = Segment(), [], at + 1

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
        elif ch == "\\" and i + 1 < n and command[i + 1] == " ":
            cur.append(" ")
            i += 1
        elif ch.isspace() and ch not in "\r\n":
            take_word()
        elif ch in "\r\n;()":
            end_segment(i)
        elif ch == "|":
            if i + 1 < n and command[i + 1] == "|":
                i += 1
            end_segment(i)
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
    """Index in `seg.words` of the command proper (after assignments and wrappers); len(words) when none."""
    i = 0
    words = seg.words
    while i < len(words):
        word = words[i]
        if re.match(r"^[A-Za-z_]\w*=", word):
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


def write_targets(seg: Segment) -> list[str]:
    """Paths a segment writes, creates, deletes, moves or overwrites."""
    targets = list(seg.outs)
    name, args = command_name(seg), args_of(seg)
    if not name:
        return targets
    if name in WRITE_ANY:
        targets += _positional(args)
    elif name in INPLACE:
        if any(re.fullmatch(r"-[A-Za-z]*i[A-Za-z0-9.]*", a) or a.startswith("--in-place") for a in args):
            targets += _positional(args)
    elif name in WRITE_DEST:
        pos = _positional(args)
        for flag, value in zip(args, args[1:]):
            if flag.lower() in ("-destination", "-dest", "-target", "-t"):
                pos.append(value)
        if pos:
            targets.append(pos[-1])
        targets += [v for f, v in zip(args, args[1:]) if f.lower() in ("-destination", "-dest")]
    elif name == "git":
        sub, rest = _git_sub(args)
        if sub in GIT_WRITES:
            targets += _positional(rest)
    elif name == "dd":
        targets += [a[3:] for a in args if a.startswith("of=")]
    elif name in ("curl", "wget"):
        for flag, value in zip(args, args[1:]):
            if flag in ("-o", "--output", "-O", "--output-document"):
                targets.append(value)
        targets += [a.split("=", 1)[1] for a in args if a.startswith(("--output=", "--output-document="))]
    return targets


def read_targets(seg: Segment) -> list[str]:
    """Paths a segment reads (known readers and copies), including `<` redirects."""
    targets = list(seg.ins)
    name, args = command_name(seg), args_of(seg)
    if name in READ_COPY:
        pos = _positional(args)
        targets += pos[:-1] if len(pos) > 1 else pos
    elif name in READERS:
        for arg in args:
            if arg.startswith("-"):
                if "=" in arg:
                    targets.append(arg.split("=", 1)[1])
                continue
            targets.append(arg.rsplit("@", 1)[1] if (name in ("curl", "wget") and "@" in arg) else arg)
    return [t for t in targets if t]


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


def _pairs(command: str, pick) -> list[tuple[str, str]]:
    """(command name, target) over all segments, each target also spelled relative to the folder a `cd` moved into."""
    out: list[tuple[str, str]] = []
    prefix = ""
    for seg in all_segments(command):
        name = command_name(seg)
        if name in CD:
            target = _cd_target(seg)
            if target:
                prefix = _join(prefix, target) if target != ".." else posixpath.normpath((prefix or ".") + "/..")
            continue
        for t in pick(seg):
            out.append((name, t))
            joined = _join(prefix, t) if prefix else t
            if joined != t:
                out.append((name, joined))
    return out


def write_pairs(command: str) -> list[tuple[str, str]]:
    return _pairs(command, write_targets)


def read_pairs(command: str) -> list[tuple[str, str]]:
    return _pairs(command, read_targets)


def write_targets_of(command: str) -> list[str]:
    return [t for _, t in write_pairs(command)]


def read_targets_of(command: str) -> list[str]:
    return [t for _, t in read_pairs(command)]
