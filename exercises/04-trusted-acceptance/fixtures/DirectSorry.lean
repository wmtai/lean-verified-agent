import tasks.development.checked_subtraction.Specification

def candidate (a b : Nat) : Option Nat :=
  if b ≤ a then some (a - b) else none

theorem candidate_correct : TaskSpec.CheckedSubSpec candidate := by
  sorry
