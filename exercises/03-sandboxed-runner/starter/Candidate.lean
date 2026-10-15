import tasks.development.checked_subtraction.Specification

-- The implementation and theorem statement are fixed for this exercise.
def candidate (a b : Nat) : Option Nat :=
  if b ≤ a then some (a - b) else none

theorem candidate_correct : TaskSpec.CheckedSubSpec candidate := by
  -- LEARNER PROOF STARTS HERE
  unfold TaskSpec.CheckedSubSpec
  constructor
  · intro a b h
    simp [candidate, h]
  · intro a b h
    simp only [candidate]
    have h1: ¬ (b ≤ a) := by simp [h]
    simp [h1]
