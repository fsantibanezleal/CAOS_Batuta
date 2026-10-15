"""Guard `guard-automation`: the ported rule table (unattended automation) with positive and negative cases."""
import base64
import unittest

from test_guard_common import GuardCase, bash, pre

from batuta_lib.areas import guard


def handler(payload):
    return guard.HOOKS["guard-automation"](payload)


def enc(text):
    return base64.b64encode(text.encode("utf-16-le")).decode()


SCHEDULED = [
    "Register-ScheduledTask -TaskName x -Action $a -Trigger $t",
    "New-ScheduledTaskTrigger -Daily -At 3am",
    "New-ScheduledTaskAction -Execute python",
    "Set-ScheduledTask -TaskName x",
    "Enable-ScheduledTask -TaskName x",
    "schtasks /create /tn x /tr foo.exe /sc daily",
    "schtasks.exe /Create /tn x /tr foo.exe",
    "schtasks /change /tn x /disable",
    "powershell -Command \"Register-ScheduledTask x\"",
    "pwsh -NoProfile -c 'schtasks /create /tn x'",
    "Register-ScheduledJob -Name x -ScriptBlock {1}",
    "Start-ScheduledTask -TaskName x",
    "schtasks /run /tn x",
]

RUN_KEYS = [
    "reg add HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run /v x /d y",
    "reg.exe add HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\RunOnce /v x /d y",
    "New-ItemProperty -Path HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run -Name x -Value y",
    "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run' -Name x -Value y",
]

STARTUP = [
    "Copy-Item x.lnk \"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\"",
    "cp x.lnk '$APPDATA/Microsoft/Windows/Start Menu/Programs/Startup/'",
    "Move-Item a.bat shell:startup",
    "$s.CreateShortcut(\"$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\x.lnk\")",
]

SERVICES = [
    "New-Service -Name x -BinaryPathName foo.exe",
    "sc create x binPath= foo.exe",
    "sc.exe config x start= auto",
    "nssm install x foo.exe",
    "nssm.exe set x AppDirectory y",
]

WMI = [
    "Set-WmiInstance -Class __EventFilter -Arguments $a",
    "New-CimInstance -ClassName CommandLineEventConsumer",
    "Register-WmiEvent -Class ActiveScriptEventConsumer",
    "$b = [wmiclass]'__FilterToConsumerBinding'",
]

WSL = [
    "echo '[wsl2]' >> ~/.wslconfig",
    "Set-Content $env:USERPROFILE\\.wslconfig '[wsl2]'",
    "Add-Content -Path ~/.wslconfig -Value x",
    "echo x | tee -a ~/.wslconfig",
    "cp a.txt ~/.wslconfig",
    "echo '[boot]' >> /etc/wsl.conf",
    "echo '[boot]' | sudo tee /etc/wsl.conf",
    "sudo sed -i s/a/b/ /etc/wsl.conf",
]

LINUX = [
    "systemctl enable foo.service",
    "systemctl --user enable foo",
    "sudo systemctl --now enable foo",
    "loginctl enable-linger me",
    "crontab mycron.txt",
    "crontab -e",
    "echo '* * * * * x' >> /etc/cron.d/x",
]

HEADLESS = [
    "claude -p 'do things'",
    "claude --print 'do things'",
    "claude.exe -p x",
    "\"claude\" -p x",
    "cat prompt | claude -p",
    "claude --dangerously-skip-permissions",
    "some-wrapper --dangerously-skip-permissions run",
]

DETACH = [
    "nohup python x.py &",
    "setsid python x.py",
    "disown",
    "Start-Process python -ArgumentList x.py -WindowStyle Hidden",
    "Start-Process pythonw x.py",
    "pythonw C:\\x\\y.py",
    "pythonw.exe -m http.server",
    "pythonw ./run.pyw",
]

LOOPS = [
    "while true; do sleep 5; done",
    "until [ -f x ]; do sleep 1; done",
    "while ($true) { Start-Sleep 5 }",
]

OBFUSCATED = [
    "Reg`ister-Sched`uledTask -TaskName x",
    "sch^tasks /create /tn x",
    'sch""tasks /create /tn x',
    "\uff53\uff43\uff48\uff54\uff41\uff53\uff4b\uff53 /create /tn x",
    "sch\u200btasks /create /tn x",
    "powershell -EncodedCommand " + enc("Register-ScheduledTask -TaskName x"),
    "powershell -enc " + enc("schtasks /create /tn x"),
    "pwsh -NoProfile -ec " + enc("Set-Content ~/.wslconfig x"),
    "powershell -EncodedCommand ZZZ-not-base64",
    "Set-Alias rst Register-ScheduledTask; rst -TaskName x",
    "New-Alias -Name rst -Value Register-ScheduledTask",
    "iex ([Text.Encoding]::Unicode.GetString([Convert]::FromBase64String('abc')))",
    "Invoke-Expression ([System.Convert]::FromBase64String($x))",
    "bash -c 'crontab mycron.txt'",
    "sh -c \"echo a; systemctl enable foo\"",
    "echo $(crontab mycron.txt)",
    "echo `crontab mycron.txt`",
    "true && crontab mycron.txt",
    "echo ok\ncrontab mycron.txt",
]

ALLOWED = [
    "ls -la",
    "git status",
    "python -m unittest discover -s tests",
    "Get-ScheduledTask -TaskName x",
    "Unregister-ScheduledTask -TaskName x -Confirm:$false",
    "schtasks /query /tn x",
    "reg query HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
    "crontab -l",
    "systemctl status foo",
    "systemctl --user start foo",
    "sc query x",
    "claude --version",
    "claude mcp list",
    "Start-Process notepad",
    "echo 'schedule a task for later'",
    "cat ~/.wslconfig",
    "timeout 60 bash -c 'until [ -f x ]; do sleep 1; done'",
    "for i in 1 2 3; do sleep 1; done",
    "i=0; while [ $i -lt 5 ]; do sleep 1; i=$((i+1)); done",
    "until [ -f x ]; do sleep 1; done  # deadline 60",
    "while ($n -lt 10) { Start-Sleep 1; $n++ }",
    "pip install requests",
    "powershell -NoProfile -Command \"Get-Date\"",
    "powershell -EncodedCommand " + enc("Get-Date"),
    "git log --oneline -5",
]


class AutomationGuard(GuardCase):
    def test_every_group_is_blocked(self):
        groups = {"scheduled": SCHEDULED, "run keys": RUN_KEYS, "startup": STARTUP, "services": SERVICES, "wmi": WMI,
                  "wsl": WSL, "linux": LINUX, "headless": HEADLESS, "detach": DETACH, "loops": LOOPS,
                  "obfuscated": OBFUSCATED}
        for name, cases in groups.items():
            with self.subTest(group=name):
                self.table(handler, cases, [])

    def test_allowed_commands(self):
        self.table(handler, [], ALLOWED)

    def test_each_group_has_at_least_three_cases_each_way(self):
        for cases in (SCHEDULED, RUN_KEYS, STARTUP, SERVICES, WMI, WSL, LINUX, HEADLESS, DETACH, LOOPS, OBFUSCATED):
            self.assertGreaterEqual(len(cases), 3)
        self.assertGreaterEqual(len(ALLOWED), 3)

    def test_the_reason_names_each_rule_hit(self):
        result = handler(bash("schtasks /create /tn x /tr y; crontab z"))
        self.denies(result, "scheduled task")
        self.assertIn("autostart", result["output"]["hookSpecificOutput"]["permissionDecisionReason"].lower())

    def test_the_reason_tells_the_model_to_hand_the_command_to_the_user(self):
        result = handler(bash("nohup x &"))
        reason = result["output"]["hookSpecificOutput"]["permissionDecisionReason"].lower()
        self.assertIn("do not retry", reason)
        self.assertIn("user", reason)

    def test_an_unbounded_polling_loop_is_named(self):
        self.denies(handler(bash("while true; do sleep 5; done")), "polling loop")

    def test_the_undecodable_encoded_command_says_it_cannot_be_inspected(self):
        self.denies(handler(bash("powershell -enc ZZZ")), "cannot be inspected")

    def test_a_search_for_the_pattern_with_grep_is_still_flagged_with_a_hint(self):
        result = handler(bash("grep -rn 'Register-ScheduledTask' ."))
        self.denies(result)
        self.assertIn("grep", result["output"]["hookSpecificOutput"]["permissionDecisionReason"].lower())

    def test_write_tool_to_wslconfig_is_blocked(self):
        for path in ("~/.wslconfig", "/etc/wsl.conf", "x/.WSLCONFIG"):
            with self.subTest(path=path):
                self.denies(handler(pre("Write", file_path=path, content="x")))
                self.denies(handler(pre("Edit", file_path=path, old_string="a", new_string="b")))

    def test_write_tool_to_startup_or_cron_is_blocked(self):
        for path in ("C:/x/Microsoft/Windows/Start Menu/Programs/Startup/a.bat", "/etc/cron.d/job",
                     "/etc/systemd/system/x.service.wants/y"):
            with self.subTest(path=path):
                self.denies(handler(pre("Write", file_path=path, content="x")))

    def test_write_tool_elsewhere_is_allowed(self):
        self.allows(handler(pre("Write", file_path="src/a.py", content="x")))
        self.allows(handler(pre("Edit", file_path="docs/wslconfig-notes.md", old_string="a", new_string="b")))

    def test_other_tools_and_odd_payloads_are_allowed(self):
        self.allows(handler(pre("Read", file_path="~/.wslconfig")))
        self.allows(handler({}))
        self.allows(handler({"tool_name": "Bash"}))
        self.allows(handler({"tool_name": "Bash", "tool_input": {"command": 5}}))
        self.allows(handler({"tool_name": "Bash", "tool_input": {"command": ""}}))
        self.allows(handler({"tool_name": "Bash", "tool_input": "x"}))

    def test_powershell_tool_input_is_scanned_like_bash(self):
        self.denies(handler(pre("PowerShell", command="Register-ScheduledTask -TaskName x")))
        self.allows(handler(pre("PowerShell", command="Get-Date")))


if __name__ == "__main__":
    unittest.main()
