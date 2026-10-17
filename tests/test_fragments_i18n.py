"""`fragments i18n`: merge `*.csv` dictionary fragments into the dictionary csv, keeping the header, the line endings
and every existing row; refuse duplicate keys. Dry run by default."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_device_support import run  # noqa: E402


class I18nTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        self.csv = self.root / "dict.csv"
        self.frag = self.root / "i18n"
        self.frag.mkdir()

    def write_dict(self, text):
        self.csv.write_bytes(text.encode())

    def merge(self, *extra):
        return run("fragments", "i18n", str(self.csv), str(self.frag), *extra)

    def test_sorted_dictionary_gets_rows_inserted_in_order(self):
        self.write_dict("key,en,es\na.one,One,Uno\nc.three,Three,Tres\ne.five,Five,Cinco\n")
        (self.frag / "u1.csv").write_text("key,en,es\nd.four,Four,Cuatro\n", encoding="utf-8")
        (self.frag / "u2.csv").write_text("b.two,Two,Dos\n", encoding="utf-8")
        code, out, _ = self.merge("--apply")
        self.assertEqual(code, 0, out)
        keys = [line.split(",")[0] for line in self.csv.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(keys, ["key", "a.one", "b.two", "c.three", "d.four", "e.five"])
        self.assertEqual(list(self.frag.glob("*.csv")), [])

    def test_unsorted_dictionary_keeps_order_and_appends(self):
        base = "key,en\nz.last,Z\na.first,A\n"
        self.write_dict(base)
        (self.frag / "u1.csv").write_text("m.mid,M\n", encoding="utf-8")
        self.merge("--apply")
        self.assertEqual(self.csv.read_text(encoding="utf-8"), base + "m.mid,M\n")

    def test_existing_rows_are_byte_identical(self):
        self.write_dict('key,en\na,"Hello, ""world"""\nc,Multi\n')
        (self.frag / "u1.csv").write_text("b,B\n", encoding="utf-8")
        self.merge("--apply")
        self.assertEqual(self.csv.read_text(encoding="utf-8"), 'key,en\na,"Hello, ""world"""\nb,B\nc,Multi\n')

    def test_quoted_multiline_row_stays_whole(self):
        self.write_dict('key,en\na,"line1\nline2"\nc,C\n')
        (self.frag / "u1.csv").write_text("b,B\n", encoding="utf-8")
        self.merge("--apply")
        self.assertEqual(self.csv.read_text(encoding="utf-8"), 'key,en\na,"line1\nline2"\nb,B\nc,C\n')

    def test_crlf_and_no_trailing_newline_preserved(self):
        self.write_dict("key,en\r\na,A\r\nc,C")
        (self.frag / "u1.csv").write_text("b,B\n", encoding="utf-8")
        self.merge("--apply")
        self.assertEqual(self.csv.read_bytes(), b"key,en\r\na,A\r\nb,B\r\nc,C")

    def test_duplicate_key_against_the_dictionary_is_refused_with_the_list(self):
        base = "key,en\na,A\nc,C\n"
        self.write_dict(base)
        (self.frag / "u1.csv").write_text("a,Again\nb,B\n", encoding="utf-8")
        code, out, _ = self.merge("--apply")
        self.assertEqual(code, 1)
        self.assertRegex(out, r"REFUSED .*duplicate")
        self.assertIn("u1.csv", out)
        self.assertEqual(self.csv.read_text(encoding="utf-8"), base)
        self.assertTrue((self.frag / "u1.csv").exists())

    def test_duplicate_key_between_fragments_is_refused(self):
        self.write_dict("key,en\na,A\n")
        (self.frag / "u1.csv").write_text("b,B1\n", encoding="utf-8")
        (self.frag / "u2.csv").write_text("b,B2\n", encoding="utf-8")
        code, out, _ = self.merge("--apply")
        self.assertEqual(code, 1)
        self.assertIn("u1.csv", out)
        self.assertIn("u2.csv", out)
        self.assertEqual(self.csv.read_text(encoding="utf-8"), "key,en\na,A\n")

    def test_dry_run_writes_nothing(self):
        base = "key,en\na,A\n"
        self.write_dict(base)
        (self.frag / "u1.csv").write_text("b,B\n", encoding="utf-8")
        code, out, _ = self.merge()
        self.assertEqual(code, 0, out)
        self.assertIn("MERGED u1.csv: b,B", out)
        self.assertEqual(self.csv.read_text(encoding="utf-8"), base)
        self.assertTrue((self.frag / "u1.csv").exists())

    def test_fragment_header_mismatch_is_refused(self):
        self.write_dict("key,en\na,A\n")
        (self.frag / "u1.csv").write_text("key,fr\nb,B\n", encoding="utf-8")
        code, out, _ = self.merge("--apply")
        self.assertEqual(code, 1)
        self.assertIn("header", out)

    def test_no_fragments_is_ok_and_a_missing_dictionary_is_refused(self):
        self.write_dict("key,en\na,A\n")
        code, out, _ = self.merge()
        self.assertEqual(code, 0)
        self.assertIn("no fragments", out)
        self.csv.unlink()
        (self.frag / "u1.csv").write_text("b,B\n", encoding="utf-8")
        code, out, _ = self.merge()
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
