import copy
import hashlib
import json
import unittest

from collab.preparation_materialization import materialize_preparation_plan, validate_materialized_package
from collab.preparation_planning import PreparationRequest, plan_preparation


def make_plan(selection="FOCUSED", *, byte_limit=50000, artifact_limit=3, domains=("state",), items=None):
    items = items if items is not None else [
        {"itemId": "state", "domain": "state", "byteSize": 5, "artifactCount": 1},
        {"itemId": "code", "domain": "code", "byteSize": 4, "artifactCount": 1},
    ]
    request = PreparationRequest(
        boundary={"boundaryId": "issue-67", "status": "pending"}, selection=selection,
        required_domains=domains, byte_limit=byte_limit, artifact_limit=artifact_limit,
        explicit_item_ids=tuple(x["itemId"] for x in items) if selection == "EXPLICIT_FULL" else (),
    )
    result = plan_preparation(request, items)
    assert result.valid
    return result.value


def finalize_plan(plan):
    plan = copy.deepcopy(plan)
    plan.pop("planId", None)
    canonical = json.dumps(plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    plan["planId"] = "sha256:preparation-plan:v1:" + hashlib.sha256(canonical).hexdigest()
    return plan

ASSIGNMENT = {
    "activeCard": "Issue #67 materialization",
    "establishedState": "Baseline accepted.",
    "developmentIntent": "Materialize one package.",
    "authorities": ["Issue #67", "collaboration model"],
    "resultContract": "Return implementation evidence.",
    "stopCondition": "Stop after reporting the bounded result.",
}


class MaterializationTests(unittest.TestCase):
    def materialize(self, plan=None, payloads=None):
        plan = plan or make_plan()
        payloads = payloads or {x["itemId"]: (b"state" if x["itemId"] == "state" else b"code") for x in plan["selectedItems"]}
        return materialize_preparation_plan(plan, payloads, ASSIGNMENT)

    def test_complete_focused_plan_materializes_three_bound_artifacts(self):
        result = self.materialize()
        self.assertTrue(result.valid, result.diagnostics)
        self.assertEqual([n for n, _ in result.artifacts], ["project.context.txt", "project.current-state.json", "project.start-prompt.txt"])
        manifest = json.loads(result.as_mapping()["project.current-state.json"])
        self.assertEqual(manifest["artifactCount"], 3)
        prompt = result.as_mapping()["project.start-prompt.txt"].decode()
        self.assertIn(manifest["inputBinding"], prompt)
        self.assertIn("issue-67 (pending)", prompt)
        self.assertIn("[required-domain]", prompt)

    def test_state_only_omits_context(self):
        plan = make_plan("STATE_ONLY")
        result = self.materialize(plan)
        self.assertEqual([n for n, _ in result.artifacts], ["project.current-state.json", "project.start-prompt.txt"])

    def test_selection_modes_never_expand_payloads(self):
        for mode in ("FOCUSED", "BROAD", "EXPLICIT_FULL"):
            with self.subTest(mode=mode):
                plan = make_plan(mode, domains=("state", "code"))
                result = self.materialize(plan)
                context = result.as_mapping()["project.context.txt"]
                self.assertIn(b"state", context); self.assertIn(b"code", context)
                self.assertNotIn(b"unselected", context)

    def test_deterministic_bytes_and_stable_order(self):
        plan = make_plan("BROAD", domains=("state", "code"))
        first = self.materialize(plan); second = self.materialize(copy.deepcopy(plan))
        self.assertEqual(first.artifacts, second.artifacts)
        self.assertEqual(list(first.artifacts), sorted(first.artifacts))

    def test_artifact_and_byte_limits(self):
        plan = make_plan(artifact_limit=2)
        self.assertEqual(self.materialize(plan).diagnostics[0]["code"], "artifact_limit")
        plan = make_plan(byte_limit=10)
        self.assertEqual(self.materialize(plan).diagnostics[0]["code"], "byte_limit")

    def test_explicit_omissions_and_limitations_render(self):
        plan = make_plan(domains=("state", "missing"))
        result = self.materialize(plan)
        prompt = result.as_mapping()["project.start-prompt.txt"].decode()
        self.assertIn("missing [required-domain-incomplete]", prompt)
        self.assertIn("OMISSIONS", prompt)

    def test_missing_domain_disclosure_is_required(self):
        plan = copy.deepcopy(make_plan(domains=("state", "missing")))
        plan["limitations"] = []
        # preserve a matching identity so validation reaches disclosure logic
        import hashlib
        core = copy.deepcopy(plan); core.pop("planId")
        canonical = json.dumps(core, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        plan["planId"] = "sha256:preparation-plan:v1:" + hashlib.sha256(canonical).hexdigest()
        self.assertEqual(self.materialize(plan).diagnostics[0]["code"], "missing_domain_disclosure")

    def test_invalid_multiple_and_nonpending_boundaries_rejected(self):
        for boundary in ([{"boundaryId": "a"}, {"boundaryId": "b"}], {"boundaryId": "issue-67", "status": "complete"}):
            plan = copy.deepcopy(make_plan()); plan["boundary"] = boundary
            self.assertFalse(self.materialize(plan).valid)

    def test_tampered_plan_and_payload_rejected_without_guessing(self):
        plan = copy.deepcopy(make_plan()); plan["selection"] = "BROAD"
        self.assertEqual(self.materialize(plan).diagnostics[0]["code"], "inapplicable_plan")
        plan = make_plan()
        self.assertEqual(self.materialize(plan, {"state": b"wrong!"}).diagnostics[0]["code"], "evidence_mismatch")

    def test_mixed_or_tampered_member_detected(self):
        result = self.materialize(); artifacts = result.as_mapping()
        artifacts["project.start-prompt.txt"] += b"tampered"
        self.assertEqual(validate_materialized_package(artifacts).diagnostics[0]["code"], "member_identity")

    def test_mutation_sentinel_and_no_advancement(self):
        result = self.materialize(); manifest = json.loads(result.as_mapping()["project.current-state.json"])
        self.assertEqual(manifest["boundary"]["status"], "pending")
        self.assertEqual(manifest["mutationSentinel"], {"repositoryMutated": False, "hostedStateMutated": False, "boundaryExecuted": False, "boundaryAdvanced": False})

    def test_inputs_remain_unchanged(self):
        plan = make_plan(); payloads = {"state": b"state"}; assignment = copy.deepcopy(ASSIGNMENT)
        before = (copy.deepcopy(plan), copy.deepcopy(payloads), copy.deepcopy(assignment))
        materialize_preparation_plan(plan, payloads, assignment)
        self.assertEqual((plan, payloads, assignment), before)

    def test_incomplete_assignment_and_pristine_planning_sentinel_required(self):
        assignment = copy.deepcopy(ASSIGNMENT); assignment.pop("stopCondition")
        self.assertEqual(materialize_preparation_plan(make_plan(), {"state": b"state"}, assignment).diagnostics[0]["code"], "incomplete_assignment")
        plan = copy.deepcopy(make_plan()); plan["mutationSentinel"]["boundaryAdvanced"] = True
        self.assertFalse(self.materialize(plan).valid)

    def test_issue66_boundary_metadata_is_accepted(self):
        plan = copy.deepcopy(make_plan())
        plan["boundary"]["objective"] = "issue-66"
        plan = finalize_plan(plan)
        self.assertTrue(self.materialize(plan).valid)

    def test_malformed_nested_plan_fields_are_structured_rejections(self):
        mutations = (
            lambda p: p["selectedItems"][0].pop("domain"),
            lambda p: p["selectedItems"][0].__setitem__("byteSize", "5"),
            lambda p: p["omissions"].append({"itemId": "x"}),
            lambda p: p["limitations"].append({"domain": "x"}),
            lambda p: p["requiredDomains"].append({"domain": "state"}),
            lambda p: p.__setitem__("totals", {"bytes": 99, "artifacts": 1}),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                plan = copy.deepcopy(make_plan()); mutate(plan); plan = finalize_plan(plan)
                result = self.materialize(plan)
                self.assertFalse(result.valid)
                self.assertEqual(result.status, "invalid")
                self.assertTrue(result.diagnostics)

    def test_cross_run_member_mixing_rejected_after_rehash(self):
        first = self.materialize().as_mapping()
        assignment = copy.deepcopy(ASSIGNMENT); assignment["activeCard"] = "different-card"
        second = materialize_preparation_plan(make_plan(), {"state": b"state"}, assignment).as_mapping()
        mixed = dict(first); mixed["project.start-prompt.txt"] = second["project.start-prompt.txt"]
        manifest = json.loads(mixed["project.current-state.json"])
        member = next(m for m in manifest["members"] if m["name"] == "project.start-prompt.txt")
        member["bytes"] = len(mixed["project.start-prompt.txt"])
        member["sha256"] = "sha256:" + hashlib.sha256(mixed["project.start-prompt.txt"]).hexdigest()
        mixed["project.current-state.json"] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        self.assertEqual(validate_materialized_package(mixed).diagnostics[0]["code"], "member_binding")

    def test_prompt_plan_and_boundary_identity_mismatches_are_rejected(self):
        for prefix, replacement in (("Preparation plan: ", "sha256:preparation-plan:v1:" + "9" * 64), ("Pending boundary: ", "sha256:boundary:v1:" + "8" * 64)):
            with self.subTest(prefix=prefix):
                artifacts = self.materialize().as_mapping(); prompt = artifacts["project.start-prompt.txt"].decode()
                lines = [prefix + replacement if line.startswith(prefix) else line for line in prompt.splitlines()]
                artifacts["project.start-prompt.txt"] = ("\n".join(lines) + "\n").encode()
                manifest = json.loads(artifacts["project.current-state.json"])
                row = next(m for m in manifest["members"] if m["name"] == "project.start-prompt.txt")
                row["bytes"] = len(artifacts["project.start-prompt.txt"]); row["sha256"] = "sha256:" + hashlib.sha256(artifacts["project.start-prompt.txt"]).hexdigest()
                artifacts["project.current-state.json"] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
                self.assertEqual(validate_materialized_package(artifacts).diagnostics[0]["code"], "member_binding")

    def test_context_binding_missing_members_additions_and_non_utf8_are_rejected(self):
        focused = copy.deepcopy(make_plan()); focused["selection"] = "FOCUSED"; focused = finalize_plan(focused)
        artifacts = self.materialize(focused).as_mapping(); context = artifacts["project.context.txt"].replace(b"PACKAGE INPUT BINDING: ", b"PACKAGE INPUT BINDING: wrong-")
        artifacts["project.context.txt"] = context
        manifest = json.loads(artifacts["project.current-state.json"]); row = next(m for m in manifest["members"] if m["name"] == "project.context.txt")
        row["bytes"] = len(context); row["sha256"] = "sha256:" + hashlib.sha256(context).hexdigest(); artifacts["project.current-state.json"] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        self.assertEqual(validate_materialized_package(artifacts).diagnostics[0]["code"], "member_binding")
        base = self.materialize().as_mapping(); base.pop("project.start-prompt.txt")
        self.assertEqual(validate_materialized_package(base).diagnostics[0]["code"], "artifact_set")
        base = self.materialize().as_mapping(); base["unexpected.txt"] = b"x"
        self.assertEqual(validate_materialized_package(base).diagnostics[0]["code"], "artifact_count")
        base = self.materialize().as_mapping(); base["project.start-prompt.txt"] = b"\xff"
        manifest = json.loads(base["project.current-state.json"]); row = next(m for m in manifest["members"] if m["name"] == "project.start-prompt.txt"); row["bytes"] = 1; row["sha256"] = "sha256:" + hashlib.sha256(b"\xff").hexdigest(); base["project.current-state.json"] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
        self.assertEqual(validate_materialized_package(base).diagnostics[0]["code"], "invalid_member")

    def test_limit_failure_returns_no_artifacts(self):
        plan = copy.deepcopy(make_plan()); plan["limits"]["bytes"] = 1; plan = finalize_plan(plan)
        result = self.materialize(plan)
        self.assertFalse(result.valid)
        self.assertEqual(result.artifacts, ())
        self.assertEqual(result.diagnostics[0]["code"], "byte_limit")


if __name__ == "__main__":
    unittest.main()
