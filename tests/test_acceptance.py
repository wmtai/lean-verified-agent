from pathlib import Path
import unittest

from agent.schema import Candidate, Task
from verifier.acceptance import PolicyViolation, _lean_string, render_candidate, validate_candidate


def example_task() -> Task:
    return Task("maximum", "Maximum", "arithmetic", "dev",
                "def Spec (f : Nat → Nat → Nat) : Prop := ∀ a b, f a b = Nat.max a b",
                "(a b : Nat) : Nat", forbidden_identifiers=("Nat.max",))


class AcceptancePolicyTests(unittest.TestCase):
    def test_model_cannot_insert_declarations_or_commands(self):
        attacks = [
            "sorry", "by admit", "by exact sorryAx _ true", "by native_decide",
            "by run_tac do pure ()", "0\n)\naxiom cheat : False\ndef other := (0",
            "0\n)\nend Generated\nnamespace Generated\n(0", "by\n  set_option debug.skipKernelTC true in exact rfl",
            "0\n)\n#eval IO.println \"spoof\"\n(0", "Lean.ofReduceBool rfl",
            "«sorryAx»", "`Generated.candidate", "0 /- swallowed suffix", "0 -/",
            "0\u202e", "by exact Lean . Elab . Term . elabTerm",
        ]
        for attack in attacks:
            for field in ("implementation", "proof"):
                with self.subTest(attack=attack, field=field):
                    candidate = Candidate(attack, "by rfl") if field == "implementation" else Candidate("a", attack)
                    with self.assertRaises(PolicyViolation):
                        validate_candidate(example_task(), candidate)

    def test_forbidden_algorithm_rejected_only_from_implementation(self):
        for implementation in ("Nat.max a b", "@Nat.max a b", "Nat . max a b"):
            with self.subTest(implementation=implementation):
                with self.assertRaises(PolicyViolation):
                    validate_candidate(example_task(), Candidate(implementation, "by rfl"))
        validate_candidate(example_task(), Candidate("if a ≤ b then b else a", "by simp [Nat.max]"))

    def test_nested_comments_do_not_change_meaning_of_policy(self):
        validate_candidate(example_task(), Candidate("a /- sorry /- axiom -/ -/", "by\n  -- sorry is forbidden code\n  rfl"))
        with self.assertRaises(PolicyViolation):
            validate_candidate(example_task(), Candidate("a /- harmless -/ + sorry", "by rfl"))

    def test_local_helpers_and_ordinary_tactics_are_supported(self):
        candidate = Candidate("let rec go : Nat → Nat\n  | 0 => 0\n  | n + 1 => go n + 1\ngo a",
                              "by\n  intro x\n  have h' : x = x := rfl\n  simp [candidate, candidate.go]")
        validate_candidate(example_task(), candidate)

    def test_renderer_preserves_exact_contract_and_signature(self):
        task = example_task()
        source = render_candidate(task, Candidate("if a ≤ b then b else a", "by omega"), "a" * 32)
        self.assertIn(task.specification, source)
        self.assertIn(f"#checked_candidate {task.signature} := ", source)
        self.assertIn(_lean_string("if a ≤ b then b else a"), source)
        self.assertIn(_lean_string("by omega"), source)
        self.assertIn("example : Spec candidate := candidate_correct", source)
        self.assertTrue(source.endswith('#audit_candidate "' + "a" * 32 + '"\n'))

    def test_literal_transport_does_not_expose_candidate_commands(self):
        # Quotes and backslashes inside comments are allowed by the lexical
        # policy, but must remain data in the outer command parser.
        candidate = Candidate('a /- " \\ \n)\nsimproc -/', "by rfl -- trailing comment")
        source = render_candidate(example_task(), candidate, "a" * 32)
        command = next(line for line in source.splitlines() if line.startswith("#checked_candidate"))
        self.assertIn('\\"', command)
        self.assertIn('\\\\', command)
        self.assertIn('\\nsimproc', command)
        self.assertNotIn("\nsimproc", source)

    def test_lean_string_escapes_controls_without_changing_literal_backslashes(self):
        self.assertEqual(_lean_string("\b\f\x00\x7f"), '"\\u0008\\u000c\\u0000\\u007f"')
        self.assertEqual(_lean_string(r"\b\u0000"), '"\\\\b\\\\u0000"')

    def test_empty_oversized_or_untrusted_marker_rejected(self):
        for candidate in (Candidate("", "by rfl"), Candidate("a", " " * 40000), Candidate("x" * 32769, "by rfl")):
            with self.assertRaises(PolicyViolation):
                validate_candidate(example_task(), candidate)
        with self.assertRaises(ValueError):
            render_candidate(example_task(), Candidate("a", "by rfl"), 'bad"\n#eval')


if __name__ == "__main__":
    unittest.main()
