"""F-08: słowniki, dane inicjalne i walidatory z config/field_rules.yaml."""
from pathlib import Path
from typing import get_args

from app.form_builder.builder import build
from app.form_builder.draft import Dictionary, Draft, DraftField
from app.form_builder.enrich import CFG
from app.rules_check import check

DRAFT1 = Draft.model_validate_json((Path(__file__).resolve().parent / "fixtures" / "draft_form1.json").read_text("utf-8"))


def fields(form):
    def walk(qs):
        for q in qs:
            yield q["field"]
            yield from walk(q["field"]["repeatingSectionGrid"])
    for t in form["tabs"]:
        yield from walk(t["questions"])


def form_of(*flds, title="Sprawa", repeating=False):
    d = Draft.model_validate({"title": "T", "pages": [{"title": "Strona", "sections": [
        {"title": title, "repeating": repeating, "fields": list(flds)}]}]})
    form = build(d)
    assert check(form) == []
    return {f["title"]: f for f in fields({"tabs": form["tabs"][1:-2]})}  # bez stron z szablonów (F-14)


def tf(label, **kw):
    return {"label": label, "type": "TEXT_FIELD", "required": False, **kw}


def test_draft_dictionaries_match_yaml():
    assert set(get_args(Dictionary)) - {""} == set(CFG["dictionaries"])


def test_required_defaults_to_false():
    assert DraftField.model_validate({"label": "A", "type": "TEXT_FIELD"}).required is False


def test_pesel_gets_validator_no_prefill():
    f = form_of(tf("Numer PESEL"))["Numer PESEL"]
    assert f["validation"] == ["PESEL"] and "defaultValueType" not in f
    # F-12 v2: dane inicjalne tylko z szablonu „Twoje dane”; „Data urodzenia” od LLM bywa sportowca -> do wpisania
    f = form_of(tf("Data urodzenia", type="DATEPICKER", prefill="PESEL.birthDate", read_only=True))["Data urodzenia"]
    assert "defaultValueType" not in f and f["readOnly"] is False


def test_kraj_becomes_dictionary_select():
    f = form_of(tf("Kraj"))["Kraj"]
    assert (f["type"], f["dictionaryName"], f["options"], f["defaultValue"]) == ("SELECT", "Kraje", [], ["Polska"])
    assert f["searchEnabled"] is True and "defaultValueType" not in f


def test_email_zip_nip_and_teryt_merge():
    by = form_of(tf("Adres e-mail *"), tf("Kod pocztowy (zagranica)"), tf("NIP"),
                 tf("Województwo"), tf("Powiat"), tf("Gmina"))
    assert by["Adres e-mail *"]["validation"] == ["EMAIL"] and "defaultValue" not in by["Adres e-mail *"]  # MLPZ.email w szablonie
    assert by["Kod pocztowy (zagranica)"]["validation"] == []
    assert by["NIP"]["validation"] == ["NIP"]
    assert by["Województwo"]["dictionaryName"] == "TERYT_4G_DOWODOWY" and by["Województwo"]["multiLevelTree"] is True
    assert "Powiat" not in by and "Gmina" not in by  # jedno drzewo TERYT na sekcję


def test_explicit_draft_settings_win():
    by = form_of(tf("Imię", default="Jan"), tf("PESEL", validators=["NIP"]),
                 {"label": "Kraj", "type": "RADIO", "required": True, "options": ["Polska", "Inny kraj"]},
                 tf("Kontakt", prefill="MLPZ.secondName"), tf("Kraj pochodzenia", dictionary=""),
                 tf("Skąd jesteś", dictionary="Kraje"))
    assert by["Imię"]["defaultValue"] == "Jan" and "defaultValueType" not in by["Imię"]
    assert by["PESEL"]["validation"] == ["PESEL"]  # NIP od LLM bez „nip” w etykiecie odpada (przegląd v5)
    assert by["Kraj"]["type"] == "RADIO" and "dictionaryName" not in by["Kraj"] and len(by["Kraj"]["options"]) == 2
    assert "defaultValue" not in by["Kontakt"]  # jawny prefill szkicu ignorowany (F-12 v2)
    assert by["Skąd jesteś"]["dictionaryName"] == "Kraje"


def test_no_prefill_for_other_persons_or_repeating():
    assert "defaultValueType" not in form_of(tf("Imię"), title="Dane małżonka")["Imię"]
    assert "defaultValueType" not in form_of(tf("Imię"), repeating=True)["Imię"]


def test_form1_fixture_enriched_and_valid():
    form = build(DRAFT1)
    assert check(form) == []
    by = {f["techName"]: f for f in fields(form)}
    assert by["kraj"]["dictionaryName"] == "Kraje" and by["kraj"]["options"] == []
    assert by["kod_pocztowy_zagranica"]["states"][0]["query"].startswith('$not("Polska" in ')
    assert by["imie"]["defaultValue"] == "PESEL.name" and "defaultValueType" not in by["imie_inna_osoba"]  # szablon z wzorca 5
    assert by["adres_e_mail"]["defaultValue"] == "MLPZ.email"
