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
            (source / "nested").mkdir(); (source / "nested" / "data.txt").write_bytes(b"nested data\n")
            carrier = base / "sample.dx.txt"
            packed = self.run_dx("pack", str(source), str(carrier))
            self.assertEqual(0, packed.returncode, packed.stderr)
            listed = self.run_dx("inspect", str(carrier), "--list")
            self.assertEqual(0, listed.returncode, listed.stderr)
            self.assertEqual(["README.md", "nested/data.txt"], listed.stdout.splitlines())
            unpacked = self.run_dx("unpack", str(carrier), str(destination))
            self.assertEqual(0, unpacked.returncode, unpacked.stderr)
            self.assertEqual(b"hello\n", (destination / "README.md").read_bytes())
            self.assertEqual(b"nested data\n", (destination / "nested" / "data.txt").read_bytes())

    def test_recursive_pack_honors_gitignore_for_all_output_forms(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            source.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=source, check=True)
            (source / ".gitignore").write_text(
                ".dx/\n*.log\nnested/*\n!nested/keep.txt\n",
                encoding="utf-8",
            )
            (source / "included.txt").write_text("included\n", encoding="utf-8")
            (source / "ignored.log").write_text("ignored\n", encoding="utf-8")
            (source / ".dx").mkdir()
            (source / ".dx" / "old.dx.txt").write_text("old\n", encoding="utf-8")
            (source / "nested").mkdir()
            (source / "nested" / "drop.txt").write_text("drop\n", encoding="utf-8")
            (source / "nested" / "keep.txt").write_text("keep\n", encoding="utf-8")

            carriers = [base / "positional.dx.txt", source / "explicit.dx.txt"]
            commands = [
                ("pack", str(source), str(carriers[0])),
                ("pack", "--root", str(source), "--out", str(carriers[1])),
            ]
            expected = [".gitignore", "included.txt", "nested/keep.txt"]
            for command, carrier in zip(commands, carriers):
                with self.subTest(command=command):
                    packed = self.run_dx(*command)
                    self.assertEqual(0, packed.returncode, packed.stderr)
                    listed = self.run_dx("inspect", str(carrier), "--list")
                    self.assertEqual(0, listed.returncode, listed.stderr)
                    self.assertEqual(expected, listed.stdout.splitlines())

    def test_recursive_pack_excludes_git_metadata_outside_a_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "source"
            (source / ".git" / "objects").mkdir(parents=True)
            (source / ".git" / "config").write_text("metadata\n", encoding="utf-8")
            (source / "file.txt").write_text("value\n", encoding="utf-8")
            carrier = base / "sample.dx.txt"

            packed = self.run_dx("pack", str(source), str(carrier))
            self.assertEqual(0, packed.returncode, packed.stderr)
            listed = self.run_dx("inspect", str(carrier), "--list")
            self.assertEqual(["file.txt"], listed.stdout.splitlines())

    def test_short_aliases_match_long_options_and_extension_filters(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary); source=base/'source'; source.mkdir()
            (source/'keep.py').write_text('python\n',encoding='utf-8')
            (source/'keep.PY').write_text('python upper\n',encoding='utf-8')
            (source/'drop.txt').write_text('text\n',encoding='utf-8')
            short=base/'short.dx.txt'; long=base/'long.dx.txt'
            short_result=self.run_dx('pack',str(source),'-i','*','-e','missing','-X','py','-x','txt','-o',str(short))
            long_result=self.run_dx('pack',str(source),'--include','*','--exclude','missing','--include-extension','.py','--exclude-extension','.txt','--out',str(long))
            self.assertEqual(0,short_result.returncode,short_result.stderr)
            self.assertEqual(0,long_result.returncode,long_result.stderr)
            short_list=self.run_dx('inspect',str(short),'--list')
            long_list=self.run_dx('inspect',str(long),'--list')
            self.assertEqual(['keep.PY','keep.py'],short_list.stdout.splitlines())
            self.assertEqual(short_list.stdout,long_list.stdout)

    def test_dry_run_alias_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary); source=base/'source'; source.mkdir()
            (source/'file.txt').write_text('value\n',encoding='utf-8')
            carrier=base/'planned.dx.txt'
            result=self.run_dx('pack',str(source),'-n','-o',str(carrier))
            self.assertEqual(0,result.returncode,result.stderr)
            self.assertIn('DX carrier plan',result.stdout)
            self.assertIn('No files were written.',result.stdout)
            self.assertFalse(carrier.exists())

    def test_no_argument_shortcut_packs_current_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary); repository=base/'repository'; output=base/'downloads'/'DX'
            repository.mkdir(); subprocess.run(['git','init','-q'],cwd=repository,check=True)
            (repository/'.gitignore').write_text('.dx/\n',encoding='utf-8')
            (repository/'file.txt').write_text('value\n',encoding='utf-8')
            env=dict(__import__('os').environ,DX_DEVICE_DIR=str(output))
            result=subprocess.run([sys.executable,str(DX)],cwd=repository,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
            self.assertEqual(0,result.returncode,result.stderr)
            carrier=output/'dx-carrier-1.dx.txt'
            self.assertTrue(carrier.is_file())
            self.assertIn('DX carrier created:',result.stdout)
            listed=self.run_dx('inspect',str(carrier),'--list')
            self.assertEqual(['.gitignore','file.txt'],listed.stdout.splitlines())

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
