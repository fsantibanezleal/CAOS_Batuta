"""Community files, git attributes, honest README, docs skeleton and the CI workflow (REPO-1, REPO-2)."""
import re
import unittest

from _support import ROOT

COMMUNITY = [
    "README.md", "LICENSE", "CODE_OF_CONDUCT.md", "CONTRIBUTING.md", "SECURITY.md",
    "CHANGELOG.md", "VERSION", "LESSONS.md", "package.json", ".gitignore", ".gitattributes",
    ".editorconfig",
]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


class RootFileTests(unittest.TestCase):
    def test_community_files_exist_and_are_not_empty(self):
        for rel in COMMUNITY:
            path = ROOT / rel
            self.assertTrue(path.is_file(), rel)
            self.assertGreater(path.stat().st_size, 0, rel)

    def test_license_is_apache_with_owner(self):
        text = read("LICENSE")
        self.assertIn("Apache License", text)
        self.assertIn("Version 2.0, January 2004", text)
        self.assertIn("Felipe A. Santibanez-Leal", text)

    def test_gitattributes_normalizes_to_lf(self):
        self.assertIn("* text=auto eol=lf", read(".gitattributes"))

    def test_gitignore_covers_python_node_os_and_local_state(self):
        text = read(".gitignore")
        for needle in ("__pycache__/", "node_modules/", ".DS_Store", "Thumbs.db", ".batuta/local/"):
            self.assertIn(needle, text)

    def test_security_and_conduct_name_a_private_channel(self):
        self.assertIn("privately", read("SECURITY.md"))
        self.assertIn("Contributor Covenant", read("CODE_OF_CONDUCT.md"))

    def test_contributing_states_the_branch_flow(self):
        text = read("CONTRIBUTING.md")
        self.assertIn("task/", text)
        self.assertIn("develop", text)


class ReadmeHonestyTests(unittest.TestCase):
    def setUp(self):
        self.text = read("README.md")

    def test_states_pre_release_status(self):
        self.assertIn("pre-release", self.text)
        self.assertIn("under construction toward 0.01.000", self.text)

    def test_install_channels_are_stated_as_they_work(self):
        # U10: the channels exist after U9; the README states them and the one-step marketplace line.
        self.assertIn("/plugin install batuta --marketplace fsantibanezleal/CAOS_Batuta", self.text)
        self.assertIn("npx github:fsantibanezleal/CAOS_Batuta", self.text)
        self.assertIn("copier copy", self.text)

    def test_no_static_claim_badges(self):
        self.assertNotRegex(self.text, r"img\.shields\.io/badge/")

    def test_describes_layout(self):
        for needle in ("plugins/batuta", "bin/batuta.mjs", "batuta.py", "docs/"):
            self.assertIn(needle, self.text)

    def test_links_the_documentation_map(self):
        for needle in ("docs/concepts/principles.md", "docs/guides/install.md", "docs/reference/cli.md"):
            self.assertIn(needle, self.text)


class DocsSkeletonTests(unittest.TestCase):
    def test_docs_index_links_four_sections(self):
        text = read("docs/README.md")
        for section in ("Concepts", "Guides", "Reference", "Decisions"):
            self.assertIn(section, text)

    def test_adr_0001(self):
        text = read("docs/decisions/ADR-0001-architecture.md")
        self.assertRegex(text, r"(?m)^status: Accepted$")
        self.assertRegex(text, r"(?m)^date: 2026-10-11$")
        self.assertIn("Enforce on artifacts, not prompts", text)
        self.assertIn("plugins/harness/", text)  # ADR-0001 is history: it keeps the pre-rename layout
        self.assertIn("Principles", text)
        self.assertIn("Architecture", text)


class CiWorkflowTests(unittest.TestCase):
    """REPO-2 and ADR-0074, checked on the text because the workflow is YAML and stdlib has no parser."""

    def setUp(self):
        self.text = read(".github/workflows/ci.yml")

    def test_triggers_are_push_to_trunk_and_dispatch_only(self):
        self.assertRegex(self.text, r"branches: \[develop, main\]|branches: \[main, develop\]")
        self.assertIn("workflow_dispatch:", self.text)
        for banned in ("pull_request", "schedule:", "pull_request_target"):
            self.assertNotIn(banned, self.text)

    def test_concurrency_group_and_read_only_permissions(self):
        self.assertIn("concurrency:", self.text)
        self.assertIn("cancel-in-progress: true", self.text)
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read$")

    def test_every_job_has_a_timeout(self):
        self.assertEqual(len(re.findall(r"(?m)^    runs-on:", self.text)),
                         len(re.findall(r"(?m)^    timeout-minutes: \d+$", self.text)))

    def test_jobs_tests_and_standards(self):
        self.assertRegex(self.text, r"(?m)^  tests:$")
        self.assertRegex(self.text, r"(?m)^  standards:$")
        self.assertIn('python -m unittest discover -s tests -p "test_*.py"', self.text)
        self.assertIn("python scripts/check_content_standards.py", self.text)

    def test_matrix(self):
        for needle in ('"3.10"', '"3.13"', "ubuntu-latest", "windows-latest"):
            self.assertIn(needle, self.text)

    def test_actions_pinned_to_full_sha_with_tag_comment(self):
        uses = re.findall(r"(?m)^\s*- uses: (\S+)(.*)$", self.text)
        self.assertGreaterEqual(len(uses), 2)
        for ref, rest in uses:
            self.assertRegex(ref, r"@[0-9a-f]{40}$", ref)
            self.assertRegex(rest, r"#\s*v\d", ref)

    def test_no_training_stack(self):
        for banned in ("torch", "tensorflow", "requirements-precompute"):
            self.assertNotIn(banned, self.text)


if __name__ == "__main__":
    unittest.main()
