import json
from pathlib import Path
import tempfile
import unittest

import jsonschema

from collab.repository_manifest import load_repository_manifest, validate_manifest

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/repository-manifest.schema.json"
FIXTURES = ROOT / "tests/fixtures/repository-manifest"

class RepositoryManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def declare(self, value):
        target = self.root / ".repository/manifest.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value), encoding="utf-8")
        return target

    def materialize_complete_paths(self):
        for path in ("src/gitdrift", "tests", "docs/history", "tests/fixtures", "dist"):
            (self.root / path).mkdir(parents=True, exist_ok=True)
        for path in ("docs/architecture.md", "pyproject.toml"):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("fixture\n", encoding="utf-8")

    def test_schema_is_draft_2020_12_and_validates_valid_fixtures(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
        for name in ("minimal-valid.json", "complete-valid.json", "gitdrift-valid.json"):
            self.assertEqual([], list(validator.iter_errors(self.fixture(name))), name)

    def test_schema_rejects_structural_path_and_version_failures(self):
        validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
        for name in ("invalid-structural.json", "invalid-path.json", "invalid-unsupported-schema.json"):
            self.assertTrue(list(validator.iter_errors(self.fixture(name))), name)

    def test_schema_rejects_every_prohibited_path_form(self):
        validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8")))
        base = self.fixture("minimal-valid.json")
        for candidate in ("/absolute", "C:/drive", r"dir\file", "a/../b", "a/./b", "a//b", "nul\u0000byte"):
            value = json.loads(json.dumps(base))
            value["workspace"]["entryPoints"] = [{"id": "bad", "path": candidate}]
            self.assertTrue(list(validator.iter_errors(value)), repr(candidate))

    def test_absent_empty_invalid_and_unavailable_states_are_distinct(self):
        self.assertEqual("not_declared", load_repository_manifest(self.root).status)
        self.declare(self.fixture("minimal-valid.json"))
        result = load_repository_manifest(self.root)
        self.assertEqual("valid", result.status)
        self.assertEqual([], result.declaration["components"])
        self.declare({"schema": "collab/repository-manifest/v1"})
        self.assertEqual("invalid", load_repository_manifest(self.root).status)
        self.assertEqual("unavailable", load_repository_manifest(self.root / "missing").status)

    def test_invalid_json_has_bounded_deterministic_diagnostic(self):
        target = self.declare(self.fixture("minimal-valid.json"))
        target.write_text("{bad", encoding="utf-8")
        result = load_repository_manifest(self.root)
        self.assertEqual("invalid", result.status)
        self.assertEqual("invalid_json", result.diagnostics[0].code)
        self.assertLess(len(result.diagnostics[0].message), 160)

    def test_semantic_validation_detects_duplicates_and_references(self):
        duplicate = validate_manifest(self.fixture("invalid-duplicate-id.json"), self.root)
        self.assertIn("duplicate_id", {item.code for item in duplicate})
        unresolved = validate_manifest(self.fixture("invalid-reference.json"), self.root)
        self.assertEqual({"unresolved_component", "unresolved_version_domain"}, {item.code for item in unresolved})

    def test_semantic_validation_resolves_paths_and_boundaries(self):
        missing = validate_manifest(self.fixture("invalid-authority-path.json"), self.root)
        self.assertEqual(["path_not_found"], [item.code for item in missing])
        contradictory = validate_manifest(self.fixture("invalid-boundary.json"), self.root)
        self.assertEqual(["contradictory_boundary"], [item.code for item in contradictory])

    def test_complete_and_gitdrift_declarations_validate_when_paths_exist(self):
        self.materialize_complete_paths()
        for name in ("complete-valid.json", "gitdrift-valid.json"):
            self.assertEqual((), validate_manifest(self.fixture(name), self.root), name)

    def test_loader_is_read_only(self):
        self.declare(self.fixture("minimal-valid.json"))
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertTrue(load_repository_manifest(self.root).valid)
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(before, after)

    def test_diagnostics_are_deterministic(self):
        value = self.fixture("invalid-reference.json")
        first = [d.as_dict() for d in validate_manifest(value, self.root)]
        second = [d.as_dict() for d in validate_manifest(value, self.root)]
        self.assertEqual(first, second)

if __name__ == "__main__":
    unittest.main()
