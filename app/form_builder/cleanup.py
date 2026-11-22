"""F-15: deterministyczne sprzątanie szkicu od LLM przed builderem (reguły w config/field_rules.yaml -> cleanup).

Usuwa pola papierowe, oświadczenia zamienia na zgody, poprawia typy pól wyboru i kwot.
F-14: usuwa też duplikaty sekcji standardowych (wnioskodawca, adres, pełnomocnik, kontakt, RODO, organ) - te są z szablonów.
Zwraca kopię szkicu; każda zmiana trafia do `notes` (trace w /convert?debug=true).
"""
import re

from app.form_builder.draft import Draft, DraftField, DraftSection
from app.form_builder.enrich import CFG, dictionary, norm

C = CFG["cleanup"]
DROP = re.compile(C["drop"])
CONSENT = re.compile(C["consent"])
NUMBER = re.compile(C["number"])
ADDRESS, ADDRESS_HINT = re.compile(C["address"]), re.compile(C["address_hint"])
ADDRESS_PARTS = [("Kraj", True), ("Ulica", True), ("Numer budynku", True), ("Numer lokalu", False), ("Kod pocztowy", True), ("Miejscowość", True)]
S = {k: re.compile(v) for k, v in CFG["standard"].items()}


def tidy(draft: Draft, notes: list) -> Draft:
    d = draft.model_copy(deep=True)
    for page in d.pages:
        kept_secs = []
        for sec in page.sections or []:
            st = norm(sec.title)
            if DROP.search(st):
                notes.append(f"usunięto sekcję {sec.title!r} (pole papierowe/instrukcja)")
                continue
            if S["sections"].search(st):
                _organ(d, sec.fields or [], st)
                notes.append(f"usunięto sekcję {sec.title!r} (dubluje sekcję standardową)")
                continue
            applicant, kept = S["applicant"].search(st), []
            for f in sec.fields or []:
                n = norm(f.label)
                if DROP.search(n):
                    notes.append(f"usunięto pole {f.label!r} (pole papierowe/instrukcja)")
                    continue
                if S["fields"].search(n) or (applicant and S["applicant_fields"].search(n)):
                    _organ(d, [f], st)
                    notes.append(f"usunięto pole {f.label!r} (dubluje sekcję standardową)")
                    continue
                _fix_type(f, sec.title, notes)
                kept.append(f)
            sec.fields = kept
            if kept:
                kept_secs.append(sec)
            kept_secs += _split_addresses(sec, notes)
        page.sections = kept_secs
    d.pages = [p for p in d.pages if p.sections]
    return d


def _organ(d: Draft, fields: list, sec_title: str) -> None:
    """Stara wersja promptu wpisywała organ jako pole read_only -> przenosimy wartość do Draft.organ."""
    if d.organ.strip():
        return
    d.organ = next((f.default.strip() for f in fields if f.default.strip()
                    and S["organ"].search(f"{sec_title} {norm(f.label)}")), "")


def _fix_type(f, sec_title: str, notes: list) -> None:
    n, before = norm(f.label), f.type
    opts = {o.strip().lower() for o in f.options}
    lone = f.type == "CHECKBOX" and len(opts) <= 1
    if f.type in ("CHECKBOX", "RADIO", "TEXT_FIELD") and (CONSENT.search(n) or (lone and re.search(r"oswiadcz|zgod", norm(sec_title)))):
        f.type, f.options = "CONSENT_SECTION", []
    elif lone:  # „☐ Załącznik A” poza oświadczeniami to pytanie Tak/Nie, nie zgoda (przegląd v3, formularz 8)
        f.type, f.options = "RADIO", ["Tak", "Nie"]
    elif f.type in ("SELECT", "RADIO", "CHECKBOX") and f.label in f.options:  # LLM wpisał opcję jako label
        notes.append(f"label {f.label!r} był opcją -> {sec_title!r}")
        f.label = sec_title
    if f.type == "CHECKBOX" and opts == {"tak", "nie"}:
        f.type = "RADIO"
    elif f.type == "SELECT" and 2 <= len(f.options) <= 5 and not dictionary(f):
        f.type = "RADIO"  # standard COI: do 5 opcji -> radio
    elif f.type == "RADIO" and len(f.options) > 15:
        f.type = "SELECT"  # >15 -> lista rozwijana z wyszukiwarką (searchEnabled w builderze)
    elif f.type == "TEXT_FIELD" and NUMBER.search(n) and not dictionary(f):
        f.type = "NUMBER"
    if f.type == "NUMBER" and not re.fullmatch(r"-?\d+([.,]\d+)?", f.default.strip()):
        f.default = ""  # "0 zł" itp. -> pole do wpisania
    if f.type != before:
        notes.append(f"{f.label!r}: {before} -> {f.type}")


def _split_addresses(sec: DraftSection, notes: list) -> list[DraftSection]:
    """Adres w jednym polu -> osobna sekcja z grupą pól (tytuł = label, ten sam show_if) wstawiana za `sec`.
    Gdy adres był jedynym polem sekcji, grupa zastępuje go w miejscu. W sekcji powtarzalnej też w miejscu, z dopiskiem
    „(label)”, bo osobna sekcja powtarzalna odkleja adres od wiersza (przegląd v5, form. 7: adres poprzedniego właściciela)."""
    out = []
    for f in list(sec.fields):
        if f.type not in ("TEXT_FIELD", "TEXTAREA") or not (ADDRESS.search(norm(f.label)) or ADDRESS_HINT.search(norm(f.hint))):
            continue
        parts = [DraftField(label=label, type="TEXT_FIELD", required=f.required and req) for label, req in ADDRESS_PARTS]
        notes.append(f"pole zbiorcze {f.label!r} rozbite na grupę adresową")
        if sec.repeating and len(sec.fields) > 1:
            for p in parts:
                p.label, p.show_if = f"{p.label} ({f.label})", f.show_if
            i = sec.fields.index(f)
            sec.fields[i:i + 1] = parts
            continue
        if len(sec.fields) == 1:
            sec.fields = parts
            if f.show_if and not sec.show_if:
                sec.show_if = f.show_if
            break
        sec.fields.remove(f)
        out.append(DraftSection(title=f.label, repeating=sec.repeating, fields=parts, show_if=f.show_if or sec.show_if))
    return out


def _stems(text: str) -> set[str]:
    return {w[:5] for w in norm(text).split() if len(w) >= 4}


def unsupported_statements(draft: Draft, source_text: str, notes: list) -> None:
    """R-03 (przegląd v4): LLM dopisywał wymagane oświadczenia, których nie ma w dokumencie („dane są prawdziwe”).
    Oświadczenie słabo pokryte słowami źródła traci REQUIRED i trafia do „do sprawdzenia” - nie usuwamy, decyduje urzędnik.
    shortcut: pokrycie po 5-literowych rdzeniach słów, bez lematyzacji; przy fałszywych alarmach podnieść próg albo użyć NER."""
    src = _stems(source_text)
    for page in draft.pages:
        for sec in page.sections or []:
            for f in sec.fields or []:
                if not f.required or not (f.type == "CONSENT_SECTION" or CONSENT.search(norm(f.label))):
                    continue
                words = _stems(f.label)
                if words and len(words & src) / len(words) < 0.6:
                    f.required = False
                    notes.append(f"oświadczenie {f.label!r} nie występuje w dokumencie, zdjęto REQUIRED")


# R-08: słowa, które e-formularz dodaje z definicji (rozbicie adresu i imienia, pytania sterujące, ogólne etykiety)
# — ich brak w dokumencie nie świadczy o zmyśleniu. Dobrane na 178 polach z wyniki/: 0 fałszywych alarmów.
_GENERIC = _stems("numer nazwa data kraj ulica budynku lokalu miejscowość kod pocztowy poczta imię nazwisko rodzaj czego "
                  "dotyczy wniosek opcji szczegóły tylko inne rrrr telefon e-mail adres województwo powiat gmina uzasadnienie "
                  "opis liczba kwota wartość informacje dodatkowe uwagi załącznik plik dokument potwierdzenie wybierz podaj "
                  "który która których jeden więcej osoba osoby inna innej czy zamieszkania korespondencji")
_INPUTS = {"TEXT_FIELD", "TEXTAREA", "NUMBER", "DATEPICKER", "SELECT", "RADIO", "CHECKBOX", "FILE_UPLOADER"}


def unsupported_fields(draft: Draft, source_text: str, notes: list) -> None:
    """R-08 (D-01, przegląd v4): pole, którego istotnych słów (bez słownictwa ogólnego _GENERIC) w większości nie ma
    w dokumencie, mogło zostać dopisane przez AI -> traci REQUIRED i trafia do „do sprawdzenia” (nie usuwamy).
    Nie złapie pola złożonego ze słów, które w dokumencie są — to wymagałoby drugiego zapytania do LLM; wyjątek: „Nazwa banku”.
    shortcut: „Nazwa banku” na sztywno, bo to jedyne powtarzalne zmyślenie z przeglądów; przy kolejnych -> lista w field_rules.yaml."""
    src = _stems(source_text)
    if not src:  # pusty / nieczytelny dokument — nie ma z czym porównać
        return
    src_norm = norm(source_text)
    for page in draft.pages:
        for sec in page.sections or []:
            # znane zmyślenie 14B (form. 2, przeglądy v4–v5): „Nazwa banku” przy samym „rachunku w banku” -> usuwamy
            for f in [f for f in sec.fields or [] if norm(f.label).startswith("nazwa banku") and "nazwa banku" not in src_norm]:
                sec.fields.remove(f)
                notes.append(f"usunięto pole {f.label!r} (nie ma go w dokumencie)")
            if not sec.fields:
                continue
            for f in sec.fields or []:
                if f.type not in _INPUTS:
                    continue
                words = _stems(f.label) - _GENERIC
                if words and len(words & src) / len(words) < 0.5:
                    f.required = False
                    notes.append(f"pole {f.label!r} nie występuje w dokumencie, zdjęto REQUIRED")
