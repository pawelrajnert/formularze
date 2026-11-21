import copy
import json
from pathlib import Path

import pytest

from app.rules_check import check

DATA = Path(__file__).resolve().parent.parent / "data"
EX1 = json.loads(next(DATA.glob("1/*/konfiguracja_form_*.json")).read_text("utf-8"))
EX5 = json.loads(next(DATA.glob("5/*/konfiguracja_form_*.json")).read_text("utf-8"))


def fixed(form):
    """Przykłady COI mają 3 znane odstępstwa od reguł (zob. raport F-05, F-17) - naprawiamy je tu jawnie."""
    form = copy.deepcopy(form)
    fin = form["tabs"][-1]["questions"][0]["field"]  # F-17: SECTION + TEXT_BLOCK -> INFO_SECTION
    fin.update(type="INFO_SECTION", description=fin["repeatingSectionGrid"][0]["field"]["description"], repeatingSectionGrid=[])
    for i, link in enumerate(form["flow"]["links"]):  # przykład 5: id przejść typu "a16ec" zamiast UUID
        if len(link["id"]) != 36:
            link["id"] = f"00000000-0000-4000-8000-{i:012d}"
    def walk(qs):
        for q in qs:
            if q["field"].get("validation") == {}:  # przykład 1: "validation": {} zamiast []
                q["field"]["validation"] = []
            walk(q["field"].get("repeatingSectionGrid") or [])
    for t in form["tabs"]:
        walk(t["questions"])
    return form


def test_examples_known_deviations():
    e1, e5 = check(EX1), check(EX5)
    finish = "na stronie FINISH dozwolona wyłącznie INFO_SECTION"
    assert len(e1) == 4 and all("'validation' musi być listą" in e or finish in e for e in e1)
    assert len(e5) == 4 and all(e.startswith("flow.links[") and "nie jest UUID" in e or finish in e for e in e5)


@pytest.mark.parametrize("form", [EX1, EX5])
def test_examples_ok_after_fix(form):
    assert check(fixed(form)) == []


def broken(mutate):
    form = fixed(EX5)
    mutate(form)
    return check(form)


def first_leaf(form):
    return form["tabs"][0]["questions"][0]["field"]["repeatingSectionGrid"][0]


def test_no_finish():
    errs = broken(lambda f: f["tabs"].pop())
    assert any("type FINISH" in e for e in errs)


def test_finish_only_info_section():
    errs = broken(lambda f: f["tabs"][-1]["questions"].append(copy.deepcopy(f["tabs"][0]["questions"][0])))
    assert any("dozwolona wyłącznie INFO_SECTION, jest SECTION" in e for e in errs)


def test_single_tab():
    errs = broken(lambda f: f.update(tabs=f["tabs"][-1:]))
    assert any("min. 2 strony" in e for e in errs)


def test_field_outside_section():
    errs = broken(lambda f: f["tabs"][0]["questions"].append(copy.deepcopy(first_leaf(f))))
    assert any("musi być w SECTION" in e for e in errs)


def test_nested_section():
    def m(f):
        first_leaf(f)["field"] = copy.deepcopy(f["tabs"][1]["questions"][0]["field"])
    assert any("zagnieżdżona w innej sekcji" in e for e in broken(m))


def test_bad_uuid():
    errs = broken(lambda f: first_leaf(f)["field"].update(id="123"))
    assert any("'123' nie jest UUID" in e for e in errs)


def test_duplicate_id():
    def m(f):
        f["tabs"][1]["questions"][0]["field"]["id"] = f["tabs"][0]["questions"][0]["field"]["id"]
    assert any("powtarza się" in e for e in broken(m))


def test_dictionary_on_text_field():
    def m(f):
        leaf = first_leaf(f)["field"]
        leaf.update(type="TEXT_FIELD", dictionaryName="Kraje", options=[])
    assert any("słownik dozwolony tylko" in e for e in broken(m))


def test_input_on_finish():
    def m(f):
        f["tabs"][-1]["questions"][0]["field"]["type"] = "TEXT_FIELD"
    assert any("FINISH niedozwolone pole wejściowe" in e for e in broken(m))


def test_missing_validation():
    errs = broken(lambda f: first_leaf(f)["field"].pop("validation"))
    assert any("obligatoryjności" in e for e in errs)


def test_bad_state():
    errs = broken(lambda f: first_leaf(f)["field"].update(states=[{"type": "HIDE", "query": "x"}]))
    assert any("typ stanu" in e for e in errs)


def test_long_title():
    assert any("max 255" in e for e in broken(lambda f: f.update(title="x" * 256)))


def test_broken_flow():
    errs = broken(lambda f: f["flow"]["links"].pop(1))
    assert any("nie prowadzi żadne przejście" in e for e in errs)


def test_schema_type_error():
    assert any(e.startswith("schemat:") for e in broken(lambda f: f.update(tabs="nie-lista")))
