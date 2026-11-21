"""F-19: zgodność z importerem COI — oryginalny importowanyPlikJsonSchemat + klucze jak we wzorcach 1/5."""
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from app.form_builder.builder import build
from tests.test_builder import DRAFT1

ROOT = Path(__file__).resolve().parent.parent
ORIGINAL = Draft202012Validator(json.loads(next(ROOT.glob("data/Materiały*/*/importowanyPlikJsonSchemat*.json")).read_text("utf-8")))
EXAMPLES = [json.loads(p.read_text("utf-8")) for p in sorted(ROOT.glob("data/[15]/*/konfiguracja_form_*.json"))]
RESULTS = {p.name: json.loads(p.read_text("utf-8")) for p in sorted((ROOT / "wyniki").glob("*.json"))}
# klucze spoza wzorców, ale z tabel komponentów w „Regułach technicznych” (pola słownikowe, zgody, dane inicjalne)
RULES_EXTRA = {"field": {"dictionaryName", "multiLevelTree", "searchEnabled", "defaultValue", "defaultValueType",
                         "consentSectionConfig"}}


def _questions(qs):
    for q in qs:
        yield q
        yield from _questions(q["field"].get("repeatingSectionGrid") or [])


def keys(form: dict) -> dict[str, set]:
    k = {"root": set(form), "tab": set(), "question": set(), "field": set(), "option": set(), "state": set(), "link": set()}
    for t in form["tabs"]:
        k["tab"] |= set(t)
        for q in _questions(t["questions"]):
            k["question"] |= set(q)
            k["field"] |= set(q["field"])
            for o in q["field"].get("options") or []:
                k["option"] |= set(o)
            for s in q["field"].get("states") or []:
                k["state"] |= set(s)
    for link in form["flow"]["links"]:
        k["link"] |= set(link)
    return k


ALLOWED = {kind: set().union(*(keys(e)[kind] for e in EXAMPLES)) | RULES_EXTRA.get(kind, set()) for kind in keys(EXAMPLES[0])}
FORMS = {"builder_form1": build(DRAFT1)} | RESULTS


@pytest.mark.parametrize("name", FORMS)
def test_original_schema(name):
    assert [e.message for e in ORIGINAL.iter_errors(FORMS[name])] == []


@pytest.mark.parametrize("name", FORMS)
def test_only_keys_known_from_examples_and_rules(name):
    extra = {kind: sorted(v - ALLOWED[kind]) for kind, v in keys(FORMS[name]).items() if v - ALLOWED[kind]}
    assert extra == {}


@pytest.mark.parametrize("name", FORMS)
def test_number_without_default_value(name):
    """Reguły techniczne: komponent NUMBER nie ma defaultValue."""
    fs = [q["field"] for t in FORMS[name]["tabs"] for q in _questions(t["questions"])]
    assert [f["techName"] for f in fs if f["type"] == "NUMBER" and "defaultValue" in f] == []
