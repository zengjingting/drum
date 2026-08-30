import copy

from eval.easyinput_eval.cases import get_case


def passing_pattern(case_id: str):
    if case_id == "G-HOUSE":
        return copy.deepcopy(get_case("E-HOUSE")["currentPattern"])
    if case_id == "G-FUNK":
        return copy.deepcopy(get_case("E-FUNK")["currentPattern"])
    if case_id == "G-COUNTRY":
        return copy.deepcopy(get_case("E-COUNTRY")["currentPattern"])
    if case_id == "E-HOUSE":
        pattern = copy.deepcopy(get_case(case_id)["currentPattern"])
        for step in (3, 7, 11, 15):
            pattern["tracks"]["closed_hat"][step - 1] = 0
            pattern["tracks"]["open_hat"][step - 1] = 1
        return pattern
    if case_id == "E-FUNK":
        pattern = copy.deepcopy(get_case(case_id)["currentPattern"])
        pattern["tracks"]["kick"] = [
            1, 0, 0, 1,
            0, 0, 0, 0,
            1, 0, 0, 0,
            0, 0, 1, 0,
        ]
        return pattern
    if case_id == "E-COUNTRY":
        pattern = copy.deepcopy(get_case(case_id)["currentPattern"])
        pattern["tracks"]["kick"][15] = 1
        pattern["tracks"]["snare"][13] = 1
        pattern["tracks"]["rim"][14] = 1
        return pattern
    raise KeyError(case_id)
