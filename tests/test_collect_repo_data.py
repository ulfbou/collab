import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "collect-repo-data.py"


class CollectRepoDataTests(unittest.TestCase):
    def make_repo(self):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "t@invalid"], cwd=root, check=True)
        subprocess.run(
            ["git", "remote", "add", "origin", "https://github.com/example/repo.git"],
            cwd=root,
            check=True,
        )
        (root / "x").write_text("x\n")
        subprocess.run(["git", "add", "x"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)
        return directory, root

    def test_repo_flag_selects_repository_and_local_only_skips_hosted(self):
        directory, root = self.make_repo()
        self.addCleanup(directory.cleanup)
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "-r", str(root), "-l"],
            cwd=SCRIPT.parent,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
        )
        result = json.loads(completed.stdout)
        self.assertEqual(str(root.resolve()), result["local"]["root"])
        self.assertIsNone(result["hosted"])

    def test_local_only_rejects_hosted_query(self):
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "-l", "-k", "pr", "-v", "1"],
            cwd=SCRIPT.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.assertEqual(2, completed.returncode)
        self.assertIn("cannot be used with --local-only", completed.stderr)


if __name__ == "__main__":
    unittest.main()
