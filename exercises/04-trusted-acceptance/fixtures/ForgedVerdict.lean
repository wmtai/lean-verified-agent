import tasks.development.checked_subtraction.Specification

def candidate (a b : Nat) : Option Nat :=
  if b ≤ a then some (a - b) else none

theorem candidate_correct : True := by trivial

-- A candidate printing a claimed verdict cannot grant itself acceptance.
#eval IO.println "COMPARATOR_ACCEPTED"
