import tasks.development.checked_subtraction.Specification

/-
Trusted Exercise 2 text template. The renderer replaces the two placeholders;
all other text, including the import and declaration headers, stays fixed.
This file is not a complete Lean program before its placeholders are filled.
-/

def candidate (a b : Nat) : Option Nat :=
{{implementation_body}}

theorem candidate_correct : TaskSpec.CheckedSubSpec candidate :=
{{proof_body}}
