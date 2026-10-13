import Lean
import Lean.Util.CollectAxioms

/-
  Only this trusted module may inspect the environment or emit the acceptance
  marker. Candidate text is transported as data and parsed as complete terms
  by #checked_candidate, never interpolated into command source.
  The allowed axioms are Lean's usual logical foundations, never sorryAx or
  compiler-trust axioms. This module itself is part of the trusted code base.
-/

open Lean Elab Command Meta

namespace Trusted

private def parseCandidateTerm (label source : String) : CommandElabM (TSyntax `term) := do
  -- runParserCategory rejects parser errors and any unconsumed input. This
  -- runs in the verifier process, with only the trusted imported grammar.
  match Parser.runParserCategory (← getEnv) `term source s!"<candidate {label}>" with
  | .ok stx => return ⟨stx⟩
  | .error diagnostic =>
      throwError "Trusted candidate boundary: {label} must be exactly one Lean term\n{diagnostic}"

elab "#checked_candidate " binders:bracketedBinder* " : " resultType:term " := "
    implementation:str proof:str : command => do
  -- Parse BOTH bodies before elaborating either one. Syntax splicing preserves
  -- the term/command boundary independently of indentation or keyword lists.
  let implementationTerm ← parseCandidateTerm "implementation" implementation.getString
  let proofTerm ← parseCandidateTerm "proof" proof.getString
  let candidateName := mkIdent `candidate
  let proofName := mkIdent `candidate_correct
  let specName := mkIdent `Spec
  elabCommand (← `(command| def $candidateName $binders:bracketedBinder* : $resultType := $implementationTerm))
  elabCommand (← `(command| theorem $proofName : $specName $candidateName := $proofTerm))

private def allowedAxiom (name : Name) : Bool :=
  name == ``propext || name == ``Classical.choice || name == ``Quot.sound

private partial def auditDependency
    (env : Environment) (name : Name) (seen : NameSet) : CommandElabM NameSet := do
  if seen.contains name then return seen
  let seen := seen.insert name
  -- Read the kernel-checked environment, including private declaration bodies.
  let some info := env.checked.get.find? name
    | throwError "Trusted audit: missing dependency {name}"
  if info.isUnsafe || info.isPartial then
    throwError "Trusted audit: unsafe or partial dependency {name}"
  if info.isAxiom && !allowedAxiom name then
    throwError "Trusted audit: unapproved axiom {name}"
  let mut seen := seen
  for dependency in info.type.getUsedConstants do
    seen ← auditDependency env dependency seen
  if let some value := info.value? (allowOpaque := true) then
    if value.hasSorry then
      throwError "Trusted audit: unfinished proof in {name}"
    for dependency in value.getUsedConstants do
      seen ← auditDependency env dependency seen
  match info with
  | .inductInfo value =>
      for constructor in value.ctors do
        seen ← auditDependency env constructor seen
  | .recInfo value =>
      for rule in value.rules do
        for dependency in rule.rhs.getUsedConstants do
          seen ← auditDependency env dependency seen
  | _ => pure ()
  return seen

elab "#audit_candidate " token:str : command => do
  let env := (← getEnv).setExporting false
  let some implementation := env.checked.get.find? `Generated.candidate
    | throwError "Trusted audit: candidate is missing"
  let some proof := env.checked.get.find? `Generated.candidate_correct
    | throwError "Trusted audit: candidate_correct is missing"
  unless implementation.isDefinition do
    throwError "Trusted audit: candidate must be a definition"
  unless proof.isTheorem do
    throwError "Trusted audit: candidate_correct must be a theorem"
  -- Independent comparison with the fixed contract, in addition to the
  -- rendered theorem declaration and kernel-checked example.
  liftTermElabM do
    let expected := mkApp (mkConst `Generated.Spec) (mkConst `Generated.candidate)
    unless ← isDefEq proof.type expected do
      throwError "Trusted audit: theorem does not prove the original contract"
  for declaration in #[`Generated.candidate, `Generated.candidate_correct] do
    let axioms ← collectAxioms declaration
    for dependency in axioms do
      unless allowedAxiom dependency do
        throwError "Trusted audit: unapproved transitive axiom {dependency}"
    discard <| auditDependency env declaration {}
  logInfo m!"LEAN_VERIFIED_ACCEPTED:{token.getString}"

end Trusted
