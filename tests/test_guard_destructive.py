"""Guard `guard-destructive`: packs for force-push to protected branches, hard reset, rm -rf of roots, disk formatting."""
import pathlib
import tempfile
import unittest

from test_guard_common import GuardCase, bash, isolated_env, reason_of, write_json, write_config

from batuta_lib.areas import guard


def handler(payload):
    return guard.HOOKS["guard-destructive"](payload)


FORCE_PUSH = [
    "git push --force origin main",
    "git push -f origin main",
    "git push origin main --force",
    "git push --force-with-lease origin develop",
    "git push origin +main",
    "git push origin +develop:develop",
    "git push --force origin HEAD:main",
    "git push -f origin release/1.2",
    "git push --force",
    "git push -f",
    "git push --force origin master",
    "git -C repo push --force origin main",
    "echo ok && git push -f origin main",
    "bash -c 'git push --force origin main'",
]
RESET = [
    "git reset --hard",
    "git reset --hard HEAD~3",
    "git reset --hard origin/main",
    "git -C repo reset --hard",
    "git clean -fd",
    "git clean -f",
    "git clean -xdf",
]
RM_ROOTS = [
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf ~/",
    "rm -rf $HOME",
    "rm -rf \"$HOME\"",
    "rm -fr /",
    "rm -r -f /",
    "rm --recursive --force /",
    "sudo rm -rf /",
    "rm -rf C:\\",
    "rm -rf C:/",
    "Remove-Item -Recurse -Force C:\\",
    "Remove-Item -Recurse -Force $env:USERPROFILE",
    "rd /s /q C:\\",
    "rmdir /s /q %USERPROFILE%",
    "rm -rf ..",
    "rm -rf .",
    "rm -rf *",
    "cd / && rm -rf *",
]
FORMAT = [
    "mkfs.ext4 /dev/sda1",
    "mkfs -t ext4 /dev/sdb",
    "format D: /q",
    "format.com E: /fs:ntfs",
    "Format-Volume -DriveLetter D",
    "Clear-Disk -Number 1 -RemoveData",
    "dd if=/dev/zero of=/dev/sda",
    "dd if=x of=/dev/nvme0n1 bs=1M",
    "wipefs -a /dev/sda",
    "diskpart /s wipe.txt",
    "fdisk /dev/sda",
    "shred -n 3 /dev/sda",
]
ALLOWED = [
    "git push origin task/my-branch",
    "git push -u origin feature/x",
    "git push --force-with-lease origin task/my-branch",
    "git push -f origin task/my-branch",
    "git push origin +task/my-branch",
    "git push",
    "git push origin develop",
    "git reset --soft HEAD~1",
    "git reset HEAD file.txt",
    "git reset --mixed HEAD~1",
    "git clean -n",
    "git clean --dry-run -fd",
    "rm -rf build",
    "rm -rf ./dist",
    "rm -rf node_modules",
    "rm -rf /tmp/work-dir",
    "rm -rf $TMPDIR/x",
    "rm file.txt",
    "rm -r old_dir",
    "Remove-Item -Recurse -Force .\\build",
    "rd /s /q build",
    "dd if=/dev/zero of=test.img bs=1M count=1",
    "format-patch -1",
    "git format-patch -1",
    "echo format D: > notes.txt",
    "mkfs.help",
    "git status",
]


class DestructiveGuard(GuardCase):
    def setUp(self):
        self._env = isolated_env()
        self._env.__enter__()
        self.addCleanup(self._env.__exit__, None, None, None)

    def test_force_push_pack(self):
        self.table(handler, FORCE_PUSH, [])

    def test_hard_reset_pack(self):
        self.table(handler, RESET, [])

    def test_rm_roots_pack(self):
        self.table(handler, RM_ROOTS, [])

    def test_format_pack(self):
        self.table(handler, FORMAT, [])

    def test_allowed(self):
        self.table(handler, [], ALLOWED)

    def test_every_pack_has_three_cases_each_way(self):
        for cases in (FORCE_PUSH, RESET, RM_ROOTS, FORMAT, ALLOWED):
            self.assertGreaterEqual(len(cases), 3)

    def test_each_hit_carries_an_explain_line(self):
        for command, word in (("git push -f origin main", "protected"), ("git reset --hard", "uncommitted"),
                              ("rm -rf /", "root"), ("mkfs.ext4 /dev/sda1", "format")):
            with self.subTest(command=command):
                self.assertIn(word, reason_of(handler(bash(command))).lower())

    def test_lookalike_characters_are_normalized(self):
        self.denies(handler(bash("git reset --h\uff41rd")))
        self.denies(handler(bash("g\u200bit push --force origin main")))

    def test_protected_branches_come_from_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".git").mkdir()
            write_config(root, guards={"protected_branches": ["prod"]})
            self.denies(handler(bash("git push --force origin prod", root)))
            self.denies(handler(bash("git push --force origin main", root)))
            self.allows(handler(bash("git push --force origin task/x", root)))

    def test_a_pack_can_be_disabled_by_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / ".git").mkdir()
            write_config(root, guards={"destructive_disable": ["hard-reset"]})
            self.allows(handler(bash("git reset --hard", root)))
            self.denies(handler(bash("git push -f origin main", root)))

    def test_odd_payloads_are_allowed(self):
        for payload in ({}, {"tool_name": "Bash", "tool_input": {"command": None}}, {"tool_name": "Read", "tool_input": {}}):
            self.allows(handler(payload))


if __name__ == "__main__":
    unittest.main()
