from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

import jsonschema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "schemas/controlled-roadmap.schema.json"
ROADMAP = ROOT / "roadmap/evidence-bound-collaboration.json"
FIXTURES = ROOT / "tests/fixtures/controlled-roadmap"

MUTATION_ISSUES = {f"issue-{number}" for number in range(76, 83)}
COMPLETED_FOUNDATIONS = {"issue-60", "issue-61", "issue-62", "issue-85"}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def diagnostic(code, path, message):
    return {"code": code, "path": path, "message": message}


def validate_semantics(value):
    findings = []
    items = value.get("items", [])
    item_by_id = {}
    for index, item in enumerate(items):
        identifier = item.get("id")
        if identifier in item_by_id:
            findings.append(diagnostic(
                "duplicate_id", f"$.items[{index}].id",
                f"Duplicate roadmap item {identifier!r}",
            ))
        else:
            item_by_id[identifier] = item

    capabilities = value.get("capabilities", [])
    capability_ids = set()
    for index, capability in enumerate(capabilities):
        identifier = capability.get("id")
        if identifier in capability_ids:
            findings.append(diagnostic(
                "duplicate_owner", f"$.capabilities[{index}].id",
                f"Capability {identifier!r} has competing primary ownership",
            ))
        capability_ids.add(identifier)

    for index, item in enumerate(items):
        for dep_index, dependency in enumerate(item.get("dependencies", [])):
            if dependency not in item_by_id:
                findings.append(diagnostic(
                    "missing_dependency",
                    f"$.items[{index}].dependencies[{dep_index}]",
                    f"Unknown dependency {dependency!r}",
                ))

    visiting = set()
    visited = set()

    def visit(identifier, trail):
        if identifier in visiting:
            findings.append(diagnostic(
                "dependency_cycle", "$.items",
                "Dependency cycle: " + " -> ".join([*trail, identifier]),
            ))
            return
        if identifier in visited or identifier not in item_by_id:
            return
        visiting.add(identifier)
        for dependency in item_by_id[identifier].get("dependencies", []):
            visit(dependency, [*trail, identifier])
        visiting.remove(identifier)
        visited.add(identifier)

    for identifier in sorted(item_by_id):
        visit(identifier, [])

    for identifier in COMPLETED_FOUNDATIONS:
        item = item_by_id.get(identifier)
        if item and (
            item.get("state") != "COMPLETED"
            or item.get("implementation") != "implemented"
        ):
            findings.append(diagnostic(
                "completed_foundation_weakened",
                f"$.items[{identifier!r}]",
                f"{identifier} must remain completed and implemented",
            ))

    for index, specification in enumerate(value.get("specifications", [])):
        if specification.get("state") == "PROPOSED" and specification.get(
            "implementation"
        ) == "implemented":
            findings.append(diagnostic(
                "proposal_as_implemented",
                f"$.specifications[{index}]",
                "A proposed specification cannot be represented as implemented",
            ))

    issue_63 = item_by_id.get("issue-63", {})
    required_63 = {"issue-61", "issue-62", "issue-85"}
    if not required_63.issubset(set(issue_63.get("dependencies", []))):
        findings.append(diagnostic(
            "issue_63_dependencies",
            "$.items[issue-63].dependencies",
            "Issue #63 must depend on Issues #61, #62, and #85",
        ))

    for number in range(64, 83):
        identifier = f"issue-{number}"
        predecessor = f"issue-{number - 1}"
        if predecessor not in item_by_id.get(identifier, {}).get("dependencies", []):
            findings.append(diagnostic(
                "sequence_violation",
                f"$.items[{identifier!r}].dependencies",
                f"{identifier} must depend on {predecessor}",
            ))

    for identifier in MUTATION_ISSUES:
        if "issue-73" not in item_by_id.get(identifier, {}).get("dependencies", []):
            findings.append(diagnostic(
                "mutation_before_read_only_gate",
                f"$.items[{identifier!r}].dependencies",
                f"{identifier} must depend on issue-73",
            ))

    gates = {gate.get("id"): gate for gate in value.get("gates", [])}
    harness = gates.get("external-harness", {})
    harness_requirements = set(harness.get("requires", []))
    if harness_requirements != {
        "specification:gitdrift-external-repository-testing:ACCEPTED",
        "issue-73",
    }:
        findings.append(diagnostic(
            "external_harness_gate",
            "$.gates[external-harness].requires",
            "External harness requires accepted specification evidence and issue-73",
        ))

    ordered = gates.get("integration-synchronization-cleanup", {}).get("requires", [])
    if ordered != ["issue-79", "issue-80", "issue-81"]:
        findings.append(diagnostic(
            "responsibility_order",
            "$.gates[integration-synchronization-cleanup].requires",
            "Integration must precede synchronization and cleanup",
        ))

    extraction = set(gates.get("library-extraction", {}).get("requires", []))
    required_adoption = {
        "consumer:ulfbou/collab",
        "consumer:gitdrift-external-harness",
        "consumer:independent",
    }
    if extraction != required_adoption:
        findings.append(diagnostic(
            "extraction_before_adoption",
            "$.gates[library-extraction].requires",
            "Extraction requires Collab, Gitdrift harness, and independent adoption",
        ))

    pending = [
        item["id"]
        for item in items
        if item.get("program") == "collab-core"
        and item.get("state") != "COMPLETED"
        and all(
            item_by_id.get(dep, {}).get("state") == "COMPLETED"
            for dep in item.get("dependencies", [])
        )
    ]
    if value.get("nextImplementationItem") != "issue-63" or pending != ["issue-63"]:
        findings.append(diagnostic(
            "next_implementation_item",
            "$.nextImplementationItem",
            "Issue #63 must be the uniquely derivable next implementation item",
        ))

    return tuple(sorted(findings, key=lambda item: (
        item["path"], item["code"], item["message"]
    )))


class ControlledRoadmapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = load(SCHEMA)
        jsonschema.Draft202012Validator.check_schema(cls.schema)
        cls.validator = jsonschema.Draft202012Validator(
            cls.schema,
            format_checker=jsonschema.FormatChecker(),
        )

    def fixture(self, name):
        return load(FIXTURES / name)

    def structural_errors(self, value):
        return list(self.validator.iter_errors(value))

    def test_authoritative_roadmap_is_structurally_and_semantically_valid(self):
        roadmap = load(ROADMAP)
        self.assertEqual([], self.structural_errors(roadmap))
        self.assertEqual((), validate_semantics(roadmap))

    def test_valid_fixtures(self):
        for name in ("minimal-valid.json", "collab-valid.json"):
            value = self.fixture(name)
            self.assertEqual([], self.structural_errors(value), name)
            self.assertEqual((), validate_semantics(value), name)

    def test_invalid_fixtures_report_expected_diagnostic(self):
        expected = {
            "invalid-cycle.json": "dependency_cycle",
            "invalid-duplicate-owner.json": "duplicate_owner",
            "invalid-missing-dependency.json": "missing_dependency",
            "invalid-proposal-as-completed.json": "proposal_as_implemented",
            "invalid-mutation-before-read-only-gate.json": "mutation_before_read_only_gate",
            "invalid-cleanup-before-synchronization.json": "responsibility_order",
            "invalid-extraction-before-adoption.json": "extraction_before_adoption",
        }
        for name, code in expected.items():
            diagnostics = validate_semantics(self.fixture(name))
            self.assertIn(code, {item["code"] for item in diagnostics}, name)

    def test_diagnostics_are_deterministic(self):
        value = self.fixture("invalid-cycle.json")
        self.assertEqual(validate_semantics(value), validate_semantics(value))

    def test_core_sequence_occurs_once(self):
        roadmap = load(ROADMAP)
        identifiers = [item["id"] for item in roadmap["items"]]
        for number in range(63, 83):
            self.assertEqual(1, identifiers.count(f"issue-{number}"))

    def test_proposed_specifications_remain_unimplemented(self):
        roadmap = load(ROADMAP)
        for specification in roadmap["specifications"]:
            self.assertEqual("PROPOSED", specification["state"])
            self.assertEqual("not-implemented", specification["implementation"])

    def test_documentation_and_json_preserve_same_issue_sequence(self):
        roadmap = load(ROADMAP)
        documentation = (
            ROOT / "docs/roadmap/evidence-bound-collaboration.md"
        ).read_text(encoding="utf-8")
        for number in range(60, 83):
            if number in {63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82}:
                self.assertIn(f"#{number}", documentation)
                self.assertTrue(any(
                    item["id"] == f"issue-{number}" for item in roadmap["items"]
                ))


if __name__ == "__main__":
    unittest.main()
