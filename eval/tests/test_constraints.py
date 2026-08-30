import copy
import unittest

from eval.easyinput_eval.cases import get_case, load_benchmark_cases
from eval.easyinput_eval.validation import validate_case_output
from eval.tests.helpers import passing_pattern


class CaseConstraintTests(unittest.TestCase):
    def test_known_passing_pattern_for_every_case(self):
        for case in load_benchmark_cases():
            with self.subTest(case=case["caseId"]):
                result = validate_case_output(case, passing_pattern(case["caseId"]))
                self.assertTrue(result.schema_valid, result.errors_as_dicts())
                self.assertTrue(result.constraints_valid, result.errors_as_dicts())
                self.assertTrue(result.edit_policy_valid, result.errors_as_dicts())
                self.assertTrue(result.valid)

    def test_schema_valid_house_can_fail_four_on_floor_constraint(self):
        pattern = passing_pattern("G-HOUSE")
        pattern["tracks"]["kick"][2] = 1
        result = validate_case_output(get_case("G-HOUSE"), pattern)
        self.assertTrue(result.schema_valid)
        self.assertFalse(result.constraints_valid)
        self.assertTrue(result.edit_policy_valid)
        self.assertFalse(result.valid)

    def test_funk_requires_syncopated_kick(self):
        pattern = passing_pattern("G-FUNK")
        pattern["tracks"]["kick"] = [
            1, 0, 0, 0,
            1, 0, 0, 0,
            1, 0, 0, 0,
            1, 0, 0, 0,
        ]
        result = validate_case_output(get_case("G-FUNK"), pattern)
        self.assertTrue(result.schema_valid)
        self.assertFalse(result.constraints_valid)

    def test_house_edit_rejects_change_outside_mutable_cells(self):
        pattern = passing_pattern("E-HOUSE")
        pattern["tracks"]["closed_hat"][0] = 0
        result = validate_case_output(get_case("E-HOUSE"), pattern)
        self.assertTrue(result.schema_valid)
        self.assertTrue(result.constraints_valid)
        self.assertFalse(result.edit_policy_valid)
        self.assertIn("immutable_cell_changed", {issue.code for issue in result.issues})

    def test_funk_edit_rejects_change_to_other_track(self):
        pattern = passing_pattern("E-FUNK")
        pattern["tracks"]["snare"][0] = 1
        result = validate_case_output(get_case("E-FUNK"), pattern)
        self.assertTrue(result.schema_valid)
        self.assertTrue(result.constraints_valid)
        self.assertFalse(result.edit_policy_valid)
        self.assertIn("immutable_field_changed", {issue.code for issue in result.issues})

    def test_country_edit_rejects_change_before_step_13(self):
        pattern = passing_pattern("E-COUNTRY")
        pattern["tracks"]["rim"][7] = 1
        result = validate_case_output(get_case("E-COUNTRY"), pattern)
        self.assertTrue(result.schema_valid)
        self.assertTrue(result.constraints_valid)
        self.assertFalse(result.edit_policy_valid)


if __name__ == "__main__":
    unittest.main()
