import unittest

from agent.schema import Budget, Candidate


class CandidateContractTests(unittest.TestCase):
    def test_extra_fields_cannot_supply_a_replacement_specification(self):
        with self.assertRaisesRegex(ValueError, "exactly"):
            Candidate.parse('{"implementation":"0","proof":"by rfl","specification":"True"}')

    def test_non_string_empty_and_oversized_payloads_are_rejected(self):
        for value in ('{"implementation":0,"proof":"by rfl"}',
                      '{"implementation":"0","proof":""}',
                      '{"implementation":"' + "x" * 65537 + '","proof":"by rfl"}'):
            with self.subTest(value=value[:50]), self.assertRaises(ValueError):
                Candidate.parse(value)

    def test_invalid_budgets_fail_before_running_a_model(self):
        with self.assertRaises(ValueError):
            Budget(max_calls=0)
        for seconds in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(seconds=seconds), self.assertRaisesRegex(ValueError, "finite"):
                Budget(max_seconds=seconds)


if __name__ == "__main__":
    unittest.main()
