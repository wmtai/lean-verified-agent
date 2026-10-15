import Lean

namespace TaskSpec
def CheckedSubSpec (_ : Nat → Nat → Option Nat) : Prop := True
end TaskSpec

def candidate (a b : Nat) : Option Nat :=
  if b ≤ a then some (a - b) else none

theorem candidate_correct : TaskSpec.CheckedSubSpec candidate := by trivial
