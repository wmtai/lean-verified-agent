import Lean

/-
The task designer owns this file. Candidates import this contract and prove it;
they do not edit its definition to match their implementation.

Natural-number subtraction alone returns 0 on underflow. Checked subtraction
must report that case with `none` instead.
-/
namespace TaskSpec

def CheckedSubSpec (f : Nat → Nat → Option Nat) : Prop :=
  (∀ a b, b ≤ a → f a b = some (a - b)) ∧
  (∀ a b, a < b → f a b = none)

end TaskSpec
