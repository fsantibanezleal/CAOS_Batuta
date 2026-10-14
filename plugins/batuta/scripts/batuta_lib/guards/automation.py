"""Guard `automation`: nothing a session starts may run unattended or outlive it.

The rule table: scheduled tasks, logon autostarts (Run keys, Startup folder), services, permanent WMI subscriptions,
`.wslconfig` and `wsl.conf` writes, Linux autostarts (systemd enable, linger, cron), headless `claude -p` and
`--dangerously-skip-permissions`, detached or hidden processes and unbounded polling loops. A command is matched
as written, after Unicode folding, with quote, backtick and caret obfuscation removed, inside every nested command
(`bash -c`, `$(...)`, backticks) and inside decoded PowerShell `-EncodedCommand` payloads; a payload that cannot be
decoded or that runs decoded text is refused because it cannot be inspected.
"""
from __future__ import annotations

import re

from . import allow, command_of, deny, file_path_of, norm_path, tool_name
from . import text as textlib

NAME = "automation"
I = re.IGNORECASE

RULES = [
    (re.compile(r"(?<!Un)Register-ScheduledTask|Register-ScheduledJob|New-ScheduledTask(Trigger|Action|Settings|Principal)?\b"
                r"|New-JobTrigger|Set-ScheduledTask|Enable-ScheduledTask|Schedule\.Service", I),
     "creates or changes a Windows scheduled task"),
    (re.compile(r"schtasks(\.exe)?\b[^\n|;&]*/(create|change)\b", I), "creates or changes a Windows scheduled task (schtasks)"),
    (re.compile(r"(reg(\.exe)?\s+add|New-ItemProperty|Set-ItemProperty|New-Item)[^\n]*\\CurrentVersion\\Run", I),
     "adds a logon autostart (Run / RunOnce registry key)"),
    (re.compile(r"(Copy-Item|Move-Item|New-Item|Out-File|Set-Content|CreateShortcut|\bcp\b|\bmv\b|\bln\b)[^\n]*"
                r"(Start Menu[\\/]Programs[\\/]Startup|shell:startup)", I), "adds a logon autostart (Startup folder)"),
    (re.compile(r"New-Service\b|\bsc(\.exe)?\s+(create|config)\b|\bnssm(\.exe)?\s+(install|set)\b", I),
     "creates or reconfigures a Windows service"),
    (re.compile(r"__EventFilter|CommandLineEventConsumer|ActiveScriptEventConsumer|__FilterToConsumerBinding", I),
     "creates a permanent WMI event subscription"),
    (re.compile(r"(>>?\s*[\"']?[^\s\"'|;&]*\.wslconfig)|((Set-Content|Add-Content|Out-File|WriteAllText|Copy-Item|Move-Item"
                r"|\btee\b|\bcp\b|\bmv\b)[^\n;|]*\.wslconfig)", I),
     "writes ~/.wslconfig (vmIdleTimeout=-1 keeps the WSL VM alive forever)"),
    (re.compile(r"(>>?\s*/etc/wsl\.conf)|((\btee\b|sed\s+-i|\bcp\b|\bmv\b)[^\n;|]*/etc/wsl\.conf)", I),
     "writes /etc/wsl.conf (boot commands)"),
    (re.compile(r"systemctl\s+(--\S+\s+)*enable\b|loginctl\s+enable-linger|crontab\s+(?!-l\b)\S|>>?\s*/etc/cron", I),
     "installs a Linux autostart (systemd enable, linger or cron)"),
    (re.compile(r"\bclaude(\.exe)?[\"']?\s+(-p|--print)\b|--dangerously-skip-permissions", I),
     "launches a headless Claude session (spends the subscription with nobody watching)"),
    (re.compile(r"\bnohup\b|\bsetsid\b|\bdisown\b|Start-Process[^\n]*-WindowStyle\s+Hidden"
                r"|Start-Process\s+[\"']?[^\s\"']*pythonw"
                r"|\bpythonw(\.exe)?[\"']?\s+[\"']?([A-Za-z]:[\\/]|\.{0,2}[\\/]|[\w.-]+\.pyw?\b|-m\s)"
                r"|schtasks(\.exe)?\b[^\n|;&]*/run\b|Start-ScheduledTask", I),
     "detaches or hides a process so it outlives the session (orphans, hidden relaunchers)"),
    (re.compile(r"\b(iex|Invoke-Expression)\b[^\n]*(FromBase64String|DownloadString|-enc\b)", I),
     "runs decoded or downloaded text (the payload cannot be inspected)"),
]
LOOP = re.compile(r"\b(until|while)\b", I)
SLEEP = re.compile(r"\bsleep\b|Start-Sleep", I)
BOUND = re.compile(r"\btimeout\s+(-\S+\s+)*\d|\bseq\s+\d|\$SECONDS|\bSECONDS\b|\s-(lt|le|gt|ge)\s|\bfor\s+\w+\s+in\b"
                   r"|deadline|max_?(tries|iter|wait|attempts)|\b\w+\s*<\s*\d", I)
LOOP_WHY = "polling loop with no bound (wrap it in `timeout <secs>` or add an iteration cap / deadline)"
UNREADABLE_WHY = "an encoded PowerShell command that cannot be inspected (it does not decode to text)"
PATH_RULES = [
    (re.compile(r"(^|/)\.wslconfig$"), "writes ~/.wslconfig (vmIdleTimeout=-1 keeps the WSL VM alive forever)"),
    (re.compile(r"(^|/)etc/wsl\.conf$"), "writes /etc/wsl.conf (boot commands)"),
    (re.compile(r"start menu/programs/startup(/|$)"), "adds a logon autostart (Startup folder)"),
    (re.compile(r"(^|/)etc/(cron|systemd/)"), "installs a Linux autostart (systemd or cron)"),
    (re.compile(r"(^|/)library/launch(agents|daemons)(/|$)"), "installs a macOS launch agent (autostart)"),
    (re.compile(r"(^|/)\.config/systemd/user(/|$)"), "installs a systemd user unit (autostart)"),
]
ADVICE = ("Do not retry it through another shell, script or tool. If this was only a plain text search for the pattern, "
          "use the Grep or Read tool instead. Otherwise stop and give the user the exact command so they can run it "
          "themselves.")
EXPLAIN = ["Blocks commands that leave unattended automation behind. Rules (each with its message):"] + \
    [f"  - {why}" for _, why in RULES] + [f"  - {LOOP_WHY}", f"  - {UNREADABLE_WHY}",
                                          "  - writes (Edit/Write) to .wslconfig, wsl.conf, the Startup folder, cron and systemd paths"]


def _variants(command: str) -> tuple[list[str], list[str]]:
    """(texts to match the rules against, hits found while decoding)."""
    base = textlib.normalize(command)
    texts, hits = [], []
    pending = [base]
    for decoded in textlib.decoded_commands(base):
        if decoded is None:
            hits.append(UNREADABLE_WHY)
        else:
            pending.append(textlib.normalize(decoded))
    for body in textlib.nested_texts(base):
        pending.append(body)
    for text in pending:
        for variant in (text, textlib.deobfuscate(text)):
            if variant not in texts:
                texts.append(variant)
    return texts, hits


def scan_text(command: str) -> list[str]:
    """The reasons `command` is refused, without duplicates (empty when it is fine)."""
    if not command:
        return []
    texts, hits = _variants(command)
    for text in texts:
        for pattern, why in RULES:
            if pattern.search(text) and why not in hits:
                hits.append(why)
    top = textlib.normalize(command)
    if LOOP.search(top) and SLEEP.search(top) and not BOUND.search(top):
        hits.append(LOOP_WHY)
    return hits


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
            hits = [why for pattern, why in PATH_RULES if pattern.search(normal)]
    if not hits:
        return allow()
    return deny("BLOCKED by guard-automation (no unattended automation): " + "; ".join(hits) + ". " + ADVICE)
