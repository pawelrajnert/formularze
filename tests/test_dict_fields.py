"""R-15: oficjalne słowniki COI w części merytorycznej (TERYT, Kraje, Numery kierunkowe)."""
from app.form_builder.builder import build
from app.form_builder.draft import Draft
from app.rules_check import check


def _form(*sections):
    return build(Draft.model_validate({"title": "Wniosek o test", "pages": [{"title": "Strona", "sections": list(sections)}]}))


def _fields(form):
    def walk(qs):
        for q in qs:
            yield q["field"]
            yield from walk(q["field"].get("repeatingSectionGrid") or [])
    return [f for t in form["tabs"][1:-2] for f in walk(t["questions"])]


def test_address_with_country_gets_teryt_for_poland_and_text_abroad():
    form = _form({"title": "Adres", "fields": [{"label": "Adres zamieszkania współmałżonka", "type": "TEXT_FIELD", "required": True}]})
    assert check(form) == []
    by = {f["title"]: f for f in _fields(form)}
    assert by["Kraj"]["dictionaryName"] == "Kraje"
    m, ma = by["Miejscowość"], by["Miejscowość (za granicą)"]
    assert m["type"] == "SELECT" and m["dictionaryName"] == "TERYT_4G_DOWODOWY" and m["options"] == []
    assert '"Polska" in' in m["states"][0]["query"]                 # pokazuje się przy Polsce
    assert "$not(" in ma["states"][0]["query"] and "dictionaryName" not in ma  # za granicą: tekst
    assert "REQUIRED" in ma["validation"] and "ZIP_CODE" not in by["Kod pocztowy (za granicą)"]["validation"]


def test_polish_only_town_gets_teryt():
    form = _form({"title": "Szczegóły wynajmu", "fields": [{"label": "Miejscowość świetlicy", "type": "TEXT_FIELD", "required": True}]})
    f = next(x for x in _fields(form) if x["title"] == "Miejscowość świetlicy")
    assert f["type"] == "SELECT" and f["dictionaryName"] == "TERYT_4G_DOWODOWY" and check(form) == []


def test_phone_gets_area_code_once():
    form = _form({"title": "Osoba odpowiedzialna", "fields": [
        {"label": "Imię osoby odpowiedzialnej", "type": "TEXT_FIELD"},
        {"label": "Numer telefonu osoby odpowiedzialnej", "type": "TEXT_FIELD"},
        {"label": "Telefon kontaktowy klubu", "type": "TEXT_FIELD"}]})
    titles = [f["title"] for f in _fields(form) if f["type"] != "SECTION"]
    assert titles.count("Numer kierunkowy") == 2
    assert titles.index("Numer kierunkowy") == titles.index("Numer telefonu osoby odpowiedzialnej") - 1
    k = next(f for f in _fields(form) if f["title"] == "Numer kierunkowy")
    assert k["type"] == "SELECT" and k["dictionaryName"] == "Numery kierunkowe" and check(form) == []
