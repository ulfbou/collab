import copy
import json
import unittest
from pathlib import Path
from jsonschema import Draft202012Validator, ValidationError
from collab.boundary_contracts import create_boundary_descriptor, create_state_transition, evaluate_receipt_applicability, issue_receipt

class BoundaryContractTests(unittest.TestCase):
    def setUp(self):
        self.ids = {name: f"sha256:{name}:v1:" + str(index) * 64 for index, name in enumerate(("baseline", "configuration", "validator", "state", "intent", "authority", "obligation", "subject"), 1)}
        self.boundary = create_boundary_descriptor(responsibility="Verify Issue #65 candidate", scope=["schemas", "collab"], identities=self.ids, limitations=[]).value
        self.receipt = issue_receipt(self.boundary, candidate_identity="sha256:candidate:v1:"+"9"*64, mutation_identity="sha256:mutation:v1:"+"8"*64, completion_identity="sha256:completion:v1:"+"7"*64, evidence_identities=["sha256:evidence:v1:"+"6"*64]).value
        self.prior = {"stateIdentity":"sha256:state:v1:"+"5"*64,"captureId":"capture-1","observations":[{"kind":"repository"}]}
        self.schemas = {name: Draft202012Validator(json.loads(Path(f"schemas/{name}.schema.json").read_text())) for name in ("boundary-descriptor","receipt","state-transition")}

    def test_values_are_deterministic_and_schema_valid(self):
        again = create_boundary_descriptor(responsibility="Verify Issue #65 candidate", scope=["collab", "schemas"], identities=dict(reversed(list(self.ids.items()))), limitations=[]).value
        self.assertEqual(self.boundary, again)
        self.schemas["boundary-descriptor"].validate(self.boundary)
        self.schemas["receipt"].validate(self.receipt)

    def test_each_material_boundary_identity_changes_boundary_identity(self):
        for name in self.ids:
            changed = dict(self.ids); changed[name] = "sha256:changed:v1:"+"a"*64
            value = create_boundary_descriptor(responsibility="Verify Issue #65 candidate", scope=["schemas", "collab"], identities=changed).value
            self.assertNotEqual(self.boundary["boundaryId"], value["boundaryId"])

    def test_boundary_requires_exactly_one_responsibility_and_complete_identities(self):
        self.assertFalse(create_boundary_descriptor(responsibility="", scope=["x"], identities=self.ids).valid)
        changed = dict(self.ids); changed.pop("obligation")
        self.assertFalse(create_boundary_descriptor(responsibility="one", scope=["x"], identities=changed).valid)

    def test_receipt_material_binds_scope_baseline_and_applicability_inputs(self):
        self.assertEqual(self.boundary["scope"], self.receipt["scope"])
        self.assertEqual(self.ids["baseline"], self.receipt["applicability"]["baseline"])
        for field, argument in (("candidateIdentity", "candidate_identity"), ("configuration", "configuration_identity"), ("validator", "validator_identity")):
            kwargs={"boundary":self.boundary,"candidate_identity":self.receipt["candidateIdentity"],"configuration_identity":self.ids["configuration"],"validator_identity":self.ids["validator"]}
            kwargs[argument]="sha256:changed:v1:"+"a"*64
            result=evaluate_receipt_applicability(self.receipt, **kwargs)
            self.assertFalse(result.value["applicable"])
            self.assertIn(field, {item["field"] for item in result.value["invalidators"]})

    def test_receipt_inputs_are_not_mutated_and_material_changes_change_identity(self):
        boundary_before=copy.deepcopy(self.boundary); receipt_before=copy.deepcopy(self.receipt)
        evaluate_receipt_applicability(self.receipt,boundary=self.boundary,candidate_identity=self.receipt["candidateIdentity"],configuration_identity=self.ids["configuration"],validator_identity=self.ids["validator"])
        self.assertEqual(boundary_before,self.boundary); self.assertEqual(receipt_before,self.receipt)
        changed=issue_receipt(self.boundary,candidate_identity="sha256:changed:v1:"+"a"*64,mutation_identity=self.receipt["mutationIdentity"],completion_identity=self.receipt["completionIdentity"],evidence_identities=self.receipt["evidenceIdentities"]).value
        self.assertNotEqual(self.receipt["receiptId"],changed["receiptId"])

    def test_transition_preserves_complete_prior_state_and_ledgers(self):
        value=create_state_transition(prior_state=self.prior,boundary=self.boundary,attached_receipt_ids=[self.receipt["receiptId"]],invalidated_receipt_ids=["sha256:receipt:v1:"+"b"*64],proposed_state={"phase":"candidate-complete"}).value
        self.schemas["state-transition"].validate(value)
        self.assertEqual(self.prior,value["priorState"]); self.assertFalse(value["workflowAdvanced"]); self.assertEqual("not-accepted",value["acceptanceState"])

    def test_transition_rejects_overlapping_receipt_ledgers(self):
        rid=self.receipt["receiptId"]
        self.assertFalse(create_state_transition(prior_state=self.prior,boundary=self.boundary,attached_receipt_ids=[rid],invalidated_receipt_ids=[rid],proposed_state={}).valid)

    def test_schemas_reject_execution_or_acceptance_claims(self):
        boundary=copy.deepcopy(self.boundary); boundary["executionState"]="executed"
        with self.assertRaises(ValidationError): self.schemas["boundary-descriptor"].validate(boundary)
        receipt=copy.deepcopy(self.receipt); receipt["acceptanceState"]="accepted"
        with self.assertRaises(ValidationError): self.schemas["receipt"].validate(receipt)

    def test_negative_transition_fixtures_are_schema_invalid(self):
        fixture_dir = Path("tests/fixtures/boundary-receipt-transition")
        expected = {
            "invalid-transition-accepted.json",
            "invalid-transition-advanced.json",
            "invalid-transition-duplicate-receipt.json",
            "invalid-transition-malformed-receipt-id.json",
            "invalid-transition-missing-prior-state.json",
            "invalid-transition-proposal-claims-acceptance.json",
        }
        invalid = sorted(fixture_dir.glob("invalid-transition-*.json"))
        self.assertEqual(expected, {path.name for path in invalid})
        validator = self.schemas["state-transition"]
        for path in invalid:
            with self.subTest(path=path.name):
                value = json.loads(path.read_text())
                with self.assertRaises(ValidationError):
                    validator.validate(value)

    def test_transition_rejects_proposed_acceptance_claim(self):
        result = create_state_transition(
            prior_state=self.prior,
            boundary=self.boundary,
            proposed_state={"acceptanceState": "accepted"},
        )
        self.assertFalse(result.valid)
        self.assertEqual("acceptance_claim_in_proposal", result.diagnostics[0]["code"])

    def test_malformed_identity_fails_closed(self):
        changed = dict(self.ids)
        changed["validator"] = "sha256:not-a-digest"
        self.assertFalse(create_boundary_descriptor(
            responsibility="one",
            scope=["x"],
            identities=changed,
        ).valid)

    def test_transition_constructor_rejects_malformed_and_duplicate_receipt_ids(self):
        malformed = create_state_transition(
            prior_state=self.prior,
            boundary=self.boundary,
            attached_receipt_ids=["receipt-1"],
            proposed_state={},
        )
        duplicate = create_state_transition(
            prior_state=self.prior,
            boundary=self.boundary,
            attached_receipt_ids=[self.receipt["receiptId"], self.receipt["receiptId"]],
            proposed_state={},
        )
        self.assertFalse(malformed.valid)
        self.assertFalse(duplicate.valid)

    def test_constructor_normalizes_embedded_identity_whitespace(self):
        prior = copy.deepcopy(self.prior)
        prior["stateIdentity"] = f"  {prior['stateIdentity']}  "
        boundary = copy.deepcopy(self.boundary)
        boundary["boundaryId"] = f"  {boundary['boundaryId']}  "
        transition = create_state_transition(
            prior_state=prior,
            boundary=boundary,
            proposed_state={},
        )
        self.assertTrue(transition.valid)
        self.schemas["state-transition"].validate(transition.value)
        self.assertEqual(self.prior["stateIdentity"], transition.value["priorStateIdentity"])
        self.assertEqual(self.boundary["boundaryId"], transition.value["boundaryId"])

    def test_domain_specific_boundary_identity_is_required(self):
        boundary = copy.deepcopy(self.boundary)
        boundary["boundaryId"] = "sha256:" + "a" * 64
        self.assertFalse(issue_receipt(
            boundary,
            candidate_identity="sha256:candidate:v1:" + "9" * 64,
            mutation_identity="sha256:mutation:v1:" + "8" * 64,
            completion_identity="sha256:completion:v1:" + "7" * 64,
            evidence_identities=["sha256:evidence:v1:" + "6" * 64],
        ).valid)
        self.assertFalse(create_state_transition(
            prior_state=self.prior,
            boundary=boundary,
            proposed_state={},
        ).valid)

    def test_non_serializable_state_fails_closed(self):
        result = create_state_transition(
            prior_state=self.prior,
            boundary=self.boundary,
            proposed_state={"value": object()},
        )
        self.assertFalse(result.valid)
        self.assertEqual("non_canonical_transition", result.diagnostics[0]["code"])

    def test_receipt_rejects_duplicate_scope_and_malformed_evidence(self):
        duplicate_scope = copy.deepcopy(self.boundary)
        duplicate_scope["scope"] = ["collab", "collab"]
        malformed_evidence = issue_receipt(
            self.boundary,
            candidate_identity="sha256:candidate:v1:" + "9" * 64,
            mutation_identity="sha256:mutation:v1:" + "8" * 64,
            completion_identity="sha256:completion:v1:" + "7" * 64,
            evidence_identities=["sha256:not-hex"],
        )
        self.assertFalse(issue_receipt(
            duplicate_scope,
            candidate_identity="sha256:candidate:v1:" + "9" * 64,
            mutation_identity="sha256:mutation:v1:" + "8" * 64,
            completion_identity="sha256:completion:v1:" + "7" * 64,
            evidence_identities=["sha256:evidence:v1:" + "6" * 64],
        ).valid)
        self.assertFalse(malformed_evidence.valid)

    def test_boundary_rejects_duplicate_scope(self):
        self.assertFalse(create_boundary_descriptor(
            responsibility="one",
            scope=["a", "a"],
            identities=self.ids,
        ).valid)

    def test_receipt_fails_closed_for_non_mapping_identities(self):
        for invalid in (None, [], "invalid"):
            with self.subTest(value=invalid):
                boundary = copy.deepcopy(self.boundary)
                boundary["identities"] = invalid
                result = issue_receipt(
                    boundary,
                    candidate_identity="sha256:candidate:v1:" + "9" * 64,
                    mutation_identity="sha256:mutation:v1:" + "8" * 64,
                    completion_identity="sha256:completion:v1:" + "7" * 64,
                    evidence_identities=["sha256:evidence:v1:" + "6" * 64],
                )
                self.assertFalse(result.valid)
                self.assertEqual(
                    "invalid_boundary_identities",
                    result.diagnostics[0]["code"],
                )

    def test_applicability_fails_closed_for_non_mapping_material(self):
        receipt = copy.deepcopy(self.receipt)
        receipt["applicability"] = None
        result = evaluate_receipt_applicability(
            receipt,
            boundary=self.boundary,
            candidate_identity=self.receipt["candidateIdentity"],
            configuration_identity=self.ids["configuration"],
            validator_identity=self.ids["validator"],
        )
        self.assertFalse(result.valid)
        self.assertEqual(
            "invalid_receipt_applicability",
            result.diagnostics[0]["code"],
        )

    def test_transition_rejects_non_serializable_proposed_state(self):
        result = create_state_transition(
            prior_state=self.prior,
            boundary=self.boundary,
            proposed_state={"payload": b"bytes"},
        )
        self.assertFalse(result.valid)
        self.assertEqual("non_canonical_transition", result.diagnostics[0]["code"])

if __name__ == "__main__": unittest.main()
