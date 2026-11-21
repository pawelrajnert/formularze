"""F-14: strony „Dane” i „Kontakt i zgody” z szablonów (N-C1) wg pól sterujących szkicu."""
import re
from pathlib import Path

import pytest

from app.form_builder.builder import _Builder, build
from app.form_builder.draft import Draft
from app.rules_check import check

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "draft_form1.json"
OPT = {"osoba": "Swoim", "inna_osoba": "Innej osoby", "firma": "Osoby prawnej lub jednostki organizacyjnej"}


def fields(qs):
    for q in qs:
        yield q["field"]
        yield from fields(q["field"]["repeatingSectionGrid"])


def make(**ctrl):
    """Szkic z jedną stroną merytoryczną + pola sterujące."""
    d = Draft.model_validate({"title": "Wniosek o X", **ctrl, "pages": [{"title": "Przedmiot wniosku", "sections": [
        {"title": "Działka", "fields": [{"label": "Numer działki", "type": "TEXT_FIELD", "required": True}]}]}]})
    notes = []
    form = build(d, notes)
    assert check(form) == []
    return form, {f["techName"]: f for f in fields(form["tabs"][0]["questions"])}, notes


VARIANTS = [
    {}, {"organ": "Wójt Gminy Elbląg"}, {"applicant_kinds": ["osoba"], "proxy_allowed": False},
    {"applicant_kinds": ["osoba", "firma", "inna_osoba"]}, {"applicant_kinds": ["firma"], "proxy_allowed": False},
    {"applicant_kinds": ["inna_osoba"], "fee_info": "10 zł za wydanie zaświadczenia"},
    {"applicant_kinds": ["osoba", "firma"], "fee_info": "17 zł za pełnomocnictwo"},
]


@pytest.mark.parametrize("ctrl", VARIANTS)
def test_structure_ids_and_references(ctrl):
    form, dane, _ = make(**ctrl)
    tabs = form["tabs"]
    assert [t["title"] for t in tabs] == ["Dane", "Przedmiot wniosku", "Kontakt i zgody", "Strona końcowa"]
    assert [t["type"] for t in tabs] == ["MAIN", "MAIN", "MAIN", "FINISH"]
    all_f = [f for t in tabs for f in fields(t["questions"])]
    ids = [t["id"] for t in tabs] + [f["id"] for f in all_f]
    names = [f["techName"] for f in all_f]
    assert len(ids) == len(set(ids)) and len(names) == len(set(names))
    # każde odwołanie w JSONacie wskazuje istniejące pole
    refs = {m for f in all_f for s in f["states"] for m in re.findall(r"'([a-z0-9_]+)' in field\.techName", s["query"])}
    assert refs <= set(names)
    kontakt = {f["techName"] for f in fields(tabs[2]["questions"])}
    assert {"dane_do_kontaktu", "numer_telefonu", "adres_e_mail", "zgoda"} <= kontakt
    assert "klauzul" in next(f for f in fields(tabs[2]["questions"]) if f["type"] == "CONSENT_SECTION")[
        "consentSectionConfig"]["consents"][0]["description"]


def test_organ_only_with_value():
    _, dane, _ = make(organ="Wójt Gminy Elbląg")
    assert dane["nazwa_organu"]["defaultValue"] == "Wójt Gminy Elbląg" and dane["nazwa_organu"]["readOnly"] is True
    _, dane, _ = make()
    assert "nazwa_organu" not in dane and "organ_do_ktorego_jest_skladany_wniosek" not in dane


def test_only_person_without_proxy_has_no_radio():
    _, dane, _ = make(applicant_kinds=["osoba"], proxy_allowed=False)
    assert {"twoje_dane", "numer_pesel", "adres_zamieszkania", "kraj"} <= set(dane)
    assert not {"podmiot_wniosku", "wybierz_w_czyim_imieniu_wnioskujesz", "dane_innej_osoby", "dane_podmiotu",
                "pelnomocnictwo"} & set(dane)


def test_person_with_proxy_gets_other_person_path():
    _, dane, _ = make(applicant_kinds=["osoba"])
    radio = dane["wybierz_w_czyim_imieniu_wnioskujesz"]
    assert [o["name"] for o in radio["options"]] == ["Swoim", "Innej osoby"]
    assert dane["pelnomocnictwo"]["states"] and dane["dane_innej_osoby"]["states"]
    # bez firmy: RADIO „jako kto” i opłata za pełnomocnictwo podmiotu znikają
    assert not {"wybierz_jako_kto_wnioskujesz", "dane_podmiotu", "oplata_skarbowa_pelnomocnictwo_2"} & set(dane)


def test_all_kinds_like_pattern():
    _, dane, _ = make(applicant_kinds=["osoba", "firma", "inna_osoba"])
    assert [o["name"] for o in dane["wybierz_w_czyim_imieniu_wnioskujesz"]["options"]] == list(OPT.values())
    assert [o["name"] for o in dane["wybierz_jako_kto_wnioskujesz"]["options"]] == ["Pełnomocnik", "Reprezentant"]
    assert {"dane_podmiotu", "numer_krs", "adres_siedziby", "oplata_skarbowa_pelnomocnictwo_1",
            "oplata_skarbowa_pelnomocnictwo_2"} <= set(dane)
    assert "Wniosek o X – opłata skarbowa" in dane["oplata_info_1"]["description"]


def test_single_kind_is_unconditional():
    _, dane, _ = make(applicant_kinds=["firma"], proxy_allowed=False)
    assert "podmiot_wniosku" not in dane and "pelnomocnictwo" not in dane and "dane_innej_osoby" not in dane
    assert dane["dane_podmiotu"]["states"] == [] and dane["adres_siedziby"]["states"] == []
    _, dane, _ = make(applicant_kinds=["inna_osoba"], proxy_allowed=False)
    assert dane["dane_innej_osoby"]["states"] == [] and "dane_podmiotu" not in dane


def test_fee_toggle():
    _, dane, _ = make(fee_info="Opłata 10 zł za wydanie zaświadczenia")
    assert "10 zł za wydanie" in dane["oplata_skarbowa_info"]["description"] and dane["oplata_skarbowa"]["states"] == []
    _, dane, _ = make()
    assert "oplata_skarbowa" not in dane
    _, dane, _ = make(fee_info="17 zł za pełnomocnictwo")  # już jest w bloku pełnomocnictwa
    assert "oplata_skarbowa" not in dane and "oplata_skarbowa_pelnomocnictwo_1" in dane
    _, dane, _ = make(proxy_allowed=False)
    assert not {"pelnomocnictwo", "oplata_skarbowa_pelnomocnictwo_1"} & set(dane)


def test_insert_renames_and_remaps_on_collision():
    b = _Builder()
    b.names |= {"podmiot_wniosku", "wybierz_w_czyim_imieniu_wnioskujesz"}  # np. już zajęte przez pole LLM
    dane, _ = b.standard(Draft.model_validate({"title": "T", "pages": [{"title": "P", "sections": [
        {"title": "S", "fields": [{"label": "A", "type": "TEXT_FIELD"}]}]}]}))
    q = next(f for f in fields(dane) if f["techName"] == "dane_innej_osoby")["states"][0]["query"]
    assert "'podmiot_wniosku_2' in field.techName" in q and "'wybierz_w_czyim_imieniu_wnioskujesz_2' in" in q


def test_legacy_draft_standard_blocks_filtered():
    """Szkic starego promptu (formularz 1 z danymi wnioskodawcy) -> jak wzorzec 1: Dane / budynek / Kontakt / FINISH."""
    notes = []
    form = build(Draft.model_validate_json(FIXTURE.read_text("utf-8")), notes)
    assert check(form) == []
    assert [t["title"] for t in form["tabs"]] == ["Dane", "Informacje o budynku", "Kontakt i zgody", "Strona końcowa"]
    dane = {f["techName"]: f for f in fields(form["tabs"][0]["questions"])}
    assert dane["nazwa_organu"]["defaultValue"].startswith("Wójt Gminy Elbląg")  # organ przeniesiony z pola LLM
    assert sum("dubluje sekcję standardową" in n for n in notes) == 14


def test_dedupe_fields_in_mixed_sections():
    d = Draft.model_validate({"title": "T", "pages": [
        {"title": "Dane", "sections": [{"title": "Dane wnioskodawcy", "fields": [
            {"label": "Imię i nazwisko", "type": "TEXT_FIELD"}, {"label": "Adres e-mail", "type": "TEXT_FIELD"},
            {"label": "Numer gospodarstwa", "type": "TEXT_FIELD"}]}]},
        {"title": "Zgody", "sections": [{"title": "Oświadczenia", "fields": [
            {"label": "Wyrażam zgodę na przetwarzanie moich danych osobowych", "type": "CONSENT_SECTION"},
            {"label": "Imię pełnomocnika", "type": "TEXT_FIELD"}]}]}]})
    notes = []
    form = build(d, notes)
    assert check(form) == []
    # strona „Zgody” pusta -> out; LLM-owa „Dane” przemianowana (unikalny tytuł dla JSONaty)
    assert [t["title"] for t in form["tabs"]] == ["Dane", "Dane (cd.)", "Kontakt i zgody", "Strona końcowa"]
    assert [f["title"] for f in fields(form["tabs"][1]["questions"])] == ["Dane wnioskodawcy", "Numer gospodarstwa"]
    assert len([n for n in notes if "dubluje" in n]) == 4
