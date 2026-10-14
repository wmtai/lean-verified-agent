import tasks.development.checked_subtraction.Specification

/-
This file deliberately fails to compile. The implementation is well typed, but
the attempted proof cannot establish its required underflow behavior.
-/
namespace Exercise1.WrongProof

def candidate (a b : Nat) : Option Nat :=
  some (a - b)

theorem candidate_correct : TaskSpec.CheckedSubSpec candidate := by
  unfold TaskSpec.CheckedSubSpec
  constructor
  · intro a b h
    simp [candidate]
  · intro a b h
    simp [candidate]

end Exercise1.WrongProof
