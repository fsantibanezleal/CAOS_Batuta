"""Guard `automation`: nothing a session starts may run unattended or outlive it.

The rule table: scheduled tasks, logon autostarts (Run keys, Startup folder, XDG autostart, shell startup files),
services, permanent WMI subscriptions, `.wslconfig` and `wsl.conf` writes, Linux autostarts (systemd enable and
`systemd-run` timers, linger, cron, `at`), headless `claude -p` and `--dangerously-skip-permissions`, detached or
hidden processes (also `&`, `start /b`, `Win32_Process` Create) and unbounded polling loops. A command is matched
as written, after Unicode folding, with quote, backtick and caret obfuscation removed, inside every nested command
(`bash -c`, `cmd /c`, `$(...)`, backticks) and inside decoded PowerShell `-EncodedCommand` payloads; a payload that
cannot be decoded or that runs decoded text is refused because it cannot be inspected. The write targets of the
shell command are checked against the same autostart paths as an Edit or Write path.

Every rule has an id (the inline marker of `guard scan` names it) and a message.
"""
from __future__ import annotations

import re

from . import allow, command_of, deny, file_path_of, norm_path, shell, tool_name
from . import text as textlib

NAME = "automation"
I = re.IGNORECASE

RULES = [
    ("scheduled-task", re.compile(r"(?<!Un)Register-ScheduledTask|Register-ScheduledJob|New-ScheduledTask(Trigger|Action|Settings|Principal)?\b"
                                  r"|New-JobTrigger|Set-ScheduledTask|Enable-ScheduledTask|Schedule\.Service", I),
     "creates or changes a Windows scheduled task"),
    ("scheduled-task", re.compile(r"schtasks(\.exe)?\b[^\n|;&]*[/-](create|change)\b", I),
     "creates or changes a Windows scheduled task (schtasks)"),
    ("run-key", re.compile(r"(reg(\.exe)?\s+add|New-ItemProperty|Set-ItemProperty|\bsp\b|\bnp\b|New-Item|Registry\]::SetValue)[^\n]*"
                           r"[\\/]CurrentVersion[\\/]Run|\breg(\.exe)?\s+import\b", I),
     "adds a logon autostart (Run / RunOnce registry key)"),
    ("startup-folder", re.compile(r"(Copy-Item|Move-Item|New-Item|Out-File|Set-Content|CreateShortcut|\bcp\b|\bmv\b|\bln\b)[^\n]*"
                                  r"(Start Menu[\\/]Programs[\\/]Startup|shell:startup)"
                                  r"|GetFolderPath\(\s*[\"']?(Common)?Startup", I),
     "adds a logon autostart (Startup folder)"),
    ("service", re.compile(r"New-Service\b|\bsc(\.exe)?\s+(create|config)\b|\bnssm(\.exe)?\s+(install|set)\b"
                           r"|Set-Service\b[^\n]*-StartupType\s+Automatic", I),
     "creates or reconfigures a Windows service"),
    ("wmi", re.compile(r"__EventFilter|CommandLineEventConsumer|ActiveScriptEventConsumer|__FilterToConsumerBinding", I),
     "creates a permanent WMI event subscription"),
    ("wslconfig", re.compile(r"(>>?\s*[\"']?[^\s\"'|;&]*\.wslconfig)|((Set-Content|Add-Content|Out-File|WriteAll\w+|AppendAll\w+|Copy-Item"
                             r"|Move-Item|New-Item|Tee-Object|\bac\b|\bni\b|\bsc\b|\btee\b|\bcp\b|\bmv\b)[^\n;|]*\.wslconfig)", I),
     "writes ~/.wslconfig (vmIdleTimeout=-1 keeps the WSL VM alive forever)"),
    ("wsl-conf", re.compile(r"(>>?\s*/etc/wsl\.conf)|((\btee\b|sed\s+-i|\bcp\b|\bmv\b)[^\n;|]*/etc/wsl\.conf)", I),
     "writes /etc/wsl.conf (boot commands)"),
    ("linux-autostart", re.compile(r"systemctl\s+(-\S+\s+)*(enable|add-wants|add-requires|link|preset)\b|loginctl\s+enable-linger"
                                   r"|crontab\s+(?!-l\b)\S|>>?\s*/etc/cron|systemd-run\b[^\n]*--on-\w+"
                                   r"|(?:^|[;&|(\n])\s*at(?:\.exe)?\s+(?:now|\d{1,2}:\d{2}|noon|midnight|tomorrow)\b", I),
     "installs a Linux autostart (systemd enable, linger, cron or at)"),
    ("headless-claude", re.compile(r"\bclaude(\.exe|\.cmd)?[\"']?\s+(?:[^\n|;&]*\s)?(-p|--print)\b|claude-code\b[^\n|;&]*\s(-p|--print)\b"
                                   r"|dangerously-skip-permissions|bypassPermissions", I),
     "launches a headless Claude session (spends the subscription with nobody watching)"),
    ("detach", re.compile(r"\bnohup\b|\bsetsid\b|\bdisown\b|\s-w(?:i\w*)?\s+hidden\b|\s-wi\w*\s+1\b|\bpythonw(\.exe)?\b"
                          r"|schtasks(\.exe)?\b[^\n|;&]*[/-]run\b|Start-ScheduledTask"
                          r"|\bstart\s+(?:\"[^\"]*\"\s+)?/(b|min)\b|Win32_Process[^\n]*Create|wmic[^\n]*process\s+call\s+create"
                          r"|(?<![&>|])\s&\s*(?:[);\n]|$)", I),
     "detaches or hides a process so it outlives the session (orphans, hidden relaunchers)"),
    ("decoded-payload", re.compile(r"\b(iex|Invoke-Expression)\b[^\n]*(FromBase64String|DownloadString|-enc\b)", I),
     "runs decoded or downloaded text (the payload cannot be inspected)"),
]
LOOP = re.compile(r"\b(until|while)\b|\bfor\s*\(\s*;\s*;\s*\)", I)
SLEEP = re.compile(r"\bsleep\b|Start-Sleep", I)
BOUND = re.compile(r"\btimeout\s+(-\S+\s+)*\d|\bseq\s+\d|\$SECONDS|\bSECONDS\b|\s-(lt|le|gt|ge)\s|\bfor\s+\w+\s+in\b"
                   r"|deadline|max_?(tries|iter|wait|attempts)|\b\w+\s*<\s*\d", I)
LOOP_ID, LOOP_WHY = "polling-loop", "polling loop with no bound (wrap it in `timeout <secs>` or add an iteration cap / deadline)"
UNREADABLE_ID, UNREADABLE_WHY = "encoded-command", "an encoded PowerShell command that cannot be inspected (it does not decode to text)"
PATH_RULES = [
    ("wslconfig", re.compile(r"(^|/)\.wslconfig$"), "writes ~/.wslconfig (vmIdleTimeout=-1 keeps the WSL VM alive forever)"),
    ("wsl-conf", re.compile(r"(^|/)etc/wsl\.conf$"), "writes /etc/wsl.conf (boot commands)"),
    ("startup-folder", re.compile(r"start menu/programs/startup(/|$)"), "adds a logon autostart (Startup folder)"),
    ("linux-autostart", re.compile(r"(^|/)etc/(cron|systemd/)"), "installs a Linux autostart (systemd or cron)"),
    ("macos-launch-agent", re.compile(r"(^|/)library/launch(agents|daemons)(/|$)"), "installs a macOS launch agent (autostart)"),
    ("systemd-user-unit", re.compile(r"(^|/)\.config/systemd/user(/|$)"), "installs a systemd user unit (autostart)"),
    ("xdg-autostart", re.compile(r"(^|/)\.config/autostart(/|$)"), "installs an XDG autostart entry"),
    ("shell-startup-file", re.compile(r"(^|/)\.(bashrc|bash_profile|bash_login|profile|zshrc|zprofile|zshenv)$"),
     "writes a shell startup file (it runs at every login)"),
]
ADVICE = ("Do not retry it through another shell, script or tool. If this was only a plain text search for the pattern, "
          "use the Grep or Read tool instead. Otherwise stop and give the user the exact command so they can run it "
          "themselves.")
EXPLAIN = ["Blocks commands that leave unattended automation behind. Rules (id: message):"] + \
    [f"  - {rid}: {why}" for rid, _, why in RULES] + [f"  - {LOOP_ID}: {LOOP_WHY}", f"  - {UNREADABLE_ID}: {UNREADABLE_WHY}"] + \
    [f"  - {rid} (write targets of Edit, Write and shell commands): {why}" for rid, _, why in PATH_RULES] + \
    ["Tool scope: every tool call that carries a string `command` (the hooks.json matcher is Bash|PowerShell|Monitor)."]


def _variants(command: str) -> tuple[list[str], list[tuple[str, str]]]:
    """(texts to match the rules against, hits found while decoding)."""
    base = textlib.normalize(command)
    texts: list[str] = []
    hits: list[tuple[str, str]] = []
    pending = [base]
    for decoded in textlib.decoded_commands(base):
        if decoded is None:
            hits.append((UNREADABLE_ID, UNREADABLE_WHY))
        else:
            pending.append(textlib.normalize(decoded))
    for body in textlib.nested_texts(base):
        pending.append(body)
    for seg_payload in {p for s in shell.all_segments(base) for p in shell._shell_payloads(s)}:
        pending.append(seg_payload)
    for text in pending:
        for variant in (text, textlib.deobfuscate(text)):
            if variant not in texts:
                texts.append(variant)
    return texts, hits


def scan_hits(command: str) -> list[tuple[str, str]]:
    """(rule id, reason) for every rule `command` trips, without duplicates (empty when it is fine)."""
    if not command:
        return []
    texts, hits = _variants(command)
    for text in texts:
        for rid, pattern, why in RULES:
            if pattern.search(text) and (rid, why) not in hits:
                hits.append((rid, why))
    normal = textlib.normalize(command)
    for target in shell.write_targets_of(normal):
        spelled = norm_path(target)
        for rid, pattern, why in PATH_RULES:
            if pattern.search(spelled) and (rid, why) not in hits:
                hits.append((rid, why))
    if LOOP.search(normal) and SLEEP.search(normal) and not BOUND.search(normal):
        hits.append((LOOP_ID, LOOP_WHY))
    return hits


def scan_text(command: str) -> list[str]:
    """The reasons `command` is refused, without duplicates (empty when it is fine)."""
    return [why for _, why in scan_hits(command)]


def decide(payload) -> dict:
    name = tool_name(payload)
    hits: list[str] = []
    command = command_of(payload)
    if command:
        hits = scan_text(command)
    else:
        path = file_path_of(payload)
        if path and name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            normal = norm_path(path)
            hits = [why for _, pattern, why in PATH_RULES if pattern.search(normal)]
    if not hits:
        return allow()
    return deny("BLOCKED by guard-automation (no unattended automation): " + "; ".join(hits) + ". " + ADVICE)
