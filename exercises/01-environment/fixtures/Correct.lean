import tasks.development.checked_subtraction.Specification

/- A worked example: an executable implementation and a proof of the fixed contract. -/
namespace Exercise1.Correct

def candidate (a b : Nat) : Option Nat :=
  if b ≤ a then
    some (a - b)
  else
    none

theorem candidate_correct : TaskSpec.CheckedSubSpec candidate := by
  unfold TaskSpec.CheckedSubSpec
  constructor
  · intro a b h
    simp [candidate, h]
  · intro a b h
    have hnot : ¬ b ≤ a := by
      omega
    simp [candidate, hnot]

-- Execution examples complement the universal correctness theorem above.
#eval candidate 3 5
#eval candidate 8 3

end Exercise1.Correct
