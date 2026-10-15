"""Exercise 2 acceptance tests. These intentionally fail for the starter code.

They check interfaces and assembly, not semantic proof correctness or isolation.
"""

from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agent.proposal import MAX_BODY_BYTES, Proposal
from agent.render import render_candidate
from agent.task import Task


ROOT = Path(__file__).resolve().parents[3]
TASK_ID = "checked_subtraction"
TASK_DIRECTORY = Path("tasks/development") / TASK_ID
IMPLEMENTATION = "if b ≤ a then some (a - b) else none"
PROOF = "by\n  unfold TaskSpec.CheckedSubSpec\n  constructor\n  <;> intro a b h\n  <;> simp [candidate]\n  <;> omega"


def response(implementation=IMPLEMENTATION, proof=PROOF):
    return json.dumps({"implementation_body": implementation, "proof_body": proof})


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        shutil.copytree(ROOT / TASK_DIRECTORY, self.root / TASK_DIRECTORY)
        shutil.copyfile(ROOT / "lean-toolchain", self.root / "lean-toolchain")
        self.metadata_path = self.root / TASK_DIRECTORY / "task.json"
        self.metadata = json.loads(self.metadata_path.read_text())

    def tearDown(self):
        self.temporary.cleanup()

    def write_metadata(self):
        self.metadata_path.write_text(json.dumps(self.metadata), encoding="utf-8")

    def test_loads_fixed_contract_headers_imports_and_examples(self):
        task = Task.load(self.root, TASK_ID)
        self.assertEqual(task.id, TASK_ID)
        self.assertEqual(task.family, "checked_arithmetic")
        self.assertEqual(task.specification_declaration, "TaskSpec.CheckedSubSpec")
        self.assertIn("def CheckedSubSpec", task.specification_source)
        self.assertEqual(task.implementation_header, "def candidate (a b : Nat) : Option Nat :=")
        self.assertEqual(task.implementation_type, "Nat → Nat → Option Nat")
        self.assertEqual(task.theorem_header, "theorem candidate_correct : TaskSpec.CheckedSubSpec candidate :=")
        self.assertEqual(task.permitted_imports, (task.specification_module,))
        self.assertEqual(task.public_examples[0].arguments, (3, 5))
        self.assertEqual(task.public_examples[0].expected, "none")
        self.assertEqual(task.lean_toolchain, "leanprover/lean4:v4.34.1")
        self.assertEqual(json.loads(task.metadata_json), self.metadata)

    def test_task_and_nested_examples_are_immutable(self):
        task = Task.load(self.root, TASK_ID)
        with self.assertRaises(FrozenInstanceError):
            task.title = "Changed"
        self.assertIsInstance(task.permitted_imports, tuple)
        self.assertIsInstance(task.public_examples, tuple)
        with self.assertRaises(FrozenInstanceError):
            task.public_examples[0].expected = "some 0"
        self.assertIsInstance(task.public_examples[0].arguments, tuple)

    def test_invalid_identifiers_and_splits_are_rejected(self):
        for identifier in ("../checked_subtraction", "/tmp/other", "CheckedSubtraction", "", 12):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                Task.load(self.root, identifier)
        with self.assertRaises(ValueError):
            Task.load(self.root, TASK_ID, split="../development")

    def test_metadata_identity_must_match_its_folder(self):
        self.metadata["id"] = "different_task"
        self.write_metadata()
        with self.assertRaises(ValueError):
            Task.load(self.root, TASK_ID)

    def test_missing_or_invalid_metadata_fields_are_rejected(self):
        original = json.loads(self.metadata_path.read_text())
        for mutate in (
            lambda data: data.pop("required_declarations"),
            lambda data: data.update(title=12),
            lambda data: data.update(permitted_imports="Lean"),
            lambda data: data["required_declarations"]["implementation"].update(header=None),
            lambda data: data.update(editable_regions=["implementation_body", "specification"]),
            lambda data: data["public_examples"][0].update(arguments=[True, -1]),
        ):
            with self.subTest(mutate=mutate):
                data = json.loads(json.dumps(original))
                mutate(data)
                self.metadata_path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    Task.load(self.root, TASK_ID)

    def test_missing_files_and_malformed_json_are_value_errors(self):
        for payload in ("[]", "null", "{not json"):
            with self.subTest(payload=payload):
                self.metadata_path.write_text(payload)
                with self.assertRaises(ValueError):
                    Task.load(self.root, TASK_ID)
        self.write_metadata()
        (self.root / TASK_DIRECTORY / "Specification.lean").unlink()
        with self.assertRaises(ValueError):
            Task.load(self.root, TASK_ID)

    def test_sources_must_stay_inside_the_repository(self):
        for key in ("specification", "candidate_template"):
            with self.subTest(key=key):
                original = json.loads(self.metadata_path.read_text())
                modified = json.loads(json.dumps(original))
                if key == "specification":
                    modified[key]["path"] = "../outside.lean"
                else:
                    modified[key] = "../outside.lean"
                self.metadata_path.write_text(json.dumps(modified))
                with self.assertRaises(ValueError):
                    Task.load(self.root, TASK_ID)
                self.metadata_path.write_text(json.dumps(original))

    def test_digest_is_portable_and_tracks_the_loaded_snapshot(self):
        original = Task.load(self.root, TASK_ID)
        self.assertRegex(original.digest, r"^[a-f0-9]{64}$")
        self.assertEqual(original.digest, Task.load(ROOT, TASK_ID).digest)
        self.metadata_path.write_text(json.dumps(self.metadata, sort_keys=True, indent=4))
        self.assertEqual(original.digest, Task.load(self.root, TASK_ID).digest)
        old_source = original.specification_source
        old_digest = original.digest
        path = self.root / TASK_DIRECTORY / "Specification.lean"
        path.write_text(path.read_text() + "\n-- changed trusted snapshot\n")
        self.assertEqual(original.specification_source, old_source)
        self.assertEqual(original.digest, old_digest)
        self.assertNotEqual(Task.load(self.root, TASK_ID).digest, old_digest)

    def test_template_placeholders_are_checked(self):
        path = self.root / TASK_DIRECTORY / "candidate_template.lean"
        original = path.read_text()
        changes = (
            original.replace("{{proof_body}}", "by rfl"),
            original + "\n{{implementation_body}}\n",
            original + "\n{{specification}}\n",
        )
        for source in changes:
            with self.subTest(source=source[-80:]):
                path.write_text(source)
                with self.assertRaises(ValueError):
                    Task.load(self.root, TASK_ID)

    def test_accidental_signature_theorem_and_import_changes_are_rejected(self):
        path = self.root / TASK_DIRECTORY / "candidate_template.lean"
        original = path.read_text()
        changes = (
            original.replace(": Option Nat :=", ": Nat :="),
            original.replace("TaskSpec.CheckedSubSpec candidate :=", "True :="),
            original.replace("def candidate ", "def other "),
            original + "\nimport Some.Unapproved.Module\n",
        )
        for source in changes:
            with self.subTest(source=source[-100:]):
                path.write_text(source)
                with self.assertRaises(ValueError):
                    Task.load(self.root, TASK_ID)


class ProposalTests(unittest.TestCase):
    def test_valid_fields_are_preserved(self):
        proposal = Proposal.from_json(response())
        self.assertEqual(proposal.implementation_body, IMPLEMENTATION)
        self.assertEqual(proposal.proof_body, PROOF)
        with self.assertRaises(FrozenInstanceError):
            proposal.proof_body = "by rfl"

    def test_missing_extra_and_replacement_contract_fields_are_rejected(self):
        for value in (
            {"implementation_body": IMPLEMENTATION},
            {"implementation_body": IMPLEMENTATION, "proof_body": PROOF, "specification": "True"},
            {"implementation_body": IMPLEMENTATION, "proof_body": PROOF, "signature": "Nat"},
            {"implementation": IMPLEMENTATION, "proof": PROOF},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Proposal.from_json(json.dumps(value))

    def test_malformed_json_and_non_objects_are_rejected(self):
        for payload in ("{not json", "[]", "null", "12", '"hello"', "```json\n{}\n```"):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                Proposal.from_json(payload)

    def test_fields_must_be_nonempty_strings(self):
        for field in ("implementation_body", "proof_body"):
            for bad_value in (None, 0, True, [], "", " \n\t"):
                with self.subTest(field=field, value=bad_value):
                    value = {"implementation_body": IMPLEMENTATION, "proof_body": PROOF, field: bad_value}
                    with self.assertRaises(ValueError):
                        Proposal.from_json(json.dumps(value))

    def test_size_limit_is_measured_in_utf8_bytes(self):
        with self.assertRaises(ValueError):
            Proposal.from_json(response("α" * (MAX_BODY_BYTES // 2 + 1)))
        Proposal.from_json(response("n" * MAX_BODY_BYTES))

    def test_preflight_rejects_declarations_commands_and_placeholders(self):
        bodies = ("def other := 0", "by\n  sorry", "by admit", "axiom cheat : False",
                  "import Lean", "0\n)\ntheorem other : True := by trivial",
                  "#eval 0", "namespace Other", "unsafeCast 0\nunsafe", "end")
        for field in ("implementation_body", "proof_body"):
            for body in bodies:
                with self.subTest(field=field, body=body):
                    value = {"implementation_body": IMPLEMENTATION, "proof_body": PROOF, field: body}
                    with self.assertRaises(ValueError):
                        Proposal.from_json(json.dumps(value))

    def test_local_helpers_and_whole_word_matching_are_allowed(self):
        implementation = "let rec go (n : Nat) : Nat :=\n  match n with\n  | 0 => 0\n  | n + 1 => go n + 1\nsome (go a)"
        proof = "by\n  have endValue : a = a := rfl\n  exact endValue"
        Proposal.from_json(response(implementation, proof))

    def test_directly_constructed_proposals_are_also_validated(self):
        for proposal in (Proposal(0, PROOF), Proposal(IMPLEMENTATION, "by sorry")):
            with self.subTest(proposal=proposal), self.assertRaises(ValueError):
                proposal.validate()


class RendererTests(unittest.TestCase):
    def setUp(self):
        self.task = Task.load(ROOT, TASK_ID)

    def test_only_the_two_body_regions_change(self):
        proposal = Proposal.from_json(response())
        source = render_candidate(self.task, proposal)
        implementation = "\n".join("  " + line for line in IMPLEMENTATION.strip().splitlines())
        proof = "\n".join("  " + line for line in PROOF.strip().splitlines())
        expected = self.task.template_source.replace("{{implementation_body}}", implementation).replace("{{proof_body}}", proof)
        self.assertEqual(source, expected)
        self.assertIn(self.task.implementation_header, source)
        self.assertIn(self.task.theorem_header, source)

    def test_multiline_indentation_preserves_inner_structure(self):
        body = "\nif b ≤ a then\n  some (a - b)\nelse\n  none\n"
        source = render_candidate(self.task, Proposal.from_json(response(body)))
        self.assertIn("  if b ≤ a then\n    some (a - b)\n  else\n    none", source)

    def test_inserted_placeholder_text_is_not_replaced_again(self):
        body = "some (a - b) -- {{proof_body}}"
        source = render_candidate(self.task, Proposal.from_json(response(body)))
        self.assertIn("-- {{proof_body}}", source)
        self.assertIn("  by\n", source)

    def test_rendering_neither_mutates_task_nor_writes_trusted_files(self):
        spec_path = ROOT / TASK_DIRECTORY / "Specification.lean"
        template_path = ROOT / TASK_DIRECTORY / "candidate_template.lean"
        before = (spec_path.read_bytes(), template_path.read_bytes(), self.task.digest)
        render_candidate(self.task, Proposal.from_json(response()))
        self.assertEqual(before, (spec_path.read_bytes(), template_path.read_bytes(), self.task.digest))

    def test_renderer_revalidates_direct_objects(self):
        with self.assertRaises(ValueError):
            render_candidate(self.task, Proposal(IMPLEMENTATION, "by sorry"))
        changed = replace(self.task, theorem_header="theorem candidate_correct : True :=")
        with self.assertRaises(ValueError):
            render_candidate(changed, Proposal.from_json(response()))


if __name__ == "__main__":
    unittest.main()
