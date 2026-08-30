from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DX = ROOT / "dx.py"
COMPAT = ROOT / "collab-dx-pack.py"


class DxCliCompatibilityTests(unittest.TestCase):
    def run_dx(self, *args: str):
        return subprocess.run([sys.executable, str(DX), *args], cwd=ROOT, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)

    def test_top_level_help(self):
        result = self.run_dx("--help")
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("Commands:", result.stdout)

    def test_pack_inspect_and_unpack(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); source = base / "source"; destination = base / "destination"
            source.mkdir(); (source / "README.md").write_bytes(b"hello\n")
            (source / "nested").mkdir(); (source / "nested" / "data.bin").write_bytes(b"\x00\xff\x01")
            carrier = base / "sample.dx.txt"
            packed = self.run_dx("pack", str(source), str(carrier))
            self.assertEqual(0, packed.returncode, packed.stderr)
            listed = self.run_dx("inspect", str(carrier), "--list")
            self.assertEqual(0, listed.returncode, listed.stderr)
            self.assertEqual(["README.md", "nested/data.bin"], listed.stdout.splitlines())
            unpacked = self.run_dx("unpack", str(carrier), str(destination))
            self.assertEqual(0, unpacked.returncode, unpacked.stderr)
            self.assertEqual(b"hello\n", (destination / "README.md").read_bytes())
            self.assertEqual(b"\x00\xff\x01", (destination / "nested" / "data.bin").read_bytes())

    def test_stdin_inspect_file(self):
        carrier = b'%%DX v1.3.1\n%%FILE path="README.md"\n    hello\n%%ENDBLOCK\n%%END\n'
        result = subprocess.run([sys.executable, str(DX), "inspect", "-", "--file", "README.md"],
                                input=carrier, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        self.assertEqual(0, result.returncode, result.stderr.decode())
        self.assertEqual(b"hello\n", result.stdout)

    def test_existing_explicit_output_is_refused_without_force(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); source = base / "source"; source.mkdir()
            (source / "file.txt").write_text("value\n", encoding="utf-8")
            carrier = base / "existing.dx.txt"; carrier.write_text("occupied\n", encoding="utf-8")
            result = self.run_dx("pack", str(source), str(carrier))
            self.assertNotEqual(0, result.returncode)
            self.assertIn("output already exists", result.stderr)
            self.assertEqual("occupied\n", carrier.read_text(encoding="utf-8"))

    def test_legacy_positional_output_remains_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); source = base / "source"; source.mkdir()
            (source / "file.txt").write_text("value\n", encoding="utf-8")
            carrier = base / "legacy.dx.txt"
            result = self.run_dx("pack", str(source), str(carrier))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(carrier.is_file())

    def test_compatibility_entry_point_accepts_out(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary); source = base / "source"; source.mkdir()
            (source / "file.txt").write_text("value\n", encoding="utf-8")
            carrier = base / "compat.dx.txt"
            result = subprocess.run([sys.executable, str(COMPAT), "--out", str(carrier), str(source)],
                                    cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(carrier.is_file())


if __name__ == "__main__":
    unittest.main()
