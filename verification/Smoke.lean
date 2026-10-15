import Solution

def main : IO Unit := do
  for (a, b, expected) in [(0, 0, some 0), (0, 1, none), (8, 3, some 5),
                           (3, 5, none), (5, 5, some 0), (5, 0, some 5)] do
    if candidate a b != expected then
      throw (IO.userError s!"Execution example failed for ({a}, {b})")
  IO.println "EXECUTION_EXAMPLES_PASSED"
