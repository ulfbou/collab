from __future__ import annotations
import json, os, tempfile, unittest
from pathlib import Path
from collab.artifacts import canonical_json_bytes, describe_artifact, manifest
from collab.diagnostics import Diagnostic
from collab.filesystem import FilesystemError, atomic_write_bytes
from collab.process import CommandError, run_command
from collab.repository import canonical_github_repository, discover_repository
from collab.validation import ValidationError, require_safe_relative_path, require_sha1

class CoreTests(unittest.TestCase):
    def test_atomic_write_and_nonreplacement(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'out'; atomic_write_bytes(p,b'one'); self.assertEqual(b'one',p.read_bytes())
            with self.assertRaises(FilesystemError): atomic_write_bytes(p,b'two',replace=False)
            self.assertEqual(b'one',p.read_bytes())
    def test_atomic_write_rejects_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); target=root/'target'; target.write_bytes(b'one'); link=root/'link'
            try: link.symlink_to(target)
            except OSError: self.skipTest('symlinks unavailable')
            with self.assertRaises(FilesystemError): atomic_write_bytes(link,b'two')
            self.assertEqual(b'one',target.read_bytes())
    def test_artifact_and_json(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'a';p.write_bytes(b'x');record=describe_artifact(p,display_path='a')
            self.assertEqual(1,record.size); self.assertEqual('a',record.path)
            self.assertEqual(b'{\n  "b": 1\n}\n',canonical_json_bytes({'b':1}))
            self.assertEqual('tool',manifest('tool','1',[record])['producer']['tool'])
    def test_process_success_failure_and_missing(self):
        result=run_command([os.environ.get('PYTHON','python3'),'-c','print("ok")'])
        self.assertEqual(b'ok\n',result.stdout)
        with self.assertRaises(CommandError): run_command([os.environ.get('PYTHON','python3'),'-c','raise SystemExit(7)'])
        with self.assertRaises(CommandError): run_command(['/definitely/missing/collab-command'])
    def test_repository_normalization(self):
        for value in ('ulfbou/collab','https://github.com/ulfbou/collab.git','git@github.com:ulfbou/collab.git','ssh://git@github.com/ulfbou/collab'):
            self.assertEqual('ulfbou/collab',canonical_github_repository(value))
        with self.assertRaises(ValidationError): canonical_github_repository('invalid')
    def test_repository_discovery(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);run_command(['git','init','-q'],cwd=root);run_command(['git','config','user.name','Test'],cwd=root);run_command(['git','config','user.email','test@example.invalid'],cwd=root);run_command(['git','remote','add','origin','https://github.com/example/repo.git'],cwd=root);(root/'x').write_text('x');run_command(['git','add','x'],cwd=root);run_command(['git','commit','-qm','init'],cwd=root)
            identity=discover_repository(root);self.assertEqual(root.resolve(),identity.root);self.assertEqual('example/repo',identity.name_with_owner)
    def test_validation(self):
        self.assertEqual('a/b',require_safe_relative_path('a\\b'))
        for value in ('','../x','/x','a//b','./x'):
            with self.assertRaises(ValidationError): require_safe_relative_path(value)
        self.assertEqual('a'*40,require_sha1('a'*40,'head'))
    def test_diagnostic_rendering(self):
        text=Diagnostic('X','TEST','failed',detail='because',hint='retry').render_text()
        self.assertEqual('ERROR: failed\nDETAIL: because\nHINT: retry',text)

if __name__=='__main__': unittest.main()
