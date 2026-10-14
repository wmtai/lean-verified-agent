import tasks.development.checked_subtraction.Specification

/-
This file compiles: its function has the required type. Its underflow result is
a concrete counterexample to the fixed contract. It has no correctness proof.
-/
namespace Exercise1.WrongImplementation

def candidate (a b : Nat) : Option Nat :=
  some (a - b)

-- Nat subtraction saturates at zero, so this prints `some 0`, not `none`.
#eval candidate 3 5

end Exercise1.WrongImplementation
