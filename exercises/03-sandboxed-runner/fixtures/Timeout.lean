import Lean

-- Reviewed resource test: the worker must stop this sleeping elaboration.
#eval IO.sleep 60000
