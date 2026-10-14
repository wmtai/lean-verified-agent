import tasks.development.checked_subtraction.Specification

/-
Replace the two holes while preserving the import, declaration names, function
signature, and theorem statement. `sorry` marks unfinished work: Lean may accept
it with a warning, but an unfinished proof does not complete this task.
-/

def candidate (a b : Nat) : Option Nat :=
  -- IMPLEMENTATION HOLE
  sorry

theorem candidate_correct : TaskSpec.CheckedSubSpec candidate := by
  -- PROOF HOLE
  sorry
