"""N-C3: asystent prostego języka — reguły ze Standardu, rozdz. 1."""
import copy
import glob
import json
from pathlib import Path

import pytest

from app.form_builder.plain_language import check_plain_language, check_text, html_to_text, load_rules, main, syllables

ROOT = Path(__file__).resolve().parent.parent


def _rules(text, where="description"):
    return {(h["regula"], h["fragment"]) for h in check_text(text, where)}


def _ids(text, where="description"):
    return {h["regula"] for h in check_text(text, where)}


def test_rules_load_and_have_source():
    rules = load_rules()
    assert len(rules) >= 15
    assert len({r.id for r in rules}) == len(rules)
    for r in rules:
        assert r.source and r.message and r.level in {"błąd", "ostrzeżenie"}
        assert r.regex is not None or r.check in {"wersaliki", "dlugosc", "dlugie_zdanie", "dlugie_slowo"}


@pytest.mark.parametrize("text,rule", [
    # przykłady wprost z listy „Błędy, których warto unikać” (s. 4)
    ("Proszę dokonać wpłaty.", "dokonac"),
    ("Dokonanie weryfikacji wniosku.", "dokonac"),
    ("Pragniemy nadmienić, że termin minął.", "pragnac"),
    ("Pragniemy nadmienić, że termin minął.", "zbedne_wyrazenia"),
    ("Posiadam gospodarstwo rolne", "posiadac"),
    ("Informujemy, że wniosek jest kompletny.", "informujemy"),
    ("W odniesieniu do powyższego prosimy o dopłatę.", "zbedne_wyrazenia"),
    ("Wnioskując o zwrot, dołącz dowód wpłaty.", "imieslow_ac"),
    ("Naliczono opłatę.", "bezosobowe_no_to"),
    ("Nie otrzymano dokumentu.", "bezosobowe_no_to"),
    ("Należy dołączyć zaświadczenie.", "nalezy"),
    ("Wniosek zostanie rozpatrzony w ciągu 30 dni.", "strona_bierna"),
    ("Zapoznałem/am się z klauzulą informacyjną.", "forma_plciowa"),
    ("Jestem zainteresowany/a udziałem.", "forma_plciowa"),
    ("Pan/Pani składa wniosek.", "forma_plciowa"),
    ("Zapoznałam się z regulaminem.", "czas_przeszly_1os"),
    ("Data uiszczenia opłaty", "trudne_slowo"),
    ("Niniejszym oświadczam, że dane są prawdziwe.", "trudne_slowo"),
    ("Liczba gospodarstw (pow. ≤ 45 m²)", "skrot"),
    ("Na podstawie art. 75 ustawy", "przepisy_prawa"),
    ("Wypełnić w przypadku nieruchomości wielolokalowej.", "bezokolicznik_polecenie"),
])
def test_rule_hits(text, rule):
    assert rule in _ids(text)


@pytest.mark.parametrize("text", [
    "Wybierz, w czyim imieniu wnioskujesz",          # ze Standardu
    "Urząd, do którego jest składany wniosek",       # tytuł sekcji wzorcowej (strona bierna celowo pominięta)
    "Opłata za miesiąc i tysiąc złotych",            # -ąc, ale nie imiesłów
    "Posiadacz gospodarstwa rolnego",                # termin prawny
    "Numer konta i miasto",                          # -to, ale nie forma bezosobowa
    "Numer PESEL, NIP i REGON",                      # znane skróty, nie wersaliki
    "Wpisz numer z rejestru KRS.",
    "Adres zamieszkania/zameldowania/siedziby",      # „/” bez formy płciowej
    "Najemca/dzierżawca",
    "Udział w zajęciach z udziałem rodziców",        # -ałem, ale rzeczownik
    "Cel wynajęcia świetlicy (np. wesele, urodziny)",
    "Zanim wyślesz wniosek, sprawdź dane na podglądzie. Jeśli zobaczysz błędy, wróć do edycji.",
    "Wyrażam zgodę na przetwarzanie moich danych osobowych zgodnie z klauzulą informacyjną",
])
def test_no_false_alarms(text):
    assert check_text(text, "description") == []
    if len(text) <= 80:  # dłuższe teksty jako etykieta i tak łapie dlugosc_etykiety
        assert check_text(text, "title") == []


def test_replacement_keeps_case():
    hit = next(h for h in check_text("Posiadam użytki rolne", "title") if h["regula"] == "posiadac")
    assert hit["fragment"] == "Posiadam" and hit["zamiana"] == "Mam"
    hit = next(h for h in check_text("Nie posiadam użytków", "title") if h["regula"] == "posiadac")
    assert hit["zamiana"] == "mam"
    hit = next(h for h in check_text("Data uiszczenia opłaty", "title") if h["regula"] == "trudne_slowo")
    assert hit["zamiana"] == "zapłaty"


def test_caps():
    assert ("wersaliki", "SUMA") in _rules("SUMA opłat (poz. 38)", "title")
    hit = next(h for h in check_text("Wpisz WSZYSTKIE DANE poprawnie", "description") if h["regula"] == "wersaliki")
    assert hit["fragment"] == "WSZYSTKIE DANE" and hit["zamiana"] == "wszystkie dane"
    assert "wersaliki" not in _ids("TERYT_4G_DOWODOWY", "title")  # nazwa słownika
    assert "wersaliki" not in _ids("Wybierz BHP lub OSP", "title")  # krótkie akronimy


def test_length_rules():
    long_label = "Informacja o sposobie zabezpieczenia robót (jeśli nie wymagany projekt organizacji ruchu)"
    assert "dlugosc_etykiety" in _ids(long_label, "title")
    assert "dlugosc_etykiety" not in _ids("Czy złożenie pełnomocnictwa wymaga opłaty skarbowej?", "title")
    assert "dlugosc_etykiety" not in _ids(long_label, "description")  # długość tylko dla etykiet
    long_sentence = " ".join(["słowo"] * 30) + "."
    assert "dlugie_zdanie" in _ids(long_sentence, "description")
    assert "dlugie_zdanie" not in _ids("Krótkie zdanie. " * 10, "description")


def test_syllables():
    assert syllables("pełnomocnictwo") == 5
    assert syllables("nieruchomości") == 5
    assert syllables("identyfikacyjny") == 7
    assert "dlugie_slowo" not in _ids("Plik dokumentu z pełnomocnictwem", "title")


def test_html_to_text():
    s = "<html><head><title>x</title></head><body><p>Pierwsze&nbsp;zdanie</p><p>Drugie <b>zdanie</b></p></body></html>"
    assert html_to_text(s) == "Pierwsze zdanie\nDrugie zdanie"


def _form():
    return {"title": "Wniosek o zwrot opłaty", "tabs": [{"id": "t1", "title": "Dane", "questions": [
        {"field": {"id": "s1", "type": "SECTION", "techName": "sekcja", "title": "Sekcja", "description": "",
                   "tooltipMessage": "", "options": [], "repeatingSectionGrid": [
            {"field": {"id": "f1", "type": "RADIO", "techName": "posiadam", "title": "Posiadam gospodarstwo",
                       "description": "<p>Należy zaznaczyć jedną opcję.</p>", "tooltipMessage": "Informujemy o terminie.",
                       "options": [{"name": "Inny podmiot posiadający nieruchomość"}], "repeatingSectionGrid": []}},
            {"field": {"id": "f2", "type": "SELECT", "techName": "kraj", "title": "Kraj", "description": "",
                       "dictionaryName": "Kraje", "options": [{"name": "Posiadłość dokonana"}], "repeatingSectionGrid": []}},
            {"field": {"id": "f3", "type": "CONSENT_SECTION", "techName": "zgoda", "title": "", "description": "",
                       "options": [], "repeatingSectionGrid": [], "consentSectionConfig": {"consents": [
                           {"description": "<p>Zapoznałem/am się z regulaminem</p>", "required": True}]}}},
            {"field": {"id": "f4", "type": "TEXT_FIELD", "techName": "imie", "title": "Imię", "description": "",
                       "defaultValue": "MLPZ.name", "options": [], "repeatingSectionGrid": []}},
        ]}}]}]}


def test_form_walk_locations():
    form = _form()
    before = copy.deepcopy(form)
    sug = check_plain_language(form)
    assert form == before  # tylko sugestie, JSON się nie zmienia
    got = {(s["techName"], s["gdzie"], s["regula"]) for s in sug}
    assert ("posiadam", "title", "posiadac") in got
    assert ("posiadam", "description", "nalezy") in got
    assert ("posiadam", "tooltip", "informujemy") in got
    assert ("posiadam", "opcja", "posiadac") in got
    assert ("zgoda", "zgoda", "forma_plciowa") in got
    assert not any(s["techName"] == "kraj" for s in sug)  # opcje słownikowe pomijamy
    assert not any(s["techName"] == "imie" for s in sug)  # MLPZ.name to źródło danych
    opt = next(s for s in sug if s["gdzie"] == "opcja")
    assert opt["sciezka"] == "tabs[0].questions[0].field.repeatingSectionGrid[0].field.options[0].name"
    assert opt["zamiana"] == "mający" and opt["strona"] == "Dane" and opt["fieldId"] == "f1"
    for s in sug:
        assert {"techName", "gdzie", "fragment", "regula", "komunikat", "propozycja", "zamiana", "zrodlo", "poziom"} <= s.keys()
        assert s["fragment"] in s["tekst"]


def _reference_forms():
    files = glob.glob(str(ROOT / "data" / "1" / "*" / "konfiguracja*.json")) + \
        glob.glob(str(ROOT / "data" / "5" / "*" / "konfiguracja*.json"))
    return files + glob.glob(str(ROOT / "config" / "section_templates" / "*.json"))


@pytest.mark.parametrize("path", _reference_forms())
def test_reference_forms_are_clean(path):
    """Wzorcowe formularze COI (1, 5) i sekcje wzorcowe Standardu nie mogą świecić."""
    data = json.loads(Path(path).read_text("utf-8"))
    if isinstance(data, list):
        data = {"tabs": [{"title": "Dane", "questions": data}]}
    assert check_plain_language(data) == []


def test_cli(tmp_path, capsys):
    p = tmp_path / "f.json"
    p.write_text(json.dumps(_form(), ensure_ascii=False), "utf-8")
    assert main([str(p)]) == 0
    out = capsys.readouterr().out
    assert "posiadac" in out and "sugestii" in out
    assert main([str(p), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[str(p)]
