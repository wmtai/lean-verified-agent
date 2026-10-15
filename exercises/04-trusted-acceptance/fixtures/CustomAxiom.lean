import tasks.development.checked_subtraction.Specification

def candidate (a b : Nat) : Option Nat :=
  if b ≤ a then some (a - b) else none

axiom underflow (a b : Nat) (h : a < b) : candidate a b = none

theorem candidate_correct : TaskSpec.CheckedSubSpec candidate := by
  unfold TaskSpec.CheckedSubSpec
  constructor
  · intro a b h
    simp [candidate, h]
  · intro a b h
    exact underflow a b h
