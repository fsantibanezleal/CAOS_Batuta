"""The install channels, each tested in temporary folders: device, project, plugin, npx and copier.

The device and project channels need nothing but Python and git and always run. The plugin, npx and copier channels need
an outside tool (`claude`, Node 18 or newer, `copier`); where it is missing only that test is skipped, with the reason
printed on stderr and in the skip message, never a silent pass. git is required: a missing git fails the suite.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import e2e_world as ew
from e2e_world import WorldCase


def node_probe(path):
    """A reason to skip when Node is older than 18 or unreadable, else None."""
    done = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=30)
    found = re.search(r"v(\d+)", done.stdout)
    if not found:
        return "cannot read the Node version from %r" % done.stdout
    if int(found.group(1)) < 18:
        return "Node %s is older than 18 (the npx channel needs 18 or newer)" % done.stdout.strip()
    return None


class DeviceChannel(WorldCase):
    def test_init_user_then_device_check(self):
        world = self.new_world()
        flags = ("--home", world.home, "--deploy-root", world.deploy)
        self.ok(world.batuta("init", "user", *flags), "dry run")
        self.assertEqual(list(world.deploy.iterdir()), [], "a dry run writes nothing")
        applied = world.batuta("init", "user", *flags, "--apply")
        self.assertIn(applied.rc, (0, 2), applied.describe())
        self.ok(world.batuta("device", "check", *flags), "complete")
        self.validate(world, "C01", world.deploy / "batuta.json")
        self.validate(world, "C15", world.deploy / "device.json")


class ProjectChannel(WorldCase):
    def test_init_project_writes_the_project_files_and_nothing_on_a_dry_run(self):
        world = self.new_world()
        ew.init_repository(world)
        self.ok(world.batuta("init", "project", "--target", ".", "--var", "project_name=scratch"), "dry run")
        self.assertEqual(world.git("status", "--short").out.strip(), "")
        self.ok(world.batuta("init", "project", "--target", ".", "--var", "project_name=scratch", "--apply"), "written in")
        for rel in (".batuta/batuta.json", ".github/workflows/batuta-gates.yml", "specs/001-example-feature/status.md"):
            self.assertTrue(world.path(rel).is_file(), rel)
        self.validate(world, "C01", world.path(".batuta/batuta.json"))


class PluginChannel(WorldCase):
    def test_claude_plugin_validate_strict(self):
        claude = ew.skip_unless_tool(self, "claude")
        world = self.new_world()
        done = world.run([claude, "plugin", "validate", "--strict", str(ew.PLUGIN)], cwd=ew.REPO)
        self.assertEqual(done.rc, 0, done.describe())


class NpxChannel(WorldCase):
    def test_the_npx_entry_runs_the_same_command_with_the_same_output(self):
        node = ew.skip_unless_tool(self, "node", node_probe)
        world = self.new_world()
        direct = self.ok(world.batuta("version", "show", cwd=ew.REPO))
        via = world.run([node, ew.NPX, "version", "show"], cwd=ew.REPO)
        self.assertEqual(via.rc, direct.rc, via.describe())
        self.assertEqual(via.out, direct.out, via.describe())


class CopierChannel(WorldCase):
    def test_copier_and_init_project_render_the_same_files(self):
        copier = ew.skip_unless_tool(self, "copier")
        world = self.new_world()
        source = world.root / "template-source"
        shutil.copytree(ew.PLUGIN / "templates", source / "plugins" / "batuta" / "templates")
        shutil.copy2(ew.REPO / "copier.yml", source / "copier.yml")
        out = world.root / "from-copier"
        done = world.run([copier, "copy", "--defaults", "--trust", "--data", "project_name=scratch", str(source), str(out)],
                         cwd=world.root, timeout=300)
        self.assertEqual(done.rc, 0, done.describe())
        ew.init_repository(world)
        self.ok(world.batuta("init", "project", "--target", ".", "--var", "project_name=scratch", "--apply"), "written in")
        for rel in (".batuta/batuta.json", ".github/workflows/batuta-gates.yml"):
            self.assertEqual((out / rel).read_bytes(), world.path(rel).read_bytes(), rel)


class MissingTools(unittest.TestCase):
    """The two rules of the missing-data behavior, tested without needing the tools to be absent."""

    def test_a_missing_optional_tool_skips_with_the_reason_and_never_passes_silently(self):
        case = unittest.TestCase()
        with mock.patch.object(sys, "stderr") as err:
            with self.assertRaises(unittest.SkipTest) as caught:
                ew.skip_unless_tool(case, "batuta-no-such-tool-xyz")
        self.assertIn("batuta-no-such-tool-xyz", str(caught.exception))
        self.assertIn("not on PATH", str(caught.exception))
        self.assertTrue(err.write.called, "the reason is also printed")

    def test_a_missing_git_fails_the_suite(self):
        with mock.patch.object(ew.subprocess, "run", side_effect=FileNotFoundError("git")):
            with self.assertRaises(AssertionError) as caught:
                ew.require_git()
        self.assertIn("git is required", str(caught.exception))

    def test_a_too_old_git_fails_the_suite(self):
        with mock.patch.object(ew, "git_version", return_value=(2, 29)):
            with self.assertRaises(AssertionError):
                ew.require_git()


if __name__ == "__main__":
    unittest.main()
