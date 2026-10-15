"""`leaks scan`: user paths, e-mail addresses, token patterns and an optional private deny-list kept outside the repo.

Every secret-looking sample is assembled at run time, so this file never contains one and the repository scans clean."""
import contextlib
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "batuta"
sys.path.insert(0, str(PLUGIN / "scripts"))

from batuta_lib.areas import leaks  # noqa: E402

A = "A"
TOKENS = {
    "github": "gh" + "p_" + "a1B2" * 9,
    "github-fine": "github" + "_pat_" + "x" * 60,
    "anthropic": "sk" + "-ant-" + "api03-" + "Zz9" * 12,
    "openai": "sk" + "-proj-" + "Ab1" * 14,
    "aws": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "private-key": "-----" + "BEGIN RSA PRIVATE" + " KEY-----",
    "slack": "xo" + "xb-" + "1234567890-abcdefghij",
    "google": "AI" + "za" + "Sy" + "A" * 33,
}
USER_PATHS = {
    "windows": "C:" + "\\" + "Users" + "\\" + "someone" + "\\" + "file.txt",
    "windows-slash": "C:" + "/" + "Users" + "/" + "someone/x",
    "linux": "/" + "home" + "/" + "someone" + "/x",
    "mac": "/" + "Users" + "/" + "someone" + "/x",
}


def mail(user, domain):
    return f"{user}@{domain}"  # assembled at run time: this file holds no address literal


def call(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = leaks.main(list(argv))
    return code, out.getvalue()


def git(root, *args):
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env, check=True)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = pathlib.Path(self.tmp.name)
        self.root = base / "repo"
        self.root.mkdir()
        self.outside = base / "outside"
        self.outside.mkdir()
        git(self.root, "init", "-q")

    def put(self, rel, text, track=True):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        if track:
            git(self.root, "add", rel)
        return path

    def scan(self, *extra):
        return call("scan", "--root", str(self.root), *extra)


class ModuleLayout(unittest.TestCase):
    def test_module_contract(self):
        self.assertEqual(leaks.AREA, "leaks")
        self.assertTrue(leaks.HELP)
        import argparse
        parser = argparse.ArgumentParser()
        subs = parser.add_subparsers(dest="verb")
        leaks.register(subs)
        self.assertEqual(set(subs.choices), {"scan"})


class Tokens(Base):
    def test_every_token_family_is_found_with_file_and_line(self):
        for name, token in TOKENS.items():
            with self.subTest(name=name):
                self.put("src/conf.txt", f"line one\nkey = {token}\n")
                code, out = self.scan()
                self.assertEqual(code, 1, out)
                self.assertIn("src/conf.txt:2", out)
                self.assertNotIn(token, out)  # the output never echoes the secret

    def test_clean_content_passes(self):
        self.put("README.md", "Plain text. Version 1.2.3. sk-learn is a library.\n")
        self.put("src/a.py", "token = os.environ['TOKEN']\nprefix = 'sk-'\n")
        code, out = self.scan()
        self.assertEqual(code, 0, out)
        self.assertIn("OK", out)

    def test_short_lookalikes_are_not_tokens(self):
        self.put("a.txt", "ghp_short\nsk-ant-x\nAKIA123\n")
        self.assertEqual(self.scan()[0], 0)

    def test_the_inline_marker_never_hides_a_token(self):
        self.put("a.txt", f"x = {TOKENS['github']}  # batuta-leaks: ignore\n")
        self.assertEqual(self.scan()[0], 1)


class UserPaths(Base):
    def test_each_spelling_is_found(self):
        for name, value in USER_PATHS.items():
            with self.subTest(name=name):
                self.put("doc.txt", f"see {value}\n")
                code, out = self.scan()
                self.assertEqual(code, 1, out)
                self.assertIn("doc.txt:1", out)
                self.assertIn("user path", out)

    def test_placeholders_pass(self):
        self.put("doc.md", "use /home/<name>/x or /Users/<name>/y\n")
        self.assertEqual(self.scan()[0], 0)


class Emails(Base):
    def test_an_address_is_found(self):
        self.put("a.txt", f"mail {mail('someone', 'corp-domain.dev')} please\n")
        code, out = self.scan()
        self.assertEqual(code, 1)
        self.assertIn("a.txt:1", out)
        self.assertIn("e-mail", out)

    def test_the_default_allow_list(self):
        self.put("a.txt", "noreply@anthropic.com\nme@example.com\nx@users.noreply.github.com\ny@example.org\n")
        self.assertEqual(self.scan()[0], 0)

    def test_contact_addresses_declared_in_security_and_conduct_docs_are_allowed(self):
        self.put("SECURITY.md", f"Write to {mail('owner', 'corp-domain.dev')}\n")
        self.put("docs/x.txt", f"Contact {mail('owner', 'corp-domain.dev')}\n")
        self.assertEqual(self.scan()[0], 0)

    def test_allow_email_option_and_config(self):
        self.put("a.txt", f"{mail('dev', 'corp-domain.dev')}\n{mail('ops', 'other-domain.dev')}\n")
        code, out = self.scan("--allow-email", mail('dev', 'corp-domain.dev'))
        self.assertEqual(code, 1)
        self.assertIn("a.txt:2", out)
        self.assertNotIn("a.txt:1", out)
        code, out = self.scan("--allow-email", "*@corp-domain.dev", "--allow-email", "*@other-domain.dev")
        self.assertEqual(code, 0, out)

    def test_decorator_and_scoped_package_names_are_not_emails(self):
        self.put("a.js", "import x from '@scope/pkg'; @decorator(arg)\nuser@host\n")
        self.assertEqual(self.scan()[0], 0)


class DenyList(Base):
    def deny(self, text, name="deny.txt"):
        path = self.outside / name
        path.write_text(text, encoding="utf-8")
        return str(path)

    def test_a_listed_term_is_found_case_insensitively_without_being_echoed(self):
        self.put("a.txt", "this mentions Project-Zebra here\n")
        code, out = self.scan("--deny-list", self.deny("# private terms\n\nproject-zebra\nother-term\n"))
        self.assertEqual(code, 1)
        self.assertIn("a.txt:1", out)
        self.assertIn("deny-list", out)
        self.assertNotIn("zebra", out.lower())

    def test_no_hit_when_no_term_appears(self):
        self.put("a.txt", "nothing special\n")
        self.assertEqual(self.scan("--deny-list", self.deny("project-zebra\n"))[0], 0)

    def test_a_deny_list_inside_the_repository_is_refused(self):
        path = self.put("private-terms.txt", "project-zebra\n")
        code, out = self.scan("--deny-list", str(path))
        self.assertEqual(code, 1)
        self.assertIn("REFUSED", out)
        self.assertIn("outside", out)

    def test_a_deny_list_given_by_a_relative_path_into_the_repo_is_refused(self):
        self.put("terms/list.txt", "x\n")
        code, out = self.scan("--deny-list", str(self.root / "terms" / ".." / "terms" / "list.txt"))
        self.assertEqual(code, 1)
        self.assertIn("REFUSED", out)

    def test_a_missing_deny_list_is_a_failure(self):
        code, out = self.scan("--deny-list", str(self.outside / "none.txt"))
        self.assertEqual(code, 1)
        self.assertIn("FAIL", out)

    def test_the_deny_list_file_is_never_scanned_as_content_or_shipped(self):
        # a deny list that sits outside never appears in the scanned set; one tracked inside is refused (above)
        self.put("a.txt", "clean\n")
        self.assertEqual(self.scan("--deny-list", self.deny("project-zebra\n"))[0], 0)

    def test_the_deny_list_from_the_environment(self):
        self.put("a.txt", "project-zebra\n")
        path = self.deny("project-zebra\n")
        with unittest.mock.patch.dict(os.environ, {"BATUTA_LEAKS_DENY_LIST": path}):
            self.assertEqual(self.scan()[0], 1)


class Scope(Base):
    def test_untracked_files_that_are_not_ignored_are_scanned(self):
        self.put("planted.txt", f"k = {TOKENS['aws']}\n", track=False)
        self.assertEqual(self.scan()[0], 1)

    def test_ignored_files_are_not_scanned(self):
        self.put(".gitignore", "secret.txt\n")
        self.put("secret.txt", f"k = {TOKENS['aws']}\n", track=False)
        self.assertEqual(self.scan()[0], 0)

    def test_binary_files_are_searched_for_tokens(self):
        path = self.root / "blob.bin"
        path.write_bytes(b"\x00\x01\x02" + TOKENS["aws"].encode() + b"\xff\xfe")
        git(self.root, "add", "blob.bin")
        self.assertEqual(self.scan()[0], 1)

    def test_a_folder_that_is_not_a_git_repository_is_walked(self):
        plain = self.outside / "plain"
        plain.mkdir()
        (plain / "a.txt").write_text(f"k = {TOKENS['aws']}\n", encoding="utf-8")
        (plain / ".git").mkdir()  # a stray folder named like git must not hide the file
        code, out = call("scan", "--root", str(plain))
        self.assertEqual(code, 1, out)

    def test_json_output_is_the_c20_object(self):
        self.put("a.txt", f"k = {TOKENS['aws']}\n")
        code, out = self.scan("--json")
        doc = json.loads(out)
        self.assertEqual(doc["area"], "leaks")
        self.assertEqual(doc["exit_code"], 1)
        self.assertEqual(doc["items"][0]["tag"], "FAIL")

    def test_several_hits_are_all_listed(self):
        self.put("a.txt", f"{TOKENS['aws']}\n{USER_PATHS['linux']}\nmail {mail('x', 'corp-domain.dev')}\n")
        code, out = self.scan()
        self.assertEqual(code, 1)
        for line in ("a.txt:1", "a.txt:2", "a.txt:3"):
            self.assertIn(line, out)


class Repository(unittest.TestCase):
    def test_this_repository_scans_clean(self):
        code, out = call("scan", "--root", str(ROOT))
        self.assertEqual(code, 0, out)


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()
