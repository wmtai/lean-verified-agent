/-
Frontend for the pinned upstream Comparator implementation. ComparatorDriver is
generated from upstream Main.lean with only its CLI main function removed.
No candidate source or olean file is imported into this verification process.
-/
import ComparatorDriver

def checkContext : Comparator.Context := {
  projectDir := "/tmp"
  challengeModule := `Challenge
  solutionModule := `Solution
  theoremNames := #[`candidate_correct]
  definitionNames := #[`candidate]
  legalAxioms := #[`propext, `Quot.sound, `Classical.choice]
  leanPrefix := "/opt/lean"
  gitLocation := "/unused"
  whichLandrun := "/unused"
  whichLean4Export := "/unused"
  externalKernels := {}
}

def main (args : List String) : IO UInt32 := do
  if args == ["--targets"] then
    let targets ← ReaderT.run (do
      return (← Comparator.builtinTargets) ++ (← Comparator.getTheoremNames)
        ++ (← Comparator.getLegalAxioms) ++ (← Comparator.primitiveTargets)
        ++ (← Comparator.getDefinitionNames)) checkContext
    for target in targets do
      IO.println target
    return 0
  if args != ["--verify"] then
    IO.eprintln "Expected --verify or --targets"
    return 2
  let challenge ← IO.FS.readFile "/trusted/challenge.ndjson"
  let solution ← IO.FS.readFile "/input/solution.ndjson"
  try
    ReaderT.run (Comparator.verifyMatch challenge solution) checkContext
    IO.println "COMPARATOR_ACCEPTED"
    return 0
  catch error =>
    IO.eprintln error
    return 1
