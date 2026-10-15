import Lean

-- This reviewed probe deliberately uses elaboration-time IO. It is submitted
-- directly to the runner; it is not a valid Exercise 2 Proposal body.
def reviewedIsolationProbe : IO Unit := do
  let token ← IO.getEnv "LVA_EX03_FAKE_SECRET"
  if token.isSome then
    throw (IO.userError "host environment secret reached worker")
  if ← System.FilePath.pathExists (System.FilePath.mk {{protected_path}}) then
    throw (IO.userError "protected host file reached worker")
  for target in ["/trusted/lakefile.toml", "/input/Candidate.lean"] do
    let writable ← try
      IO.FS.writeFile target "must not write"
      pure true
    catch _ => pure false
    if writable then
      throw (IO.userError s!"protected file was writable: {target}")
  let memory ← IO.FS.readFile "/sys/fs/cgroup/memory.max"
  let pids ← IO.FS.readFile "/sys/fs/cgroup/pids.max"
  if memory.trimAscii.toString != "536870912" || pids.trimAscii.toString != "64" then
    throw (IO.userError "memory/process cgroup limits were not enforced")
  let status ← IO.FS.readFile "/proc/self/status"
  if !(status.splitOn "\n").any (· == "NoNewPrivs:\t1") then
    throw (IO.userError "no-new-privileges was not enforced")
  let network ← IO.FS.readFile "/proc/net/dev"
  if (network.splitOn "\n").any (fun line => line.contains ':' && (line.splitOn ":").head!.trimAscii.toString != "lo") then
    throw (IO.userError "worker has a network interface beyond loopback")
  IO.println "isolation checks passed"

#eval reviewedIsolationProbe
