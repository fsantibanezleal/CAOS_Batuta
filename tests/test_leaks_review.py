"""Reproductions of the Opus review findings on `leaks scan` (F-11, F-16, F-26). Samples are assembled at run time."""
import pathlib
import unittest

from test_leaks_scan import Base, TOKENS, USER_PATHS, mail


class F11Encodings(Base):
    def test_a_utf16_file_is_decoded_before_the_binary_test(self):
        for encoding in ("utf-16", "utf-16-le", "utf-16-be"):
            with self.subTest(encoding=encoding):
                path = self.root / f"u16-{encoding}.txt"
                data = f"line\nkey = {TOKENS['github']}\n".encode(encoding)
                if encoding == "utf-16-le":
                    data = b"\xff\xfe" + data
                if encoding == "utf-16-be":
                    data = b"\xfe\xff" + data
                path.write_bytes(data)
                code, out = self.scan()
                self.assertEqual(code, 1, out)
                self.assertIn(f"u16-{encoding}.txt:2", out)
                path.unlink()

    def test_a_utf16_file_without_a_bom_is_detected_by_the_nul_pattern(self):
        (self.root / "nobom.txt").write_bytes(f"a\nkey = {TOKENS['aws']}\n".encode("utf-16-le"))
        code, out = self.scan()
        self.assertEqual(code, 1, out)
        self.assertIn("nobom.txt:2", out)

    def test_a_large_file_is_scanned_to_its_last_line(self):
        filler = ("x" * 99 + "\n") * 21000
        (self.root / "big.txt").write_text(filler + f"key = {TOKENS['github']}\n", encoding="utf-8")
        self.assertGreater((self.root / "big.txt").stat().st_size, 2_000_000)
        code, out = self.scan()
        self.assertEqual(code, 1, out)
        self.assertIn("big.txt:21001", out)

    def test_a_token_across_the_chunk_boundary_is_found(self):
        size = 1024 * 1024
        head = "y" * (size - 20)
        (self.root / "edge.txt").write_text(head + TOKENS["github"] + "\n", encoding="utf-8")
        code, out = self.scan()
        self.assertEqual(code, 1, out)

    def test_a_single_huge_line_is_scanned(self):
        (self.root / "line.txt").write_text("z" * 3_000_000 + " " + TOKENS["aws"], encoding="utf-8")
        self.assertEqual(self.scan()[0], 1)

    def test_a_binary_file_is_not_skipped_silently(self):
        (self.root / "blob.bin").write_bytes(b"\x00\x01\x02" + TOKENS["aws"].encode() + b"\xff\xfe\x00")
        code, out = self.scan()
        self.assertEqual(code, 1, out)
        (self.root / "blob.bin").write_bytes(b"\x00\x01\x02\xff\xfe\x00 nothing here")
        self.assertEqual(self.scan()[0], 0)

    def test_the_summary_counts_the_files_scanned(self):
        self.put("a.txt", "hello\n")
        code, out = self.scan()
        self.assertEqual(code, 0)
        self.assertIn("1 file", out)


class F16NamesAndSpellings(Base):
    def test_file_names_are_scanned(self):
        self.put(f"keys/{TOKENS['github']}.txt", "x\n")
        code, out = self.scan()
        self.assertEqual(code, 1, out)
        self.assertIn("keys/", out)
        self.assertNotIn(TOKENS["github"], out)

    def test_a_deny_list_term_in_a_file_name_is_found(self):
        self.put("docs/project-zebra-notes.txt", "x\n")
        deny = self.outside / "deny.txt"
        deny.write_text("project-zebra\n", encoding="utf-8")
        code, out = self.scan("--deny-list", str(deny))
        self.assertEqual(code, 1, out)
        self.assertIn("deny-list", out)
        self.assertNotIn("zebra", out.lower())

    def test_deny_terms_and_lines_are_normalized(self):
        self.put("a.txt", "see project\u200b-zebra here\n")
        self.put("b.txt", "see \uff50\uff52\uff4f\uff4a\uff45\uff43\uff54-zebra here\n")
        deny = self.outside / "deny.txt"
        deny.write_text("project-zebra\n", encoding="utf-8")
        code, out = self.scan("--deny-list", str(deny))
        self.assertEqual(code, 1)
        self.assertIn("a.txt:1", out)
        self.assertIn("b.txt:1", out)

    def test_more_user_path_spellings(self):
        cases = {
            "json": "C:" + "\\\\" + "Users" + "\\\\" + "someone" + "\\\\" + "x",
            "lower": "c:" + "/" + "users" + "/" + "someone/x",
            "double-slash": "C:" + "\\" + "\\" + "Users" + "\\" + "\\" + "someone",
            "home-end": "cd /" + "home" + "/someone",
            "mac-end": "cd /" + "Users" + "/someone",
        }
        for name, value in cases.items():
            with self.subTest(name=name):
                self.put("p.txt", f"{value}\n")
                code, out = self.scan()
                self.assertEqual(code, 1, out)
                self.assertIn("user path", out)

    def test_placeholders_still_pass(self):
        self.put("p.md", "use /home/<name> or /Users/<name> or C:/Users/<name>\n")
        self.assertEqual(self.scan()[0], 0)


class F26Families(Base):
    SAMPLES = {
        "pypi": "pypi" + "-AgEIcHlwaS5vcmc" + "A" * 60,
        "npm": "npm" + "_" + "a1B2c3" * 6,
        "huggingface": "hf" + "_" + "AbCdEfGhIj" * 4,
        "gitlab": "glpat" + "-" + "a1B2c3D4e5F6g7H8i9J0",
    }

    def test_each_family_is_found(self):
        for name, token in self.SAMPLES.items():
            with self.subTest(name=name):
                self.put("conf.txt", f"line\nkey = {token}\n")
                code, out = self.scan()
                self.assertEqual(code, 1, out)
                self.assertIn("conf.txt:2", out)
                self.assertNotIn(token, out)

    def test_the_marker_never_hides_a_token_family_hit(self):
        for family, token in {**TOKENS, **self.SAMPLES}.items():
            with self.subTest(family=family):
                self.put("m.txt", f"k = {token}  # batuta-leaks: ignore\n")
                self.assertEqual(self.scan()[0], 1, family)

    def test_the_marker_still_skips_path_email_and_deny_hits(self):
        deny = self.outside / "deny.txt"
        deny.write_text("project-zebra\n", encoding="utf-8")
        self.put("m.txt", f"{USER_PATHS['linux']} {mail('a', 'corp-domain.dev')} project-zebra  # batuta-leaks: ignore\n")
        self.assertEqual(self.scan("--deny-list", str(deny))[0], 0)

    def test_short_lookalikes_still_pass(self):
        self.put("a.txt", "hf_short npm_x glpat-short pypi-short\n")
        self.assertEqual(self.scan()[0], 0)


if __name__ == "__main__":
    unittest.main()
