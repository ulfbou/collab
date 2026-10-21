from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import jsonschema

from collab.development_intent import (
    derive_issue_intent,
    derive_operational_intent,
    resolve_authority_set,
)
from collab.repository_manifest import (
    ManifestResult,
    load_repository_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/development-intent"


class DevelopmentIntentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.intent_schema = json.loads(
            (ROOT / "schemas/development-intent.schema.json").read_text(
                encoding="utf-8"
            )
        )
        cls.authority_schema = json.loads(
            (ROOT / "schemas/authority-set.schema.json").read_text(
                encoding="utf-8"
            )
        )
        jsonschema.Draft202012Validator.check_schema(cls.intent_schema)
        jsonschema.Draft202012Validator.check_schema(cls.authority_schema)
        cls.intent_validator = jsonschema.Draft202012Validator(cls.intent_schema)
        cls.authority_validator = jsonschema.Draft202012Validator(
            cls.authority_schema
        )

    def fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def repository(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)

        contract = root / "docs/contracts/development-intent.md"
        contract.parent.mkdir(parents=True)
        contract.write_text("authority v1\n", encoding="utf-8")

        implementation = root / "collab/development_intent.py"
        implementation.parent.mkdir(parents=True)
        implementation.write_text("implementation\n", encoding="utf-8")
        return root

    def declare_manifest(self, root, value):
        target = root / ".repository/manifest.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(value), encoding="utf-8")
        return load_repository_manifest(root)

    def operational_authorization(self, **overrides):
        base = {
            "repository": "ulfbou/collab",
            "authorizationId": "operator-approved-1",
            "accepted": True,
            "objective": "Perform one bounded operation",
            "expectedBoundary": "VERIFY",
            "allowedMutation": False,
            "changedPathScope": [],
            "exclusions": ["no mutation"],
            "acceptanceConditions": ["verification completes"],
            "dependencies": [],
        }
        base.update(overrides)
        return base

    def test_issue_intent_is_derived_and_issue_change_invalidates_identity(self):
        issue = self.fixture("issue-valid.json")
        first = derive_issue_intent(issue)
        second = derive_issue_intent(copy.deepcopy(issue))
        self.assertTrue(first.valid)
        self.assertEqual(first.value, second.value)
        self.intent_validator.validate(first.value)

        changed = copy.deepcopy(issue)
        changed["body"] += " Material change."
        changed_result = derive_issue_intent(changed)
        self.assertNotEqual(
            first.value["source"]["contentIdentity"],
            changed_result.value["source"]["contentIdentity"],
        )
        self.assertNotEqual(
            first.value["intentId"],
            changed_result.value["intentId"],
        )
        self.assertNotIn(issue["body"], json.dumps(first.value))

    def test_missing_and_unknown_issue_values_return_ordered_diagnostics(self):
        result = derive_issue_intent(
            {
                "repository": "bad",
                "number": 0,
                "title": "",
                "body": "",
                "state": "PROPOSED",
                "labels": [None],
                "milestone": {"number": 0, "title": ""},
            }
        )
        self.assertEqual("invalid", result.status)
        self.assertIsNone(result.value)
        rendered = [item.as_dict() for item in result.diagnostics]
        self.assertEqual(
            rendered,
            sorted(
                rendered,
                key=lambda item: (
                    item["path"],
                    item["code"],
                    item["message"],
                ),
            ),
        )
        self.assertIn(
            "unknown_issue_state",
            {item["code"] for item in rendered},
        )

    def test_explicit_operational_intent_requires_accepted_authorization(self):
        result = derive_operational_intent(self.operational_authorization())
        self.assertTrue(result.valid)
        self.intent_validator.validate(result.value)
        rejected = derive_operational_intent(
            self.operational_authorization(accepted=False)
        )
        self.assertEqual(
            ["authorization_not_accepted"],
            [item.code for item in rejected.diagnostics],
        )

    def test_valid_manifest_contributes_candidates_without_overreach(self):
        root = self.repository()
        manifest = self.declare_manifest(
            root,
            self.fixture("manifest-valid.json"),
        )
        result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            required_authority_ids=["development-intent"],
            manifest_result=manifest,
        )
        self.assertTrue(result.valid)
        value = result.value
        self.authority_validator.validate(value)
        self.assertEqual(
            ["development-intent"],
            [item["id"] for item in value["resolvedAuthorities"]],
        )
        authority = value["resolvedAuthorities"][0]
        self.assertEqual(
            "durable-documentation",
            authority["primaryOwner"],
        )
        self.assertEqual(
            "not-established-by-authority-resolution",
            authority["implementationStatus"],
        )
        self.assertEqual(
            "not-established-by-authority-resolution",
            authority["currentStateStatus"],
        )

    def test_material_authority_change_alters_authority_set_id(self):
        root = self.repository()
        manifest = self.declare_manifest(
            root,
            self.fixture("manifest-valid.json"),
        )
        first = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=manifest,
        )
        (root / "docs/contracts/development-intent.md").write_text(
            "authority v2\n",
            encoding="utf-8",
        )
        second = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=manifest,
        )
        self.assertNotEqual(
            first.value["authoritySetId"],
            second.value["authoritySetId"],
        )

    def test_absent_invalid_and_incomplete_manifest_states_remain_explicit(self):
        root = self.repository()
        absent = ManifestResult(
            "not_declared",
            ".repository/manifest.json",
            None,
            (),
        )
        absent_result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            required_authority_ids=["required"],
            manifest_result=absent,
        )
        self.assertEqual("incomplete", absent_result.status)
        self.assertTrue(absent_result.value["absentDeclarations"])
        self.assertEqual([], absent_result.value["declaredAuthorities"])

        invalid = ManifestResult(
            "invalid",
            ".repository/manifest.json",
            None,
            (),
        )
        invalid_result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=invalid,
        )
        self.assertEqual("incomplete", invalid_result.status)
        self.assertTrue(invalid_result.value["invalidDeclarations"])
        self.assertEqual([], invalid_result.value["resolvedAuthorities"])

    def test_conflicting_authority_claims_are_not_silently_selected(self):
        root = self.repository()
        conflict = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            document_declarations=self.fixture("authority-conflict.json"),
        )
        self.assertEqual("conflicted", conflict.status)
        self.assertEqual([], conflict.value["resolvedAuthorities"])
        self.assertEqual(1, len(conflict.value["conflicts"]))
        self.assertIn(
            "authority_conflict",
            {item.code for item in conflict.diagnostics},
        )

    def test_observation_conflict_preserves_provenance(self):
        root = self.repository()
        manifest = self.declare_manifest(
            root,
            self.fixture("manifest-valid.json"),
        )
        conflict = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=manifest,
            observed_documents={
                "docs/contracts/development-intent.md": {
                    "contentIdentity": "sha256:" + ("0" * 64),
                    "source": "CurrentState.observations.selectedFiles",
                }
            },
        )
        self.assertEqual("conflicted", conflict.status)
        self.assertEqual(
            "declaration-observation-conflict",
            conflict.value["conflicts"][0]["kind"],
        )
        self.assertEqual([], conflict.value["resolvedAuthorities"])

    def test_resolution_is_deterministic_and_read_only(self):
        root = self.repository()
        manifest = self.declare_manifest(
            root,
            self.fixture("manifest-valid.json"),
        )
        before = {
            path.relative_to(root): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
        first = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=manifest,
        )
        second = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=manifest,
        )
        after = {
            path.relative_to(root): path.read_bytes()
            for path in root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(first.as_dict(), second.as_dict())
        self.assertEqual(before, after)

    def test_issue_64_obligation_behavior_is_not_implemented(self):
        import collab.development_intent as module

        forbidden = {
            "NormalizedObligation",
            "normalize_obligations",
            "obligation_set_id",
        }
        self.assertTrue(forbidden.isdisjoint(set(dir(module))))

    # -- Batch 2: input-layer status contract and declaration validation -----

    def test_invalid_repository_fails_closed(self):
        root = self.repository()
        bad_repositories = (
            "",
            "ulfbou",
            "ulfbou/",
            "/collab",
            "ulfbou/collab/extra",
            "ulf bou/collab",
            "ulfbou/coll ab",
            "ulfbou\t/collab",
        )
        for bad_repo in bad_repositories:
            with self.subTest(repository=bad_repo):
                result = resolve_authority_set(
                    repository=bad_repo,
                    repository_root=root,
                )
                self.assertEqual("invalid", result.status)
                self.assertIsNone(result.value)
                self.assertFalse(result.valid)
                self.assertTrue(
                    any(item.code == "invalid_repository" for item in result.diagnostics)
                )

    def test_repository_accepts_canonical_owner_name_form(self):
        root = self.repository()
        for good_repo in ("ulfbou/collab", "a/b", "owner-name/name.with.dots"):
            with self.subTest(repository=good_repo):
                result = resolve_authority_set(
                    repository=good_repo,
                    repository_root=root,
                )
                self.assertEqual("resolved", result.status)
                self.authority_validator.validate(result.value)

    def test_structurally_invalid_explicit_declarations_are_recorded(self):
        root = self.repository()
        good = {
            "id": "good",
            "kind": "contract",
            "path": "docs/contracts/development-intent.md",
            "scope": [],
            "readOnly": True,
        }
        cases = (
            ("missing id", {**good, "id": ""}, "invalid_authority_id"),
            ("unknown kind", {**good, "kind": "unrecognized"}, "unknown_authority_kind"),
            ("missing path", {**good, "path": ""}, "invalid_authority_path"),
            ("scope not list", {**good, "scope": "abc"}, "invalid_authority_scope"),
            ("scope item not string", {**good, "scope": [1]}, "invalid_authority_scope"),
            ("scope null", {**good, "scope": None}, "invalid_authority_scope"),
            ("readOnly not bool", {**good, "readOnly": "false"}, "invalid_authority_read_only"),
            ("readOnly null", {**good, "readOnly": None}, "invalid_authority_read_only"),
        )
        for label, item, expected_code in cases:
            with self.subTest(label=label):
                result = resolve_authority_set(
                    repository="ulfbou/collab",
                    repository_root=root,
                    document_declarations=[good, item],
                )
                self.assertEqual("incomplete", result.status)
                self.assertFalse(result.valid)
                self.authority_validator.validate(result.value)
                self.assertEqual(1, len(result.value["invalidDeclarations"]))
                ledger_entry = result.value["invalidDeclarations"][0]
                self.assertEqual("explicit-document", ledger_entry["source"])
                self.assertEqual(1, ledger_entry["index"])
                self.assertIn(expected_code, ledger_entry["codes"])
                self.assertEqual(
                    ["good"],
                    [authority["id"] for authority in result.value["resolvedAuthorities"]],
                )

    def test_non_mapping_explicit_declaration_is_recorded(self):
        root = self.repository()
        result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            document_declarations=["not-a-mapping"],
        )
        self.assertEqual("incomplete", result.status)
        self.assertFalse(result.valid)
        self.authority_validator.validate(result.value)
        self.assertEqual(1, len(result.value["invalidDeclarations"]))
        self.assertIn(
            "invalid_authority_declaration",
            result.value["invalidDeclarations"][0]["codes"],
        )

    # -- Batch 3: identity binding, absence semantics, and I/O hardening -----

    def test_provenance_participates_in_authority_set_identity(self):
        root = self.repository()
        empty_manifest = ManifestResult(
            "valid",
            ".repository/manifest.json",
            {"authorities": []},
            (),
        )
        with_manifest = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=empty_manifest,
        )
        without_manifest = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=None,
        )
        self.assertEqual("resolved", with_manifest.status)
        self.assertEqual("resolved", without_manifest.status)
        self.assertNotEqual(
            with_manifest.value["authoritySetId"],
            without_manifest.value["authoritySetId"],
        )
        self.assertEqual([], without_manifest.value["provenance"])
        self.assertEqual(1, len(with_manifest.value["provenance"]))
        self.assertEqual(
            "repository-manifest-declaration",
            with_manifest.value["provenance"][0]["kind"],
        )

    def test_not_declared_manifest_without_missing_required_stays_resolved(self):
        root = self.repository()
        absent = ManifestResult(
            "not_declared",
            ".repository/manifest.json",
            None,
            (),
        )
        result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=absent,
        )
        self.assertEqual("resolved", result.status)
        self.assertTrue(result.valid)
        self.authority_validator.validate(result.value)
        self.assertEqual([], result.value["absentDeclarations"])
        self.assertEqual(1, len(result.value["provenance"]))
        entry = result.value["provenance"][0]
        self.assertEqual("repository-manifest-declaration", entry["kind"])
        self.assertEqual("not_declared", entry["status"])

    def test_unreadable_authority_content_is_incomplete_evidence(self):
        root = self.repository()
        manifest = self.declare_manifest(
            root,
            self.fixture("manifest-valid.json"),
        )
        with mock.patch.object(
            Path,
            "read_bytes",
            side_effect=PermissionError("denied"),
        ):
            result = resolve_authority_set(
                repository="ulfbou/collab",
                repository_root=root,
                manifest_result=manifest,
            )
        self.assertEqual("incomplete", result.status)
        self.assertFalse(result.valid)
        self.authority_validator.validate(result.value)
        self.assertEqual([], result.value["resolvedAuthorities"])
        self.assertEqual(1, len(result.value["incompleteEvidence"]))
        entry = result.value["incompleteEvidence"][0]
        self.assertEqual("development-intent", entry["authorityId"])
        self.assertEqual("authority-content-unreadable", entry["reason"])
        self.assertEqual("PermissionError", entry["errorClass"])
        self.assertIn(
            "authority_content_unreadable",
            {item.code for item in result.diagnostics},
        )

    # -- Batch 4: remaining coverage, unknown status, path safety -----------

    def test_unknown_manifest_status_fails_closed(self):
        root = self.repository()
        unknown = ManifestResult(
            "archived",
            ".repository/manifest.json",
            None,
            (),
        )
        result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=unknown,
        )
        self.assertEqual("incomplete", result.status)
        self.assertFalse(result.valid)
        self.authority_validator.validate(result.value)
        self.assertEqual([], result.value["resolvedAuthorities"])
        self.assertEqual(1, len(result.value["invalidDeclarations"]))
        entry = result.value["invalidDeclarations"][0]
        self.assertEqual("repository-manifest", entry["source"])
        self.assertEqual("unknown-manifest-status", entry["reason"])
        self.assertEqual("archived", entry["status"])
        self.assertIn(
            "unknown_manifest_status",
            {item.code for item in result.diagnostics},
        )

    def test_duplicate_identical_declarations_are_not_conflicts(self):
        root = self.repository()
        manifest_declaration = {
            "id": "development-intent",
            "kind": "contract",
            "path": "docs/contracts/development-intent.md",
            "scope": ["collab/development_intent.py"],
        }
        manifest = ManifestResult(
            "valid",
            ".repository/manifest.json",
            {"authorities": [manifest_declaration]},
            (),
        )
        result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=manifest,
            document_declarations=[manifest_declaration],
        )
        self.assertEqual("resolved", result.status)
        self.assertTrue(result.valid)
        self.authority_validator.validate(result.value)
        self.assertEqual([], result.value["conflicts"])
        self.assertEqual(
            2, len(result.value["declaredAuthorities"])
        )
        self.assertEqual(1, len(result.value["resolvedAuthorities"]))
        resolved_authority = result.value["resolvedAuthorities"][0]
        self.assertEqual("repository-manifest", resolved_authority["source"])

    def test_explicit_declarations_alone_produce_valid_authority_set(self):
        root = self.repository()
        result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            required_authority_ids=["development-intent"],
            document_declarations=[
                {
                    "id": "development-intent",
                    "kind": "contract",
                    "path": "docs/contracts/development-intent.md",
                    "scope": ["collab/development_intent.py"],
                    "readOnly": True,
                }
            ],
        )
        self.assertEqual("resolved", result.status)
        self.assertTrue(result.valid)
        self.authority_validator.validate(result.value)
        self.assertEqual(1, len(result.value["resolvedAuthorities"]))
        authority = result.value["resolvedAuthorities"][0]
        self.assertEqual("explicit-document", authority["source"])
        self.assertEqual("durable-documentation", authority["primaryOwner"])
        self.assertEqual(1, len(result.value["declaredAuthorities"]))
        self.assertEqual(
            "explicit-document",
            result.value["declaredAuthorities"][0]["source"],
        )

    def test_operational_intent_material_change_alters_identity(self):
        first = derive_operational_intent(self.operational_authorization())
        self.assertTrue(first.valid)

        variants = (
            ("changedPathScope", ["docs/", "collab/"]),
            ("exclusions", ["no mutation", "no release"]),
            ("acceptanceConditions", ["verification completes cleanly"]),
            ("dependencies", ["#63"]),
            ("objective", "Perform a different bounded operation"),
            ("expectedBoundary", "REVIEW"),
        )
        for field, replacement in variants:
            with self.subTest(field=field):
                changed = derive_operational_intent(
                    self.operational_authorization(**{field: replacement})
                )
                self.assertTrue(changed.valid)
                self.assertNotEqual(
                    first.value["intentId"],
                    changed.value["intentId"],
                )

    # -- Batch 5: schema discriminates by sourceKind ------------------------

    def issue_intent_value(self):
        result = derive_issue_intent(self.fixture("issue-valid.json"))
        self.assertTrue(result.valid)
        return result.value

    def operational_intent_value(self):
        result = derive_operational_intent(self.operational_authorization())
        self.assertTrue(result.valid)
        return result.value

    def assert_invalid_against_schema(self, value, message):
        with self.assertRaises(jsonschema.ValidationError, msg=message):
            self.intent_validator.validate(value)

    def test_issue_intent_without_number_fails_schema(self):
        invalid = copy.deepcopy(self.issue_intent_value())
        del invalid["source"]["number"]
        self.assert_invalid_against_schema(
            invalid, "issue intent without source.number must fail schema"
        )

    def test_issue_intent_without_hosted_state_fails_schema(self):
        invalid = copy.deepcopy(self.issue_intent_value())
        del invalid["hostedState"]
        self.assert_invalid_against_schema(
            invalid, "issue intent without hostedState must fail schema"
        )

    def test_issue_intent_with_operational_fields_fails_schema(self):
        for field, value in (
            ("allowedMutation", False),
            ("changedPathScope", []),
            ("exclusions", []),
            ("acceptanceConditions", ["x"]),
            ("dependencies", []),
        ):
            with self.subTest(field=field):
                invalid = copy.deepcopy(self.issue_intent_value())
                invalid[field] = value
                self.assert_invalid_against_schema(
                    invalid,
                    f"issue intent with {field} must fail schema",
                )

    def test_operational_intent_without_authorization_id_fails_schema(self):
        invalid = copy.deepcopy(self.operational_intent_value())
        del invalid["source"]["authorizationId"]
        self.assert_invalid_against_schema(
            invalid,
            "operational intent without source.authorizationId must fail schema",
        )

    def test_operational_intent_without_each_required_field_fails_schema(self):
        for field in (
            "allowedMutation",
            "changedPathScope",
            "exclusions",
            "acceptanceConditions",
            "dependencies",
        ):
            with self.subTest(field=field):
                invalid = copy.deepcopy(self.operational_intent_value())
                del invalid[field]
                self.assert_invalid_against_schema(
                    invalid,
                    f"operational intent without {field} must fail schema",
                )

    def test_operational_intent_with_empty_acceptance_conditions_fails_schema(self):
        invalid = copy.deepcopy(self.operational_intent_value())
        invalid["acceptanceConditions"] = []
        self.assert_invalid_against_schema(
            invalid,
            "operational intent with empty acceptanceConditions must fail schema",
        )

    def test_operational_intent_with_hosted_state_fails_schema(self):
        invalid = copy.deepcopy(self.operational_intent_value())
        invalid["hostedState"] = {
            "state": "OPEN",
            "labels": [],
            "milestone": None,
        }
        self.assert_invalid_against_schema(
            invalid,
            "operational intent with hostedState must fail schema",
        )

    def test_unknown_source_kind_fails_schema(self):
        invalid = copy.deepcopy(self.issue_intent_value())
        invalid["sourceKind"] = "something-else"
        self.assert_invalid_against_schema(
            invalid,
            "unknown sourceKind must fail schema",
        )

    # -- Batch 6: classified authority content and flat diagnostic contract -

    def test_unsafe_authority_path_is_invalid_declaration(self):
        root = self.repository()
        cases = (
            ("parent traversal", "../etc/passwd"),
            ("absolute", "/etc/passwd"),
            ("backslash", "docs\\contracts\\development-intent.md"),
            ("internal traversal", "docs/../collab/development_intent.py"),
            ("dot only", "."),
            ("drive absolute", "C:/outside.md"),
            ("drive relative", "C:outside.md"),
        )
        for label, path in cases:
            with self.subTest(label=label):
                result = resolve_authority_set(
                    repository="ulfbou/collab",
                    repository_root=root,
                    document_declarations=[
                        {
                            "id": "unsafe",
                            "kind": "contract",
                            "path": path,
                            "scope": [],
                            "readOnly": False,
                        }
                    ],
                )
                self.assertEqual("incomplete", result.status)
                self.assertFalse(result.valid)
                self.authority_validator.validate(result.value)
                self.assertEqual([], result.value["resolvedAuthorities"])
                self.assertEqual(1, len(result.value["invalidDeclarations"]))
                entry = result.value["invalidDeclarations"][0]
                self.assertEqual("explicit-document", entry["source"])
                self.assertIn("unsafe_authority_path", entry["codes"])
                self.assertEqual(0, len(result.value["incompleteEvidence"]))
                self.assertIn(
                    "unsafe_authority_path",
                    {item.code for item in result.diagnostics},
                )

    def test_authority_content_missing_is_incomplete_evidence(self):
        root = self.repository()
        result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            document_declarations=[
                {
                    "id": "absent",
                    "kind": "contract",
                    "path": "docs/contracts/missing.md",
                    "scope": [],
                    "readOnly": False,
                }
            ],
        )
        self.assertEqual("incomplete", result.status)
        self.assertFalse(result.valid)
        self.authority_validator.validate(result.value)
        self.assertEqual([], result.value["resolvedAuthorities"])
        self.assertEqual([], result.value["invalidDeclarations"])
        self.assertEqual(1, len(result.value["incompleteEvidence"]))
        entry = result.value["incompleteEvidence"][0]
        self.assertEqual("absent", entry["authorityId"])
        self.assertEqual("authority-content-missing", entry["reason"])
        self.assertIn(
            "authority_content_missing",
            {item.code for item in result.diagnostics},
        )

    def test_authority_content_not_file_is_incomplete_evidence(self):
        root = self.repository()
        result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            document_declarations=[
                {
                    "id": "dir",
                    "kind": "documentation",
                    "path": "docs",
                    "scope": [],
                    "readOnly": False,
                }
            ],
        )
        self.assertEqual("incomplete", result.status)
        self.assertFalse(result.valid)
        self.authority_validator.validate(result.value)
        self.assertEqual([], result.value["resolvedAuthorities"])
        self.assertEqual([], result.value["invalidDeclarations"])
        self.assertEqual(1, len(result.value["incompleteEvidence"]))
        entry = result.value["incompleteEvidence"][0]
        self.assertEqual("dir", entry["authorityId"])
        self.assertEqual("authority-content-not-file", entry["reason"])
        self.assertIn(
            "authority_content_not_file",
            {item.code for item in result.diagnostics},
        )

    def test_manifest_invalid_emits_flat_diagnostic(self):
        root = self.repository()
        result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=ManifestResult(
                "invalid", ".repository/manifest.json", None, ()
            ),
        )
        self.assertEqual("incomplete", result.status)
        self.assertFalse(result.valid)
        self.assertIn(
            "manifest_invalid",
            {item.code for item in result.diagnostics},
        )

    def test_manifest_unavailable_emits_flat_diagnostic(self):
        root = self.repository()
        result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            manifest_result=ManifestResult(
                "unavailable", ".repository/manifest.json", None, ()
            ),
        )
        self.assertEqual("incomplete", result.status)
        self.assertFalse(result.valid)
        self.assertIn(
            "manifest_unavailable",
            {item.code for item in result.diagnostics},
        )

    def test_required_authority_not_declared_emits_flat_diagnostic(self):
        root = self.repository()
        result = resolve_authority_set(
            repository="ulfbou/collab",
            repository_root=root,
            required_authority_ids=["missing-a", "missing-b"],
        )
        self.assertEqual("incomplete", result.status)
        self.assertFalse(result.valid)
        self.assertEqual(2, len(result.value["absentDeclarations"]))
        flat_codes = [item.code for item in result.diagnostics]
        self.assertEqual(2, flat_codes.count("required_authority_not_declared"))

    def test_every_unresolved_result_emits_at_least_one_diagnostic(self):
        root = self.repository()
        scenarios = {
            "manifest_invalid": dict(
                manifest_result=ManifestResult(
                    "invalid", ".repository/manifest.json", None, ()
                ),
            ),
            "manifest_unavailable": dict(
                manifest_result=ManifestResult(
                    "unavailable", ".repository/manifest.json", None, ()
                ),
            ),
            "required_authority_not_declared": dict(
                required_authority_ids=["missing-authority"],
            ),
            "unsafe_authority_path": dict(
                document_declarations=[
                    {
                        "id": "u",
                        "kind": "contract",
                        "path": "../escape",
                        "scope": [],
                        "readOnly": False,
                    }
                ],
            ),
            "authority_content_missing": dict(
                document_declarations=[
                    {
                        "id": "m",
                        "kind": "contract",
                        "path": "docs/contracts/missing.md",
                        "scope": [],
                        "readOnly": False,
                    }
                ],
            ),
            "authority_content_not_file": dict(
                document_declarations=[
                    {
                        "id": "d",
                        "kind": "documentation",
                        "path": "docs",
                        "scope": [],
                        "readOnly": False,
                    }
                ],
            ),
            "unknown_manifest_status": dict(
                manifest_result=ManifestResult(
                    "archived", ".repository/manifest.json", None, ()
                ),
            ),
            "authority_conflict": dict(
                document_declarations=[
                    {
                        "id": "x",
                        "kind": "contract",
                        "path": "docs/contracts/development-intent.md",
                        "scope": [],
                        "readOnly": False,
                    },
                    {
                        "id": "x",
                        "kind": "policy",
                        "path": "collab/development_intent.py",
                        "scope": [],
                        "readOnly": False,
                    },
                ],
            ),
        }
        for label, kwargs in scenarios.items():
            with self.subTest(scenario=label):
                result = resolve_authority_set(
                    repository="ulfbou/collab",
                    repository_root=root,
                    **kwargs,
                )
                self.assertNotEqual("resolved", result.status, label)
                self.assertGreater(
                    len(result.diagnostics),
                    0,
                    f"{label} produced no flat diagnostic",
                )

    # -- Batch 7: input-layer fail-closed and schema-domain consistency -----

    def test_unavailable_repository_root_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            missing_root = base / "does-not-exist"
            file_root = base / "not-a-directory.txt"
            file_root.write_text("not a directory\n", encoding="utf-8")
            scenarios = (
                ("missing", missing_root),
                ("regular file", file_root),
            )
            for label, root in scenarios:
                with self.subTest(label=label):
                    result = resolve_authority_set(
                        repository="ulfbou/collab",
                        repository_root=root,
                    )
                    self.assertEqual("invalid", result.status)
                    self.assertFalse(result.valid)
                    self.assertIsNone(result.value)
                    self.assertIn(
                        "repository_unavailable",
                        {item.code for item in result.diagnostics},
                    )

    def test_operational_intent_rejects_empty_acceptance_conditions(self):
        result = derive_operational_intent(
            self.operational_authorization(acceptanceConditions=[])
        )
        self.assertEqual("invalid", result.status)
        self.assertFalse(result.valid)
        self.assertIsNone(result.value)
        self.assertIn(
            "missing_required",
            {item.code for item in result.diagnostics},
        )


if __name__ == "__main__":
    unittest.main()
