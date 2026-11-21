"""F-09: deterministyczne dopisywanie typowych zależności (show_if) w post-processingu szkicu."""
from app.form_builder.builder import build
from app.form_builder.draft import Draft
from app.form_builder.draft_postprocess import postprocess
from app.rules_check import check


def f(label, type="TEXT_FIELD", options=None, show_if=None):
    return {"label": label, "type": type, "required": False, "options": options or [], "show_if": show_if}


def run(sections):
    d = Draft.model_validate({"title": "Wniosek o test", "pages": [{"title": "Dane", "sections": sections}]})
    warnings = []
    out = postprocess(d, [], warnings)
    assert check(build(out)) == []
    return out, warnings


def fields(draft):
    return {x.label: x for p in draft.pages for s in p.sections for x in s.fields}


def test_if_yes_links_to_previous_yes_no():
    out, w = run([{"title": "Pies", "fields": [
        f("Czy pies był szczepiony?", "RADIO", ["Tak", "Nie"]),
        f("Jeśli tak, podaj datę szczepienia", "DATEPICKER"),
        f("Jeżeli nie, podaj powód"),
    ]}])
    fs = fields(out)
    assert fs["Jeśli tak, podaj datę szczepienia"].show_if.equals == "Tak"
    assert fs["Jeżeli nie, podaj powód"].show_if.equals == "Nie"
    assert any("Dodano warunek" in x for x in w)


def test_poland_abroad_address():
    out, _ = run([{"title": "Adres", "fields": [
        f("Kraj", "SELECT", ["Polska", "Inny kraj"]),
        f("Województwo"), f("Kod pocztowy"), f("Kod pocztowy (zagranica)"), f("Miejscowość"),
    ]}])
    fs = fields(out)
    assert fs["Województwo"].show_if.equals == "Polska"
    assert fs["Kod pocztowy"].show_if.equals == "Polska"
    assert fs["Kod pocztowy (zagranica)"].show_if.equals == "Inny kraj"
    assert fs["Miejscowość"].show_if is None


def test_whose_sections():
    out, _ = run([
        {"title": "Podmiot wniosku", "fields": [
            f("Wybierz, w czyim imieniu wnioskujesz", "RADIO",
              ["Swoim", "Innej osoby", "Osoby prawnej lub jednostki organizacyjnej"])]},
        {"title": "Dane innej osoby", "fields": [f("Imię")]},
        {"title": "Dane podmiotu", "fields": [f("Nazwa")]},
        {"title": "Twoje dane", "fields": [f("Nazwisko")]},
    ])
    secs = {s.title: s for s in out.pages[0].sections}
    assert secs["Dane innej osoby"].show_if.equals == "Innej osoby"
    assert secs["Dane podmiotu"].show_if.equals == "Osoby prawnej lub jednostki organizacyjnej"
    assert secs["Twoje dane"].show_if is None


def test_llm_conditions_not_overwritten():
    out, _ = run([{"title": "Adres", "fields": [
        f("Kraj", "SELECT", ["Polska", "Inny kraj"]),
        f("Typ", "RADIO", ["A", "B"]),
        f("Kod pocztowy", show_if={"field": "Typ", "equals": "A"}),
    ]}])
    assert fields(out)["Kod pocztowy"].show_if.field == "Typ"


def test_no_yes_no_question_no_condition():
    out, _ = run([{"title": "S", "fields": [f("Jeśli tak, podaj numer")]}])
    assert fields(out)["Jeśli tak, podaj numer"].show_if is None
