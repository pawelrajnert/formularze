"""F-15: sprzątanie szkicu LLM (cleanup.py + poprawki w builderze/enrich)."""
from app.form_builder.builder import FINISH_TEXT, _html, build
from app.form_builder.draft import Draft
from app.rules_check import check


def fields(form):
    def walk(qs):
        for q in qs:
            yield q["field"]
            yield from walk(q["field"]["repeatingSectionGrid"])
    for t in form["tabs"]:
        yield from walk(t["questions"])


def run(*sections, finish_text=""):
    d = Draft.model_validate({"title": "T", "finish_text": finish_text,
                              "pages": [{"title": "Strona", "sections": list(sections)}]})
    notes = []
    form = build(d, notes)
    assert check(form) == []
    llm = {"tabs": form["tabs"][1:-2]}  # bez stron z szablonów (F-14)
    return form, {f["title"] or f["techName"]: f for f in fields(llm)}, notes


def fld(label, type="TEXT_FIELD", **kw):
    return {"label": label, "type": type, **kw}


def test_a_paper_fields_and_sections_dropped():
    _, by, notes = run(
        {"title": "Wniosek", "fields": [fld("Nazwa"), fld("Podpis wnioskodawcy", required=True),
                                        fld("Data złożenia wniosku", "DATEPICKER", required=True),
                                        fld("Miejscowość i data"), fld("Nr sprawy"),
                                        fld("Instrukcja wypełnienia", "TEXT_BLOCK"),
                                        fld("Podstawa prawna", "TEXT_BLOCK"), fld("Podpis i pieczątka")]},
        {"title": "Wypełnia organ", "fields": [fld("Uwagi")]})
    assert set(by) == {"Wniosek", "Nazwa"} and len(notes) == 8


def test_b_finish_always_standard():
    form, _, _ = run({"title": "S", "fields": [fld("A")]}, finish_text="#/$defs/TextBlock RODO ...")
    fin = form["tabs"][-1]["questions"][0]["field"]["repeatingSectionGrid"][0]["field"]
    assert fin["description"] == _html(FINISH_TEXT)


def test_c_statements_become_consents():
    _, by, _ = run({"title": "Oświadczenia", "fields": [
        fld("Oświadczam, że dane są prawdziwe", "CHECKBOX", required=True),
        fld("Wyrażam zgodę na oględziny nieruchomości", "RADIO", options=["Tak", "Nie"]),
        fld("Potwierdzenie", "CHECKBOX")]})
    consents = [f for f in by.values() if f["type"] == "CONSENT_SECTION"]
    assert len(consents) == 3 and all(f["options"] == [] for f in consents)


def test_d_read_only_only_with_value():
    _, by, _ = run({"title": "S", "fields": [
        fld("Powierzchnia (m2)", "NUMBER", read_only=True, required=True),
        fld("Liczba dni", "NUMBER", read_only=True, default="5"),
        fld("Jednostka", read_only=True, default="Koło PZW nr 5"), fld("Pusty", read_only=True)]})
    assert [by[k]["readOnly"] for k in ("Powierzchnia (m2)", "Liczba dni", "Jednostka", "Pusty")] == [False, False, True, False]


def test_e_show_if_by_option_or_unrequired():
    form, by, notes = run(
        {"title": "Zwrot", "fields": [fld("Sposób zwrotu", "RADIO", options=["Gotówką", "Na rachunek"])]},
        {"title": "Rachunek", "show_if": {"field": "Na rachunek", "equals": "Tak"},
         "fields": [fld("Numer rachunku", required=True)]},
        {"title": "Współmałżonek", "show_if": {"field": "Nie ma takiego", "equals": "x"},
         "fields": [fld("Imię małżonka", required=True)]})
    assert "'sposob_zwrotu' in field.techName" in by["Rachunek"]["states"][0]["query"]
    assert by["Imię małżonka"]["validation"] == [] and by["Współmałżonek"]["states"] == []
    assert any("Nie ma takiego" in n for n in notes)


def test_f_choice_types_and_numbers():
    many = [f"D{i}" for i in range(20)]
    _, by, _ = run({"title": "Sposób zwrotu", "fields": [
        fld("Gotówką", "RADIO", options=["Gotówką", "Przelewem"]),
        fld("Załącznik A", "CHECKBOX", options=["TAK", "NIE"]),
        fld("Oznakowanie", "SELECT", options=["Chip", "Tatuaż", "Brak"]),
        fld("Dyscyplina", "RADIO", options=many),
        fld("Kwota opłaty", default="0 zł", read_only=True)]})
    assert by["Sposób zwrotu"]["type"] == "RADIO"  # label == opcja -> tytuł sekcji (sekcja ma inny techName)
    assert by["Załącznik A"]["type"] == "RADIO" and by["Oznakowanie"]["type"] == "RADIO"
    assert by["Dyscyplina"]["type"] == "SELECT" and by["Dyscyplina"]["searchEnabled"] is True
    k = by["Kwota opłaty"]
    assert (k["type"], k.get("defaultValue"), k["readOnly"]) == ("NUMBER", None, False)


def test_f_select_with_dictionary_stays_select():
    _, by, _ = run({"title": "Adres nieruchomości", "fields": [fld("Kraj", "SELECT", options=["Polska", "Niemcy"])]})
    assert by["Kraj"]["dictionaryName"] == "Kraje"


def test_g_text_block_content_from_default():
    _, by, _ = run({"title": "S", "fields": [fld("Pouczenie", "TEXT_BLOCK", default="Treść pouczenia", required=True,
                                                 read_only=True)]})
    tb = next(f for f in by.values() if f["type"] == "TEXT_BLOCK")
    assert "Treść pouczenia" in tb["description"] and "defaultValue" not in tb
    assert (tb["validation"], tb["readOnly"]) == ([], False)


def test_h_prefill_only_for_applicant():
    form, by, _ = run(
        {"title": "Osoba odpowiedzialna", "fields": [fld("Numer telefonu"), fld("Imię", prefill="MLPZ.name")]},
        {"title": "Dane sportowca", "fields": [fld("Nazwisko", prefill="MLPZ.surname")]},
        {"title": "Adres zamieszkania / siedziby", "fields": [fld("Ulica")]},
        {"title": "Wnioskodawca", "fields": [fld("E-mail osoby odpowiedzialnej"), fld("Adres e-mail")]})
    assert all("defaultValueType" not in by[k] for k in ("Numer telefonu", "Imię", "Nazwisko", "E-mail osoby odpowiedzialnej"))
    assert by["E-mail osoby odpowiedzialnej"]["validation"] == ["EMAIL"]
    # F-14: adres i e-mail wnioskodawcy ma szablon; duplikaty od LLM wypadają albo nie dostają drugi raz tego samego prefill
    assert "Adres e-mail" not in by and "defaultValueType" not in by["Ulica"]
    tpl = {f["techName"]: f for f in fields({"tabs": [form["tabs"][0], form["tabs"][-2]]})}
    assert tpl["ulica"]["defaultValue"] == "MLPZ.street" and tpl["adres_e_mail"]["defaultValue"] == "MLPZ.email"
