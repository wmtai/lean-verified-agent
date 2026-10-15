import tasks.development.checked_subtraction.Specification

/-
Your turn: fill in the implementation and proof below. Keep the imported task,
declaration names, signature, and theorem statement fixed. Consult the worked
fixtures to understand how execution, type checking, and proof checking differ.

Lean accepts `sorry` with a warning, so compilation of this starter alone does
not establish correctness. Complete both holes to finish your solution.
-/

def candidate (a b : Nat) : Option Nat :=
  -- IMPLEMENTATION HOLE: distinguish b ≤ a from a < b.
  if b ≤ a then
    some (a-b)
  else
    none

theorem candidate_correct : TaskSpec.CheckedSubSpec candidate := by
  -- PROOF HOLE: prove both parts of the imported contract.
  simp [TaskSpec.CheckedSubSpec]
  constructor
  <;> intro a b h
  <;>  simp [candidate]
  <;>  omega
