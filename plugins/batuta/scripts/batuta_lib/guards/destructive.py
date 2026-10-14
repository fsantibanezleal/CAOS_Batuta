"""Guard `destructive`: packs of commands that destroy work or data, each with an explain line.

Packs: `force-push-protected` (git push --force or +refspec to a protected branch or with no branch named, and
deleting a protected branch remotely: `:main`, `--delete main`), `hard-reset` (git reset --hard), `git-clean`
(git clean -f without a dry run), `rm-roots` (recursive delete of a filesystem root, a home folder, a drive or the
current folder contents, also fed through a pipe, `xargs rm -r` or `find ... -delete`), `disk-format` (mkfs, format,
Format-Volume, diskpart, dd to a device, wipefs, fdisk). Git accepts any unambiguous prefix of a long option, so
`--har` is `--hard`. Configuration: `guards.protected_branches` adds to the protected list (default main, master,
develop, release/*); `guards.destructive_disable` lists packs to switch off.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path

from . import allow, command_of, deny, guard_config, project_root, section, shell, string_list
from . import text as textlib

NAME = "destructive"
DEFAULT_PROTECTED = ["main", "master", "develop", "release/*"]
EXPLAIN_BY_PACK = {
    "force-push-protected": "force-pushing or deleting a protected branch (or any force push with no branch named) "
                            "rewrites shared history; push a task branch and merge through a pull request",
    "hard-reset": "git reset --hard throws away uncommitted work and local commits for good; use git stash or a new branch",
    "git-clean": "git clean -f deletes untracked files that git cannot restore; preview with git clean -n",
    "rm-roots": "a recursive delete of a root, home or drive folder (or `*`) wipes the machine; name the exact subfolder",
    "disk-format": "disk formatting, partitioning or writing to a device destroys its data; the user runs it themselves",
}
EXPLAIN = ["Blocks destructive command packs; each hit carries an explain line:"] + \
    [f"  - {pack}: {why}" for pack, why in EXPLAIN_BY_PACK.items()] + \
    ["Protected branches default to main, master, develop, release/*; add with guards.protected_branches.",
     "Switch a pack off with guards.destructive_disable (a list of pack names)."]

ROOT_NAMES = {"", "*", ".", "..", "~", "$home", "${home}", "%userprofile%", "$env:userprofile", "$env:homepath", "$env:systemdrive",
              "/*", "~/*", "$home/*", "./*", "../*", "/bin", "/boot", "/dev", "/etc", "/home", "/lib", "/opt", "/root",
              "/sbin", "/usr", "/var", "/sys", "/proc", "/users", "/windows", "c:/users", "c:/windows",
              "c:/program files"}
DRIVE = re.compile(r"^[a-z]:(/\*?)?$")
HOME_FOLDER = re.compile(r"^(/home/[^/]+|/users/[^/]+|[a-z]:/users/[^/]+)$")
RECURSIVE_FLAG = re.compile(r"^-[A-Za-z]*[rR][A-Za-z]*$|^--recursive$|^-recurse$", re.IGNORECASE)
RECURSIVE_WIN = re.compile(r"^/s$", re.IGNORECASE)
DELETERS = {"rm", "remove-item", "ri", "rmdir", "rd", "del", "erase"}
PRODUCERS = {"ls", "dir", "gci", "get-childitem", "find", "echo", "printf", "cat", "get-item", "gi", "tree", "fd"}
DISK_COMMANDS = {"format-volume", "clear-disk", "diskpart", "fdisk", "cfdisk", "sfdisk", "parted", "wipefs",
                 "initialize-disk", "remove-partition"}
DEVICE = re.compile(r"^(/dev/|\\\\\.\\|//\./)", re.IGNORECASE)


def settings(root: Path | None) -> tuple[list[str], set[str]]:
    section_ = section(guard_config(root), "guards") if root is not None else {}
    protected = DEFAULT_PROTECTED + string_list(section_.get("protected_branches"))
    return protected, set(string_list(section_.get("destructive_disable")))


def state(root: Path) -> str:
    protected, disabled = settings(root)
    return f"protected branches: {', '.join(protected)}; packs switched off: {', '.join(sorted(disabled)) or 'none'}"


def _is_protected(branch: str, protected: list[str]) -> bool:
    branch = branch.removeprefix("refs/heads/")
    return any(fnmatch.fnmatchcase(branch, p) for p in protected)


def _opt(arg: str, full: str, minlen: int) -> bool:
    """`arg` is the long option `full` or an abbreviation of it (git parse-options accepts unique prefixes)."""
    return arg.startswith("--") and len(arg) >= minlen and full.startswith(arg.split("=", 1)[0])


FORCE_FORMS = ("--force", "--force-with-lease", "--force-if-includes")


def _is_force_flag(arg: str) -> bool:
    if re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", arg):
        return True
    return any(_opt(arg, full, 5) for full in FORCE_FORMS)


def _is_delete_flag(arg: str) -> bool:
    return arg == "-d" or _opt(arg, "--delete", 5)


def _push_hits(args: list[str], protected: list[str]) -> bool:
    flags = [a for a in args if a.startswith("-")]
    forced = any(_is_force_flag(a) for a in flags)
    deleting = any(_is_delete_flag(a) for a in flags)
    positional = [a for a in args if not a.startswith("-")]
    refspecs = positional[1:]
    if any(a in ("--all", "--mirror") or _opt(a, "--mirror", 5) or _opt(a, "--all", 4) for a in flags) and forced:
        return True
    if forced and not refspecs:
        return True
    for ref in refspecs:
        source, colon, target = ref.lstrip("+").partition(":")
        target = target if colon else source
        is_delete = deleting or (colon and source == "")
        is_forced = forced or ref.startswith("+")
        if not (is_delete or is_forced):
            continue
        if is_delete and not colon:
            target = source
        if is_forced and target in ("HEAD", ""):
            return True
        if _is_protected(target, protected):
            return True
    return False


def _root_like(token: str) -> bool:
    t = textlib.normalize(token).replace("\\", "/").lower()
    stripped = t.rstrip("/")
    if t.startswith("/") and stripped == "":
        return True
    return stripped in ROOT_NAMES or bool(DRIVE.match(stripped)) or bool(HOME_FOLDER.match(stripped))


def _recursive(name: str, args: list[str]) -> bool:
    return any(RECURSIVE_FLAG.match(a) or RECURSIVE_WIN.match(a) for a in args) or \
        (name in ("remove-item", "ri") and any(a.lower().startswith("-r") for a in args))


def _producer_roots(segs: list, skip) -> bool:
    for other in segs:
        if other is skip or shell.command_name(other) not in PRODUCERS:
            continue
        if any(_root_like(t) for t in shell._positional(shell.args_of(other))):
            return True
    return False


def scan_text(command: str, protected: list[str] | None = None, disabled: set[str] | None = None) -> list[tuple[str, str]]:
    """(pack, explain line) for every enabled pack the command trips; empty when it is fine."""
    protected = protected if protected is not None else DEFAULT_PROTECTED
    disabled = disabled or set()
    hits: list[tuple[str, str]] = []

    def add(pack: str) -> None:
        if pack not in disabled and all(h[0] != pack for h in hits):
            hits.append((pack, EXPLAIN_BY_PACK[pack]))

    segs = shell.all_segments(textlib.normalize(command))
    for seg in segs:
        name, args = shell.command_name(seg), shell.args_of(seg)
        if name == "xargs":
            inner = shell.Segment(words=args[shell._flag_value_skip("xargs", args):], piped=True)
            if shell.command_name(inner) in DELETERS and _recursive(shell.command_name(inner), shell.args_of(inner)) \
                    and not shell._positional(shell.args_of(inner)) and _producer_roots(segs, seg):
                add("rm-roots")
        if name == "git":
            sub, rest = shell._git_sub(args)
            if sub == "push" and _push_hits(rest, protected):
                add("force-push-protected")
            elif sub == "reset" and any(_opt(a, "--hard", 4) for a in rest):
                add("hard-reset")
            elif sub == "clean":
                dry = any(a == "-n" or _opt(a, "--dry-run", 4) or re.fullmatch(r"-[a-z]*n[a-z]*", a) for a in rest)
                force = any(_opt(a, "--force", 4) or re.fullmatch(r"-[a-zA-Z]*f[a-zA-Z]*", a) for a in rest)
                if force and not dry:
                    add("git-clean")
        elif name in DELETERS:
            pos = shell._positional(args)
            if _recursive(name, args):
                if any(_root_like(t) for t in pos):
                    add("rm-roots")
                elif not pos and seg.piped and _producer_roots(segs, seg):
                    add("rm-roots")
        elif name == "find":
            operands, deletes, runs_writer = shell._find_parts(args)
            exec_rm = any(a in shell.FIND_EXEC and i + 1 < len(args) and shell.command_name(shell.Segment(words=args[i + 1:])) in DELETERS
                          for i, a in enumerate(args))
            if (deletes or exec_rm) and any(_root_like(t) for t in operands or ["."]):
                add("rm-roots")
        elif name.startswith("mkfs") and any(DEVICE.match(a) or a.lower().startswith("/dev") for a in args):
            add("disk-format")
        elif name in ("format", "format.com") and any(re.match(r"^[A-Za-z]:", a) for a in args):
            add("disk-format")
        elif name in DISK_COMMANDS:
            add("disk-format")
        elif name == "dd" and any(a.startswith("of=") and DEVICE.match(a[3:]) for a in args):
            add("disk-format")
        elif name == "shred" and any(DEVICE.match(a) for a in args):
            add("disk-format")
    return hits


def decide(payload) -> dict:
    command = command_of(payload)
    if not command:
        return allow()
    protected, disabled = settings(project_root(payload))
    hits = scan_text(command, protected, disabled)
    if not hits:
        return allow()
    return deny("BLOCKED by guard-destructive: " + " ".join(f"[{pack}] {why}." for pack, why in hits)
                + " If this is really intended, stop and give the user the exact command to run.")
