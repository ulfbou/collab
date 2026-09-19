from __future__ import annotations

import base64
import importlib.util
import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dx_under_test", ROOT / "dx.py")
assert SPEC and SPEC.loader
DX = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = DX
SPEC.loader.exec_module(DX)


class DxCodecTests(unittest.TestCase):
    def parse(self, text: str):
        return DX.parse(io.StringIO(text))

    def test_parses_text_readonly_note_and_version(self):
        version, entries, notes = self.parse(
            '%%DX v1.3.1\n%%NOTE kind="tree"\n    project/\n%%ENDBLOCK\n'
            '%%FILE path="README.md" readonly="true"\n    hello\n%%ENDBLOCK\n%%END\n'
        )
        self.assertEqual("v1.3.1", version)
        self.assertEqual(1, notes)
        self.assertEqual(b"hello\n", entries[0].data)
        self.assertTrue(entries[0].readonly)

    def test_rejects_headerless_footerless_carrier(self):
        with self.assertRaisesRegex(
            DX.InvalidCarrierError,
            "missing %%DX header",
        ):
            self.parse(
                '%%FILE path="src/example.py"\n'
                '    print("ok")\n'
                '%%ENDBLOCK\n'
            )

    def test_decodes_escaped_directive_content(self):
        _, entries, _ = self.parse(
            '%%DX v1.3.1\n%%FILE path="directives.txt"\n'
            '        %%FILE is content\n        %%END is content\n%%ENDBLOCK\n%%END\n'
        )
        self.assertEqual(b"%%FILE is content\n%%END is content\n", entries[0].data)

    def test_decodes_base64_binary_exactly(self):
        payload = b"\x00\x01binary\xff\n"
        encoded = base64.b64encode(payload).decode("ascii")
        _, entries, _ = self.parse(
            '%%DX v1.3.1\n%%FILE path="fixture.bin" encoding="base64"\n'
            f'    {encoded}\n%%ENDBLOCK\n%%END\n'
        )
        self.assertEqual(payload, entries[0].data)

    def test_encode_entry_round_trips_text_and_directives(self):
        output = io.StringIO()
        data = b"alpha\n%%END\nomega\n"
        self.assertTrue(DX.encode_entry(output, "sample.txt", data, True))
        _, entries, _ = self.parse("%%DX v1.3.1\n" + output.getvalue() + "%%END\n")
        self.assertEqual(data, entries[0].data)
        self.assertTrue(entries[0].readonly)

    def test_encode_entry_round_trips_binary(self):
        output = io.StringIO()
        data = bytes(range(256))
        self.assertTrue(DX.encode_entry(output, "sample.bin", data, False))
        _, entries, _ = self.parse("%%DX v1.3.1\n" + output.getvalue() + "%%END\n")
        self.assertEqual(data, entries[0].data)
        self.assertEqual("base64", entries[0].encoding)

    def test_rejects_duplicate_paths(self):
        with self.assertRaisesRegex(DX.DxError, "duplicate path"):
            self.parse('%%FILE path="same.txt"\n    first\n%%ENDBLOCK\n%%FILE path="same.txt"\n    second\n%%ENDBLOCK\n')

    def test_rejects_unsafe_paths(self):
        for path in ("../escape.txt", "/absolute.txt", "a//b.txt", "./local.txt"):
            with self.subTest(path=path), self.assertRaises(DX.DxError):
                self.parse(f'%%FILE path="{path}"\n    value\n%%ENDBLOCK\n')

    def test_rejects_unsupported_encoding(self):
        with self.assertRaisesRegex(DX.DxError, "unsupported encoding"):
            self.parse('%%FILE path="sample.txt" encoding="rot13"\n    value\n%%ENDBLOCK\n')

    def test_rejects_unterminated_file_block(self):
        with self.assertRaisesRegex(DX.DxError, "unterminated file block"):
            self.parse('%%FILE path="sample.txt"\n    value\n')

    def test_wildmatch_pattern_contract(self):
        suffix = DX._validate_pattern("*.py", "include", 0, "include")
        directory = DX._validate_pattern("src/", "include", 0, "include")
        unrelated = DX._validate_pattern("tests/", "include", 0, "include")
        recursive = DX._validate_pattern("src/**", "include", 0, "include")
        self.assertTrue(DX.pattern_matches("src/tool.py", suffix))
        self.assertTrue(DX.pattern_matches("src/tool.py", directory))
        self.assertFalse(DX.pattern_matches("src/tool.py", unrelated))
        self.assertTrue(DX.pattern_matches("src/tool.py", recursive))


if __name__ == "__main__":
    unittest.main()
