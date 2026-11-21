import json
from pathlib import Path

import pytest

from app.form_builder.builder import build, slug
from app.form_builder.draft import Draft, DraftPage, DraftSection
from app.rules_check import check

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "draft_form1.json"
DRAFT1 = Draft.model_validate_json(FIXTURE.read_text("utf-8"))


def fields(form, tabs=slice(None)):
    def walk(qs):
        for q in qs:
            yield q["field"]
            yield from walk(q["field"]["repeatingSectionGrid"])
    for t in form["tabs"][tabs]:
        yield from walk(t["questions"])


LLM = slice(1, -2)  # strony merytoryczne; [0] „Dane” i [-2] „Kontakt i zgody” są z szablonów (F-14)


def mini(*sections, pages=None):
    return Draft.model_validate({"title": "T", "pages": pages or [{"title": "Strona", "sections": list(sections)}]})


def test_fixture_passes_rules_check():
    form = build(DRAFT1)
    assert check(form) == []
    assert [t["type"] for t in form["tabs"]] == ["MAIN", "MAIN", "MAIN", "FINISH"]
    assert len(form["flow"]["links"]) == 3


def test_ids_unique_and_tech_names_unique():
    form = build(DRAFT1)
    ids = [t["id"] for t in form["tabs"]] + [f["id"] for f in fields(form)] + [l["id"] for l in form["flow"]["links"]]
    assert len(ids) == len(set(ids))
    names = [f["techName"] for f in fields(form)]
    assert len(names) == len(set(names))


def test_show_if_gives_states():
    form = build(DRAFT1.model_copy(update={"applicant_kinds": ["osoba", "firma"]}))
    by = {f["techName"]: f for f in fields(form)}
    assert by["wybierz_jako_kto_wnioskujesz"]["states"] == [{"type": "SHOW", "query":
        "(\"Osoby prawnej lub jednostki organizacyjnej\" in tabs['Dane' in title].questions['podmiot_wniosku' in field.techName]"
        ".field.repeatingSectionGrid['wybierz_w_czyim_imieniu_wnioskujesz' in field.techName].field.__userAnswer)"}]
    assert by["dane_innej_osoby"]["states"]  # warunek na sekcji z szablonu
    # powtórzony label "Kraj" w szkicu LLM: rozwiązywany najpierw w obrębie własnej sekcji
    adres = lambda t: {"title": t, "fields": [
        {"label": "Kraj", "type": "SELECT", "options": ["Polska", "Inny kraj"], "default": "Polska"},
        {"label": "Kod pocztowy", "type": "TEXT_FIELD", "show_if": {"field": "Kraj", "equals": "Polska"}}]}
    by = {f["techName"]: f for f in fields(build(mini(adres("Adres nieruchomości"), adres("Adres działki"))), LLM)}
    assert "'adres_dzialki' in field.techName].field.repeatingSectionGrid['kraj_3'" in by["kod_pocztowy_3"]["states"][0]["query"]


def test_unknown_show_if_label_is_skipped():
    d = mini({"title": "S", "fields": [{"label": "A", "type": "TEXT_FIELD", "required": False,
                                        "show_if": {"field": "Nie ma", "equals": "x"}}]})
    form = build(d)
    assert check(form) == [] and form["tabs"][1]["questions"][0]["field"]["repeatingSectionGrid"][0]["field"]["states"] == []


def test_tech_name_collision_and_slug():
    assert slug("Źródło łąki, część 1!") == "zrodlo_laki_czesc_1"
    f = lambda: {"label": "Imię", "type": "TEXT_FIELD", "required": True}
    form = build(mini({"title": "Imię", "fields": [f(), f()]}))
    assert [x["techName"] for x in fields(form, LLM)] == ["imie_2", "imie_3", "imie_4"]  # "imie" ma szablon „Twoje dane”
    assert next(fields(form, LLM))["repeatingSectionGrid"][0]["field"]["validation"] == ["REQUIRED"]


def test_repeating_section_and_validators():
    form = build(mini({"title": "Współwłaściciele", "repeating": True, "fields": [
        {"label": "PESEL", "type": "TEXT_FIELD", "required": False, "validators": ["PESEL"]}]}))
    sec = form["tabs"][1]["questions"][0]["field"]
    assert check(form) == [] and sec["type"] == "REPEATING_SECTION"
    assert sec["repeatingSectionGrid"][0]["field"]["validation"] == ["PESEL"]


def test_empty_page_skipped_and_empty_draft_raises():
    d = mini({"title": "S", "fields": [{"label": "A", "type": "TEXT_FIELD", "required": False}]})
    d.pages.append(DraftPage.model_construct(title="Pusta", sections=[DraftSection.model_construct(title="X", fields=[])]))
    form = build(d)
    assert check(form) == [] and [t["title"] for t in form["tabs"]] == ["Dane", "Strona", "Kontakt i zgody", "Strona końcowa"]
    with pytest.raises(ValueError):
        build(Draft.model_construct(title="T", pages=[d.pages[1]], finish_text=""))


def test_cli(capsys, monkeypatch):
    import runpy, sys
    monkeypatch.setattr(sys, "argv", ["builder", str(FIXTURE)])
    runpy.run_module("app.form_builder.builder", run_name="__main__")
    assert check(json.loads(capsys.readouterr().out)) == []
