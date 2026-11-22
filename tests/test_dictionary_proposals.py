"""F-10: propozycje nowych słowników z list wyboru w formularzach."""
import json
from pathlib import Path

from app.form_builder.dictionary_proposals import analyze, choice_lists, propose_dictionaries, propose_for_form

ROOT = Path(__file__).resolve().parent.parent


def field(tech, title, options, type_="RADIO", **kw):
    return {"type": type_, "techName": tech, "title": title,
            "options": [{"id": o, "name": o, "techName": o} for o in options], **kw}


def form(title, *fields):
    return {"title": title, "tabs": [{"title": "Krok", "questions": [{"title": "Sekcja", "fields": list(fields)}]}]}


def test_skips_yes_no_templates_and_existing_dictionaries():
    f = form("A",
             field("x", "Czy?", ["Tak", "Nie"]),
             field("wybierz_w_czyim_imieniu_wnioskujesz", "W czyim imieniu", ["Swoim", "Innej osoby", "Firmy"]),
             field("kraj", "Kraj", [], "SELECT", dictionaryName="Kraje"),
             field("woj", "Województwo", ["mazowieckie", "śląskie", "pomorskie"], "SELECT"),
             field("rodzaj", "Rodzaj pojazdu", ["osobowy", "ciężarowy", "motocykl"], "SELECT"))
    assert [c["techName"] for c in choice_lists(f, "1")] == ["rodzaj"]


def test_groups_similar_lists_across_forms():
    a = form("Wniosek A", field("zwrot", "Wybierz sposób zwrotu opłaty", ["Gotówką w kasie organu", "Przelewem na rachunek bankowy"]))
    b = form("Wniosek B", field("nadplata", "Co zrobić z nadpłatą",
                                ["Zaliczyć na poczet zobowiązania", "Zwrócić przelewem na rachunek bankowy"]))
    [p] = propose_dictionaries([a, b], ["2", "5"])
    assert p["nazwa"] == "SPOSOB_ZWROTU_OPLATY"
    assert p["pewnosc"] == "wysoka"
    assert len(p["pozycje"]) == 3
    assert {w["formularz"] for w in p["wystapienia"]} == {"2", "5"}
    assert all(set(x) == {"kod", "nazwa"} for x in p["pozycje"])


def test_single_short_list_is_only_a_candidate():
    f = form("A", field("typ", "Typ zajęcia", ["Jezdnia do 20% szerokości", "Jezdnia powyżej 50% szerokości", "Chodnik"]))
    proposals, remaining = analyze([f], ["6"])
    assert proposals == []
    # opcje z jednego pola nie scalają się mimo podobieństwa
    assert remaining[0]["liczbaPozycji"] == 3


def test_long_list_and_repeated_field_qualify():
    sports = ["hokej", "karate", "kolarstwo", "koszykówka", "piłka nożna", "piłka ręczna"]
    f = form("Klub", field("dyscypliny", "Dyscypliny sportowe (wybierz wszystkie)", sports, "CHECKBOX"),
             field("ozn", "Sposób oznakowania psa", ["mikroprocesor", "tatuaż", "brak"]),
             field("ozn_2", "Sposób oznakowania psa", ["mikroprocesor", "tatuaż", "brak"]))
    names = {p["nazwa"]: p for p in propose_for_form(f, "9")}
    assert set(names) == {"DYSCYPLINY_SPORTOWE", "SPOSOB_OZNAKOWANIA_PSA"}
    assert len(names["DYSCYPLINY_SPORTOWE"]["pozycje"]) == 6
    assert len(names["SPOSOB_OZNAKOWANIA_PSA"]["wystapienia"]) == 2
    assert names["DYSCYPLINY_SPORTOWE"]["pozycje"][4] == {"kod": "PILKA_NOZNA", "nazwa": "piłka nożna"}


def test_deterministic_on_real_results():
    files = sorted((ROOT / "wyniki").glob("[0-9]*.json"))
    forms = [json.loads(p.read_text("utf-8")) for p in files]
    ids = [p.stem for p in files]
    first = propose_dictionaries(forms, ids)
    assert first == propose_dictionaries(forms, ids)
    assert 1 <= len(first) <= 6
    assert len({p["nazwa"] for p in first}) == len(first)
