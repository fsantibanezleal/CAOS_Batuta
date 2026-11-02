"""Reproductions of the Opus review findings F-1 to F-10, F-13, F-14, F-17, F-22, F-23 (payload cases of the review,
D2 numbers in the comments). Every case is a payload; no command is ever executed."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from test_guard_common import GuardCase, bash, decision_of, isolated_env, pre, reason_of, write_config, write_json

from batuta_lib.areas import guard

PLUGIN = pathlib.Path(__file__).resolve().parents[1] / "plugins" / "batuta"
SHA = "a" * 64


def handler(name, payload):
    return guard.HOOKS[f"guard-{name}"](payload)


class Project(GuardCase):
    """A fixture project: a locked test, an approvals folder, a secret file."""

    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name).resolve()
        (self.root / ".git").mkdir()
        for rel, text in (("tests/test_a.py", "x\n"), ("tests/test_b.py", "y\n"), (".env", "KEY=1\n"),
                          ("README.md", "r\n"), ("specs/f/approvals/a.json", "{}\n"), ("src/app.py", "z\n")):
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        write_json(self.root / ".batuta" / "test-locks.json", {"contract_version": "1.0", "entries": [
            {"path": "tests/test_a.py", "sha256": SHA, "task_id": "T-001", "req_ids": ["REQ-A-001"],
             "locked_commit": "abc", "locked_at": "2026-10-13T10:00:00Z"}]})

    def sh(self, command, tool="Bash"):
        return pre(tool, self.root, command=command)

    def deny_all(self, name, commands, tool="Bash"):
        for command in commands:
            with self.subTest(command=command):
                self.denies(handler(name, self.sh(command, tool)), msg=f"expected deny: {command}")

    def allow_all(self, name, commands, tool="Bash"):
        for command in commands:
            with self.subTest(command=command):
                self.allows(handler(name, self.sh(command, tool)), command)


class F1MonitorTool(Project):
    def test_every_shell_guard_reads_the_command_of_the_monitor_tool(self):  # automation 017
        self.denies(handler("automation", self.sh("schtasks /create /tn x /tr y /sc minute", "Monitor")))
        self.denies(handler("locked-tests", self.sh("echo x > tests/test_a.py", "Monitor")))
        self.denies(handler("secrets", self.sh("cat .env", "Monitor")))
        self.denies(handler("destructive", self.sh("git reset --hard", "Monitor")))
        self.denies(handler("approvals", self.sh("echo {} > specs/f/approvals/a.json", "Monitor")))

    def test_a_tool_with_a_string_command_is_read_and_one_without_is_not(self):
        self.denies(handler("automation", pre("SomeFutureShell", self.root, command="crontab x")))
        self.allows(handler("automation", pre("Read", self.root, file_path="x")))


class F2AssignmentPrefix(Project):
    def test_powershell_assignment_prefixes_do_not_hide_the_command(self):  # secrets 058 059, locked 014, approvals 043, destructive 075
        self.deny_all("secrets", ["$x = Get-Content .env; $x", "$x = cat .env", "$x=Get-Content .env",
                                  "[string]$x = Get-Content .env", "$x += gc .env"], "PowerShell")
        self.deny_all("locked-tests", ["$null = Set-Content tests/test_a.py 'x'", "$r = Remove-Item tests/test_a.py"], "PowerShell")
        self.deny_all("approvals", ["$null = Set-Content specs/f/approvals/a.json '{}'"], "PowerShell")
        self.deny_all("destructive", ["$r = Remove-Item -Recurse -Force C:\\"], "PowerShell")

    def test_block_braces_do_not_hide_the_command(self):
        self.deny_all("locked-tests", ["if ($true) { Remove-Item tests/test_a.py }", "foreach ($i in 1) {Set-Content tests/test_a.py x}"], "PowerShell")

    def test_a_plain_assignment_of_a_harmless_value_is_allowed(self):
        self.allow_all("secrets", ["$x = Get-Content README.md", "$y = 5"], "PowerShell")


class F3UnquotedNestedShells(Project):
    def test_cmd_and_powershell_arguments_are_inspected_unquoted(self):  # locked 020 021, approvals 045, secrets 060 061, destructive 073 074
        self.deny_all("locked-tests", ["cmd /c del tests\\test_a.py", "pwsh -c Remove-Item tests/test_a.py",
                                       "powershell -Command Remove-Item tests/test_a.py", "bash -c rm tests/test_a.py",
                                       "wsl rm tests/test_a.py", "cmd /c \"echo x > tests\\test_a.py\""])
        self.deny_all("approvals", ["cmd /c copy a.json specs\\f\\approvals\\"])
        self.deny_all("secrets", ["cmd /c type .env", "pwsh -c gc .env", "powershell -c Get-Content .env"])
        self.deny_all("destructive", ["cmd /c rd /s /q C:\\", "powershell Remove-Item -Recurse -Force C:\\"])

    def test_unquoted_nested_commands_that_are_harmless_pass(self):
        self.allow_all("locked-tests", ["cmd /c dir tests", "pwsh -c Get-Content tests/test_a.py"])


class F4Globs(Project):
    def test_locked_paths_are_matched_by_glob_targets(self):  # locked 007 008 009
        self.deny_all("locked-tests", ["rm tests/test_*.py", "sed -i s/1/2/ tests/*.py", "rm tests/*", "rm tests/test_?.py"])
        self.deny_all("locked-tests", ["Remove-Item tests\\*", "Remove-Item tests\\test_[a-b].py"], "PowerShell")
        self.allow_all("locked-tests", ["rm tests/other_*.py", "rm src/*.py"])

    def test_secret_files_are_matched_by_glob_targets(self):  # secrets 051 052
        self.deny_all("secrets", ["cat .en?", "cat .e*", "cat .[e]nv", "head -1 ./.en*"])
        self.allow_all("secrets", ["cat READ*", "cat src/*.py"])


class F5MissingWriters(Project):
    def test_copies_into_the_folder_and_more_writers(self):  # locked 010 011 015 016 017 018 019 022, approvals 044
        self.deny_all("locked-tests", [
            "cp /tmp/test_a.py tests/", "cp /tmp/test_a.py tests", "cp -r /tmp/x/* tests/", "install /tmp/test_a.py tests/",
            "find tests -name test_a.py -exec sed -i s/1/2/ {} +", "find tests -name test_a.py -delete",
            "echo tests/test_a.py | xargs rm", "cat list.txt | xargs rm", "git apply evil.patch", "git am evil.mbox",
            "mv /tmp/test_a.py tests/", "rsync -a /tmp/x/ tests/"])
        self.deny_all("locked-tests", [
            "Copy-Item C:\\tmp\\test_a.py tests\\", "sc tests\\test_a.py 'x'", "ac tests\\test_a.py 'x'",
            "'x' | Tee-Object -FilePath tests\\test_a.py", "clc tests\\test_a.py", "Get-ChildItem tests | Remove-Item"], "PowerShell")
        self.deny_all("approvals", ["sc specs\\f\\approvals\\a.json '{}'", "cp /tmp/a.json specs/f/approvals/"])
        self.deny_all("approvals", ["Copy-Item C:\\tmp\\a.json specs\\f\\approvals\\"], "PowerShell")

    def test_copies_out_of_the_folder_are_reads(self):
        self.allow_all("locked-tests", ["cp tests/test_a.py /tmp/", "cp tests/test_a.py /tmp/copy.py", "find src -name '*.py'",
                                        "cp /tmp/other.py tests/", "mv /tmp/new.py tests/", "echo build/a.o | xargs rm",
                                        "find tests -name test_a.py", "ls tests | xargs echo"])


class F6SecretReads(Project):
    def test_dotnet_reads_in_the_powershell_tool(self):  # secrets 057
        self.deny_all("secrets", ["[IO.File]::ReadAllText('.env')", "[System.IO.File]::ReadAllLines(\".env\")",
                                  "[IO.File]::OpenRead('.env')"], "PowerShell")

    def test_grep_tool_glob_and_folder(self):  # secrets 054 055
        self.denies(handler("secrets", pre("Grep", self.root, pattern="K", glob=".env")))
        self.denies(handler("secrets", pre("Grep", self.root, pattern="K", path=str(self.root), glob=".env*")))
        self.denies(handler("secrets", pre("Grep", self.root, pattern="K", glob="**/.env")))
        self.allows(handler("secrets", pre("Grep", self.root, pattern="K", glob="*.py")))
        self.allows(handler("secrets", pre("Grep", self.root, pattern="K", path="src", glob="*.py")))

    def test_recursive_search_over_a_folder_that_holds_a_secret(self):  # secrets 053
        self.deny_all("secrets", ["grep -r KEY .", "grep -rn KEY", "rg KEY", "rg KEY .", "ag KEY .", "grep -R KEY ."])
        self.deny_all("secrets", ["Select-String -Path . -Pattern KEY -Recurse"], "PowerShell")
        self.allow_all("secrets", ["grep -r KEY src", "grep -r KEY . --exclude=.env", "grep -r KEY . --exclude-dir=.git --exclude=.env*",
                                   "rg KEY -g '!.env' .", "grep KEY README.md"])

    def test_git_show_of_a_secret_path(self):  # secrets 062
        self.deny_all("secrets", ["git show HEAD:.env", "git cat-file -p HEAD:.env", "git show main:config/.env.local"])
        self.allow_all("secrets", ["git show HEAD:README.md", "git show HEAD", "git log --oneline"])


class F7DestructiveSpellings(Project):
    def test_abbreviated_git_options(self):  # destructive 071 072
        self.deny_all("destructive", ["git reset --har HEAD~1", "git reset --ha", "git clean --forc -d", "git clean --fo -d",
                                      "git push --for origin main", "git push --forc origin main"])
        self.allow_all("destructive", ["git reset --soft HEAD~1", "git push --follow-tags origin task/x", "git reset --help"])

    def test_pipelines_xargs_and_find_into_deletes(self):  # destructive 076 077 078
        self.deny_all("destructive", ["ls / | xargs rm -rf", "find / -delete", "find ~ -delete", "find / -exec rm -rf {} +"])
        self.deny_all("destructive", ["Get-ChildItem C:\\ | Remove-Item -Recurse -Force", "gci C:\\ | ri -r -fo"], "PowerShell")
        self.allow_all("destructive", ["find build -name '*.pyc' -delete", "ls build | xargs rm -rf", "find . -name x"])

    def test_home_folders_are_roots(self):  # destructive 079 080 (built at run time: no user path literal in the repository)
        lin, mac, win = "/" + "home" + "/someone", "/" + "Users" + "/someone", "C:" + "/" + "Users" + "/someone"
        self.deny_all("destructive", [f"rm -rf {lin}", f"rm -rf {lin}/", f"rm -rf {win}", f"rm -rf {mac}",
                                      "Remove-Item -Recurse -Force " + win.replace("/", "\\")])
        self.allow_all("destructive", [f"rm -rf {lin}/build", f"rm -rf {win}/proj/dist"])

    def test_deleting_a_protected_branch_remotely(self):  # destructive 081 082 (F-23)
        self.deny_all("destructive", ["git push origin :main", "git push origin --delete main", "git push origin -d master",
                                      "git push origin --del develop", "git push origin :release/1.0"])
        self.allow_all("destructive", ["git push origin :task/old", "git push origin --delete task/old"])

    def test_configured_protected_branches_cover_deletes_too(self):
        write_config(self.root, guards={"protected_branches": ["prod"]})
        self.denies(handler("destructive", self.sh("git push origin :prod")))
        self.denies(handler("destructive", self.sh("git push origin --delete prod")))


class F8SwitchingTheGuardsOff(Project):
    def test_deleting_the_lock_or_its_folder_is_denied(self):  # locked 023 024
        self.deny_all("locked-tests", ["rm -rf .batuta", "rm -rf .batuta/", "rm .batuta/test-locks.json", "mv .batuta /tmp/x",
                                       "rm -r ./.batuta", "echo {} > .batuta/test-locks.json", "cmd /c rmdir /s /q .batuta"])
        self.deny_all("locked-tests", ["Remove-Item -Recurse -Force .batuta", "Remove-Item .batuta\\test-locks.json",
                                       "Move-Item .batuta ..\\x"], "PowerShell")
        self.denies(handler("locked-tests", pre("Write", self.root, file_path=".batuta/test-locks.json", content="{}")))

    def test_the_configured_lock_location_is_protected_too(self):
        write_config(self.root, tdd={"lock_file": "locks/custom.json"})
        write_json(self.root / "locks" / "custom.json", {"contract_version": "1.0", "entries": [
            {"path": "tests/test_a.py", "sha256": SHA, "task_id": "T-001", "req_ids": ["REQ-A-001"],
             "locked_commit": "abc", "locked_at": "2026-10-13T10:00:00Z"}]})
        self.deny_all("locked-tests", ["rm locks/custom.json", "rm -rf locks", "rm .batuta/test-locks.json"])

    def test_a_write_to_the_project_config_asks_and_names_the_security_keys(self):  # locked 025
        for payload in (pre("Write", self.root, file_path=".batuta/batuta.json", content="{}"),
                        pre("Edit", self.root, file_path=str(self.root / ".batuta" / "batuta.json"), old_string="a", new_string="b"),
                        self.sh("echo {} > .batuta/batuta.json"), self.sh("Set-Content .batuta\\batuta.json '{}'", "PowerShell")):
            with self.subTest(payload=str(payload)[:60]):
                result = handler("locked-tests", payload)
                self.asks(result)
                self.assertIn("guards.", reason_of(result))
                self.assertIn("tdd.lock_file", reason_of(result))

    def test_reading_the_config_is_allowed(self):
        self.allow_all("locked-tests", ["cat .batuta/batuta.json", "ls .batuta"])
        self.allows(handler("locked-tests", pre("Read", self.root, file_path=".batuta/batuta.json")))


class F9ProjectRoot(Project):
    def setUp(self):
        super().setUp()
        self.elsewhere = pathlib.Path(self.tmp.name).resolve() / "elsewhere"
        self.elsewhere.mkdir()

    def at(self, tool, **ti):
        return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti, "cwd": str(self.elsewhere)}

    def test_the_project_dir_variable_wins_over_the_payload_cwd(self):  # locked 028 029
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.root)
        self.denies(handler("locked-tests", self.at("Bash", command=f"echo x > {(self.root / 'tests' / 'test_a.py').as_posix()}")))
        self.denies(handler("locked-tests", self.at("Edit", file_path=str(self.root / "tests" / "test_a.py"), old_string="a", new_string="b")))
        self.denies(handler("locked-tests", self.at("Write", file_path="tests/test_a.py", content="x")))

    def test_an_absolute_target_in_another_project_is_checked_against_that_project(self):
        self.denies(handler("locked-tests", self.at("Bash", command=f"echo x > {(self.root / 'tests' / 'test_a.py').as_posix()}")))
        self.denies(handler("locked-tests", self.at("Edit", file_path=str(self.root / "tests" / "test_a.py"), old_string="a", new_string="b")))
        self.denies(handler("approvals", self.at("Write", file_path=str(self.root / "specs" / "f" / "approvals" / "n.json"), content="x")))
        self.allows(handler("locked-tests", self.at("Write", file_path=str(self.root / "tests" / "test_c.py"), content="x")))


class F10Spellings(Project):
    BLOCKED = [
        "Start-Process python -Wi Hidden -ArgumentList a.py", "Start-Process python -WindowStyle 1", "saps python -WindowStyle Hidden",
        "start python -WindowStyle Hidden", "cmd /c start \"\" /b python loop.py", "powershell -w hidden -c python loop.py",
        "Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine='x'}",
        "wmic process call create 'python loop.py'", "python loop.py &", "(python loop.py &)", "pythonw.exe -c \"import loop\"",
        "schtasks -create -tn x -tr y", "at 23:00 /every:M python a.py", "echo 'python a.py' | at now + 1 hour",
        "systemd-run --user --on-calendar=hourly python a.py", "systemctl -q enable foo", "systemctl --user add-wants default.target foo.service",
        "ln -s ~/foo.service ~/.config/systemd/user/default.target.wants/foo.service",
        "cat > ~/.config/systemd/user/foo.service <<EOF\n[Service]\nEOF", "cp run.desktop ~/.config/autostart/",
        "echo 'python ~/a.py &' >> ~/.bashrc", "Copy-Item a.bat ([Environment]::GetFolderPath('Startup'))",
        "copy a.bat \"%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\\"",
        "echo python a.py > \"%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\Startup\\a.bat\"", "reg import autostart.reg",
        "Set-ItemProperty -Path HKCU:/Software/Microsoft/Windows/CurrentVersion/Run -Name x -Value y",
        "sp HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Run x y",
        "[Microsoft.Win32.Registry]::SetValue('HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Run','x','y')",
        "Set-Service foo -StartupType Automatic", "New-Item -Path $HOME\\.wslconfig -Value '[wsl2]' -Force",
        "[IO.File]::WriteAllLines(\"$HOME\\.wslconfig\", 'x')", "ac $HOME\\.wslconfig 'vmIdleTimeout=-1'",
        "claude --model sonnet -p \"do it\"", "claude.cmd -p \"x\"", "npx @anthropic-ai/claude-code -p \"x\"",
        "claude --permission-mode bypassPermissions \"x\"", "claude --allow-dangerously-skip-permissions",
        "for(;;){ Start-Sleep 5; gci }",
    ]
    ALLOWED = ["git status", "claude --version", "claude mcp list", "echo a && echo b", "python run.py 2>&1", "cat ~/.bashrc",
               "ls ~/.config", "systemctl status foo", "reg query HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run",
               "Get-Service foo", "at --version"]

    def test_blocked_spellings(self):
        self.deny_all("automation", self.BLOCKED)

    def test_allowed_spellings(self):
        self.allow_all("automation", self.ALLOWED)

    def test_path_rules_apply_to_shell_write_targets(self):
        self.deny_all("automation", ["echo x > ~/.wslconfig", "tee /etc/cron.d/x", "cp a ~/.config/autostart/a.desktop"])


class F13Lockout(Project):
    def test_a_malformed_lock_does_not_block_reads(self):
        (self.root / ".batuta" / "test-locks.json").write_text("<<<<<<< HEAD\n", encoding="utf-8")
        self.allow_all("locked-tests", ["ls", "cat README.md", "git status"])
        self.allows(handler("locked-tests", pre("Read", self.root, file_path="tests/test_a.py")))
        for payload in (self.sh("echo x > notes.txt"),):
            with self.assertRaises(ValueError):
                handler("locked-tests", payload)
        with self.assertRaises(ValueError):
            handler("locked-tests", pre("Write", self.root, file_path="src/app.py", content="x"))

    def test_a_bad_config_does_not_block_reads(self):
        (self.root / ".batuta" / "batuta.json").write_text("{broken", encoding="utf-8")
        self.allow_all("locked-tests", ["ls", "cat README.md"])


class F14F17LinksAndStreams(Project):
    def test_every_operand_of_a_link_command_is_a_write_target(self):  # locked 026, approvals 037 038, secrets 063
        self.deny_all("locked-tests", ["ln -s tests/test_a.py notes.py", "ln tests/test_a.py notes.py", "cmd /c mklink notes.py tests\\test_a.py",
                                       "cmd /c mklink /H notes.py tests\\test_a.py"])
        self.deny_all("locked-tests", ["New-Item -ItemType SymbolicLink -Path notes.py -Target tests/test_a.py",
                                       "New-Item -ItemType HardLink -Path n.py -Target tests\\test_a.py"], "PowerShell")
        self.deny_all("approvals", ["ln -s specs/f/approvals apr", "cmd /c mklink /J apr specs\\f\\approvals"])
        self.deny_all("approvals", ["New-Item -ItemType Junction -Path apr -Target specs\\f\\approvals"], "PowerShell")

    def test_a_link_that_exists_is_resolved(self):
        link = self.root / "notes.txt"
        try:
            os.symlink(self.root / ".env", link)
        except (OSError, NotImplementedError):
            self.skipTest("symlinks are not available")
        self.denies(handler("secrets", self.sh("cat notes.txt")))
        self.denies(handler("secrets", pre("Read", self.root, file_path=str(link))))
        alias = self.root / "t.py"
        os.symlink(self.root / "tests" / "test_a.py", alias)
        self.denies(handler("locked-tests", pre("Write", self.root, file_path=str(alias), content="x")))
        self.denies(handler("locked-tests", self.sh("echo x > t.py")))

    def test_a_hard_link_to_a_locked_test_is_the_same_file(self):
        link = self.root / "hard.py"
        try:
            os.link(self.root / "tests" / "test_a.py", link)
        except (OSError, NotImplementedError):
            self.skipTest("hard links are not available")
        self.denies(handler("locked-tests", pre("Write", self.root, file_path=str(link), content="x")))

    def test_ntfs_stream_spellings_fold_to_the_file(self):  # secrets 056
        for name in (".env::$DATA", ".env:Zone.Identifier", ".env::$data", ".ENV::$DATA", ".env.", ".env "):
            with self.subTest(name=name):
                self.denies(handler("secrets", pre("Read", self.root, file_path=str(self.root / name))))
        self.denies(handler("locked-tests", pre("Write", self.root, file_path="tests/test_a.py::$DATA", content="x")))
        self.denies(handler("approvals", pre("Write", self.root, file_path="specs/f/approvals/a.json:stream", content="x")))
        self.allows(handler("secrets", pre("Read", self.root, file_path="README.md")))

    def test_short_8_3_spellings_resolve_to_the_same_file(self):
        if os.name != "nt":
            self.skipTest("8.3 names exist on Windows only")
        import ctypes
        buf = ctypes.create_unicode_buffer(500)
        n = ctypes.windll.kernel32.GetShortPathNameW(str(self.root / "tests" / "test_a.py"), buf, 500)
        if not n or buf.value.lower() == str(self.root / "tests" / "test_a.py").lower():
            self.skipTest("8.3 names are disabled on this volume")
        self.denies(handler("locked-tests", pre("Write", self.root, file_path=buf.value, content="x")))


class F22BriefNone(Project):
    def launch(self, prompt, agent="searcher"):
        return pre("Agent", self.root, subagent_type=agent, prompt=prompt, description="x")

    def test_brief_none_counts_only_on_the_last_line(self):  # require-brief 092
        self.denies(handler("require-brief", self.launch("BRIEF: none\nnow write and commit the feature")))
        self.denies(handler("require-brief", self.launch("BRIEF: none\n\nmore text after")))
        self.allows(handler("require-brief", self.launch("find x\nBRIEF: none")))
        self.allows(handler("require-brief", self.launch("find x\nBRIEF: none\n\n")))
        self.allows(handler("require-brief", self.launch("find x\n  BRIEF: none  ", agent="runner")))


class ViaTheLauncher(Project):
    """A sample of the review cases through the real launcher and through `guard <name> --payload`."""

    CASES = [
        ("guard-automation", "Monitor", {"command": "schtasks /create /tn x /tr y /sc minute"}),
        ("guard-secrets", "PowerShell", {"command": "$x = Get-Content .env; $x"}),
        ("guard-locked-tests", "Bash", {"command": "rm tests/test_*.py"}),
        ("guard-locked-tests", "Bash", {"command": "cmd /c del tests\\test_a.py"}),
        ("guard-destructive", "Bash", {"command": "git reset --har HEAD~1"}),
        ("guard-destructive", "Bash", {"command": "git push origin :main"}),
        ("guard-approvals", "Bash", {"command": "ln -s specs/f/approvals apr"}),
    ]

    def run_hook(self, hid, payload):
        env = {k: v for k, v in os.environ.items() if k not in ("BATUTA_CONFIG", "CLAUDE_PROJECT_DIR")}
        proc = subprocess.run([sys.executable, "-B", str(PLUGIN / "scripts" / "hook.py"), hid], input=json.dumps(payload),
                              capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(self.root), timeout=120)
        return proc

    def test_payload_files_through_hook_py_and_the_guard_cli(self):
        for hid, tool, ti in self.CASES:
            with self.subTest(hid=hid, ti=ti):
                payload = {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": ti, "cwd": str(self.root)}
                proc = self.run_hook(hid, payload)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"], "deny", ti)
                path = self.root / "payload.json"
                path.write_text(json.dumps(payload), encoding="utf-8")
                cli = subprocess.run([sys.executable, "-B", str(PLUGIN / "scripts" / "batuta.py"), "guard", hid[len("guard-"):],
                                      "--payload", str(path)], capture_output=True, text=True, cwd=str(self.root), timeout=120,
                                     env={k: v for k, v in os.environ.items() if k not in ("BATUTA_CONFIG", "CLAUDE_PROJECT_DIR")})
                self.assertEqual(cli.returncode, 1, cli.stdout)


if __name__ == "__main__":
    unittest.main()
