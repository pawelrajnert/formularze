"""Tekst dokumentu -> Draft przez LLM (structured output).

Tymczasowe, do podmiany na LLMClient z hackcore C-04 / F-06 Marcina.
"""
import time
from pathlib import Path

from app import config
import json
from typing import get_args

from app.form_builder.draft import Dictionary, Draft, FieldType, Validator

TIMEOUT = 90
ATTEMPTS = 3
MAX_CHARS = 30000  # shortcut: ucinamy długie dokumenty, przy wielostronicowych formularzach dzielić na części

SYSTEM = """Jesteś analitykiem cyfryzującym urzędowe formularze na platformę COI. Z tekstu dokumentu zbuduj szkic formularza wg schematu JSON.
Reguły:
- Wyciągnij KAŻDE miejsce do wypełnienia: wykropkowania (……), puste kratki ☐, komórki tabel, rubryki pod opisem w nawiasie. Nie pomijaj pól z tabel.
- Pola merytoryczne tylko z dokumentu, nie wymyślaj nowych. Dane wnioskodawcy (w czyim imieniu, osoba fizyczna/prawna, pełnomocnik, adres, kontakt) rozpisz tak szczegółowo jak w przykładzie.
- Strony tematyczne, np.: „Dane wnioskodawcy” / „Przedmiot wniosku” / „Załączniki i oświadczenia”. W stronach sekcje (organ, wnioskodawca, adres, dane sprawy...).
- Etykiety po polsku, jak w dokumencie, bez kropek, podkreśleń i przypisów.
- Wybory: „w czyim imieniu”, „osoba fizyczna / prawna”, „tak / nie”, „zaznacz właściwe ☐” -> RADIO (jedna opcja) lub CHECKBOX (wiele), opcje w `options`; przy długiej liście -> SELECT.
- Pola lub sekcje widoczne tylko przy danym wyborze -> show_if {field: label pola sterującego, equals: opcja}; np. dane pełnomocnika gdy „W imieniu innej osoby”, NIP/KRS gdy „Osoba prawna”.
- Adres rozbij na pola: Kraj, Miejscowość, Kod pocztowy, Ulica, Numer budynku, Numer lokalu (gmina/powiat/województwo, jeśli są w dokumencie).
- required=true, gdy pole obowiązkowe lub oznaczone *; dane identyfikujące wnioskodawcę zwykle obowiązkowe.
- Typy: daty -> DATEPICKER, kwoty/liczby -> NUMBER, dłuższe opisy/uzasadnienia -> TEXTAREA, załączniki -> FILE_UPLOADER, oświadczenia/zgody -> CONSENT_SECTION, pouczenia i klauzule -> TEXT_BLOCK albo `finish_text` (klauzula RODO).
- Walidatory: EMAIL, PESEL, NIP, REGON, ZIP_CODE (kod pocztowy), EPUAP (skrytka ePUAP).
- Uzupełniaj `dictionary` i `prefill` zgodnie z opisami pól w schemacie (kraj -> Kraje, PESEL -> PESEL.pesel, imię -> PESEL.name itd.).
- Stała treść (np. nazwa i adres organu) -> pole read_only z `default`. Powtarzalne listy -> repeating=true.
Zwróć wyłącznie JSON."""

_FEWSHOT = Path(__file__).resolve().parents[2] / "config" / "fewshot"
# few-shot: formularz 1 (tekst -> wzorcowy szkic COI); uczy szczegółowości, RADIO i show_if
EXAMPLE = [
    {"role": "user", "content": (_FEWSHOT / "form1.txt").read_text("utf-8")},
    {"role": "assistant", "content": (_FEWSHOT / "form1_draft.json").read_text("utf-8")},
]


def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(_txt(x) for x in v if x is not None)
    if isinstance(v, dict):
        return _txt(v.get("name") or v.get("label") or v.get("value") or "")
    return str(v)


def _fix_show_if(o: dict) -> None:
    si = o.get("show_if")
    if not isinstance(si, dict) or not si.get("field"):
        o["show_if"] = None
        return
    eq = si.get("equals")
    si["field"] = _txt(si["field"])
    si["equals"] = _txt(eq[0] if isinstance(eq, list) and eq else eq)
    if isinstance(eq, bool):
        si["equals"] = "Tak" if eq else "Nie"


def clean(raw: str) -> Draft:
    """Jeden zły enum w polu nie zabija całego szkicu: nieznane wartości -> domyślne, puste sekcje/strony out."""
    d = json.loads(raw)
    if isinstance(ft := d.get("finish_text"), dict):  # bywa {"type": "TEXT_BLOCK", "content": ...}
        d["finish_text"] = "\n".join(str(v) for k, v in ft.items() if k != "type")
    for page in d.get("pages") or []:
        for sec in page.get("sections") or []:
            sec["fields"] = [f for f in sec.get("fields") or [] if isinstance(f, dict) and f.get("label")]
            _fix_show_if(sec)
            for f in sec["fields"]:
                f["validators"] = [v for v in f.get("validators") or [] if v in get_args(Validator)]
                if f.get("dictionary") not in get_args(Dictionary):
                    f["dictionary"] = ""
                if f.get("type") not in get_args(FieldType):
                    f["type"] = "TEXT_FIELD"
                for k in ("label", "hint", "default", "prefill"):  # bywa lista / liczba / bool zamiast tekstu
                    if k in f:
                        f[k] = _txt(f[k])
                f["options"] = [_txt(o) for o in f.get("options") or [] if _txt(o)]
                _fix_show_if(f)
        page["sections"] = [s for s in page.get("sections") or [] if s["fields"]]
    d["pages"] = [p for p in d.get("pages") or [] if p["sections"]]
    return Draft.model_validate(d)


def messages(text: str) -> list[dict]:
    return [{"role": "system", "content": SYSTEM}, *EXAMPLE, {"role": "user", "content": text[:MAX_CHARS]}]


def _client():
    from openai import OpenAI
    s = config.settings
    return OpenAI(base_url=s.llm_base_url, api_key=s.llm_api_key, timeout=TIMEOUT, max_retries=0)


def llm_draft(text: str) -> Draft:
    from openai import RateLimitError
    client = _client()
    for attempt in range(ATTEMPTS):
        try:
            r = client.chat.completions.create(
                model=config.settings.llm_model,
                temperature=0,
                messages=messages(text),
                response_format={"type": "json_schema", "json_schema": {
                    "name": "draft", "schema": Draft.model_json_schema(), "strict": False}},
            )
            return clean(r.choices[0].message.content)
        except RateLimitError:
            if attempt == ATTEMPTS - 1:
                raise
            time.sleep(31)  # darmowy Mistral: 2 req/min, więc krócej nie ma sensu
    raise AssertionError("unreachable")
