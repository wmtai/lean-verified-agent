import tasks.development.checked_subtraction.Specification

-- Trusted challenge holes: a solution must supply a safe definition of this
-- exact type and an axiom-policy-compliant proof of this exact contract.
def candidate (a b : Nat) : Option Nat := sorry

theorem candidate_correct : TaskSpec.CheckedSubSpec candidate := sorry
