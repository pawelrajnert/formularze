"""F-06: deterministyczne poprawki szkicu (LLM albo heurystyka) wg reguł technicznych i standardu COI.

Bez LLM. Wejście: Draft. Wyjście: poprawiony Draft albo None (gdy nie zostało żadne pole).
Wszystko, co zmieniamy, ląduje w `warnings`; to, co usuwamy jako relikt papieru — w `removed` (N-C4).
"""
import re

from app.form_builder.draft import Draft

CHOICE = {"SELECT", "RADIO", "CHECKBOX"}
NOT_INPUT = {"TEXT_BLOCK", "CONSENT_SECTION", "FILE_UPLOADER"}  # tych nie usuwamy regułami „papierowymi”
TITLE_PREFIXES = ("Wniosek", "Zgłoszenie", "Deklaracja", "Oświadczenie")
TITLE_SYNONYMS = re.compile(r"^(podanie|prośba|formularz|druk|karta|pismo)\b\s*", re.I)
MAX_TITLE = 255
MAX_OPTIONS_RADIO = 5

# --- elementy papierowe (N-C4) -------------------------------------------------------------------------------
REASON_SIGNATURE = "formularz elektroniczny podpisuje się elektronicznie na końcu procesu (np. profil zaufany)"
REASON_STAMP = "w e-usłudze nie stosuje się pieczęci"
REASON_DATE = "system zapisuje datę złożenia automatycznie"
REASON_OFFICE = "urzędnik uzupełnia je w swoim systemie"

# reguły na etykiety pól wejściowych: (regex, uzasadnienie)
PAPER_FIELD_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bpodpis(y|u|em|ów)?\b|czytelny podpis", re.I), REASON_SIGNATURE),
    (re.compile(r"piecz(ęć|ec|ątk|ęci)", re.I), REASON_STAMP),
    (re.compile(r"^\s*(miejscowość\s*(,|i)?\s*)?(data|dnia)\s*[:.]?\s*$|data\s+(wypełnienia|sporządzenia|złożenia)"
                r"|^\s*miejsce\s+i\s+data|^\s*data\s+i\s+(miejsce|podpis)|^\s*miejscowość\s*(,|i)\s*data|,\s*(dnia|data)\s*[:.]?\s*$",
                re.I), REASON_DATE),
    (re.compile(r"wypełnia\s+(urząd|organ|pracownik)|adnotacj\w*\s+urz|potwierdzenie\s+wpływu|nr\s+sprawy|znak\s+sprawy",
                re.I), REASON_OFFICE),
]

# reguły na cały tekst dokumentu: (regex, opis zmiany) — do listy „Co zmieniliśmy przy cyfryzacji”
PAPER_TEXT_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\bpodpis(y|u|em)?\b", re.I), "Podpis wnioskodawcy — pominięty: " + REASON_SIGNATURE + "."),
    (re.compile(r"piecz(ęć|ątk)", re.I), "Pieczęć — pominięta: " + REASON_STAMP + "."),
    (re.compile(r"\(\s*data\s*\)|/\s*data\s*/|data\s+wypełnienia|,\s*dnia\s*[.…_]{2,}|miejscowość\s*(,|i)\s*data|^\s*data\s*[.…_ -]{3,}",
                re.I | re.M), "Miejscowość i data wypełnienia — pominięte: " + REASON_DATE + "."),
    (re.compile(r"drukowanymi\s+literami|wielkimi\s+literami|wypełni\w*\s+czytelnie|kolorem\s+czarnym|długopisem", re.I),
     "Instrukcje wypełniania papieru (np. „wypełnij drukowanymi literami”) — pominięte: nie dotyczą formularza elektronicznego."),
    (re.compile(r"niepotrzebne\s+skreślić|postaw\s*„?x|zaznacz\w*\s+(znakiem\s+)?x\b|pola\s+wyboru\s+oznaczaj", re.I),
     "Instrukcje „niepotrzebne skreślić / postaw X” — zastąpione polami wyboru (RADIO/CHECKBOX/SELECT)."),
    (re.compile(r"wypełnia\s+(urząd|organ|pracownik)|adnotacje\s+urz|potwierdzenie\s+wpływu", re.I),
     "Pola „wypełnia urząd” — pominięte: " + REASON_OFFICE + "."),
    (re.compile(r"klauzul\w*\s+informacyjn|ochronie\s+danych\s+osobowych|\bRODO\b", re.I),
     "Pełna treść klauzuli informacyjnej RODO — nie umieszczamy jej na formularzu (standard COI); zamiast niej zgoda w sekcji „Zgoda”."),
    (re.compile(r"^\s*(\d+\.\s*)?załącznik\w*\s*[:(]", re.I | re.M),
     "Lista załączników — zamieniona na pola przesyłania plików (FILE_UPLOADER)."),
]


def paper_reason(label: str, ftype: str) -> str | None:
    """Uzasadnienie usunięcia pola papierowego albo None (pole zostaje)."""
    if ftype in NOT_INPUT:
        return None
    for rx, reason in PAPER_FIELD_RULES:
        if rx.search(label):
            return reason
    return None


def paper_elements_in_text(text: str) -> list[str]:
    return [msg for rx, msg in PAPER_TEXT_RULES if rx.search(text or "")]


# --- tytuł -----------------------------------------------------------------------------------------------------
_LEGAL_PAREN = re.compile(r"\s*\([^()]*\b(art\.|ustaw|rozporządz|Dz\.\s?U|§)[^()]*\)", re.I)
_LEGAL_TAIL = re.compile(r"\s*,?\s*\b(na podstawie|zgodnie z|w trybie|w myśl)\s+(art\.|ustaw|przepis|§|rozporządz).*$", re.I)


def _mostly_upper(s: str) -> bool:
    letters = [c for c in s if c.isalpha()]
    return len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.8


def normalize_title(title: str, warnings: list[str]) -> str:
    raw = title
    t = re.sub(r"\s+", " ", title or "").strip(" \t\"'„”.:;-–")
    t = _LEGAL_TAIL.sub("", _LEGAL_PAREN.sub("", t)).strip(" ,.;:-–")
    if _mostly_upper(t):
        t = t[:1].upper() + t[1:].lower()
    for p in TITLE_PREFIXES:
        if t.lower().startswith(p.lower()):
            t = p + t[len(p):]
            break
    else:
        if TITLE_SYNONYMS.match(t):
            t = TITLE_SYNONYMS.sub("Wniosek ", t, count=1).strip()
        elif t:
            t = "Wniosek o " + t[:1].lower() + t[1:]
        else:
            t = "Wniosek"
        warnings.append(f"Tytuł „{raw}” nie zaczynał się od Wniosek/Zgłoszenie/Deklaracja/Oświadczenie — zmieniony na „{t[:80]}”.")
    if len(t) > MAX_TITLE:
        t = t[:MAX_TITLE].rsplit(" ", 1)[0].rstrip(" ,.;:-–")
        warnings.append(f"Tytuł skrócony do {MAX_TITLE} znaków.")
    return t


# --- pola ------------------------------------------------------------------------------------------------------
_CONSENT_LABEL = re.compile(r"^\s*(oświadczam|wyrażam\s+zgodę|zapoznał\w*\s+się|potwierdzam|akceptuję)", re.I)


def _clean_options(opts: list[str]) -> list[str]:
    out: list[str] = []
    for o in opts:
        o = re.sub(r"\s+", " ", str(o)).strip(" \t;,")
        if o and o not in out:
            out.append(o)
    return out


def _fix_field(f: dict, where: str, removed: list[str], warnings: list[str]) -> dict | None:
    """Tylko higiena struktury. Sprzątanie treści (pola papierowe, zgody, typy) robi tidy() z F-15 (P) w builderze."""
    f["label"] = re.sub(r"\s+", " ", f.get("label") or "").strip()
    t = f["type"]
    if not f["label"]:
        warnings.append(f"{where}: pole bez etykiety usunięte.")
        return None
    if t in CHOICE:
        f["options"] = _clean_options(f.get("options") or [])
        if t in ("SELECT", "RADIO") and not f["options"]:
            warnings.append(f"{where}: „{f['label']}” ({t}) bez opcji — zamienione na TEXT_FIELD.")
            f["type"] = t = "TEXT_FIELD"
    if t not in CHOICE:
        f["options"] = []
    if t == "TEXT_BLOCK":
        f["required"] = False
    f["validators"] = list(dict.fromkeys(f.get("validators") or []))
    if f.get("default") and t in CHOICE and f["options"] and f["default"] not in f["options"]:
        warnings.append(f"{where}: wartość domyślna „{f['default']}” spoza opcji pola „{f['label']}” — usunięta.")
        f["default"] = ""
    return f


def _resolve_show_if(node: dict, what: str, labels: dict[str, list[list[str] | None]], own_label: str | None,
                     warnings: list[str]) -> None:
    """Tylko poprawka wielkości liter w etykiecie/opcji. Warunki do nieznanych pól zostawiamy — obsługuje je F-15 (e)
    w builderze (szuka pola wyboru z taką opcją, inaczej zdejmuje REQUIRED w sekcji warunkowej)."""
    cond = node.get("show_if")
    if not cond:
        return
    field, equals = (cond.get("field") or "").strip(), (cond.get("equals") or "").strip()
    if field not in labels:
        field = next((k for k in labels if k.casefold() == field.casefold()), field)
    option_sets = [o for o in labels.get(field, []) if o is not None]
    if option_sets and not any(equals in o for o in option_sets):
        equals = next((x for o in option_sets for x in o if x.casefold() == equals.casefold()), equals)
    node["show_if"] = {"field": field, "equals": equals}


# --- F-09: typowe zależności dopisywane deterministycznie (gdy LLM ich nie dał) -----------------------------------
_IF_YES = re.compile(r"^\s*(je[sś]li|je[zż]eli|w przypadku)\b[^,:]{0,40}\b(tak|twierdz)", re.IGNORECASE)
_IF_NO = re.compile(r"^\s*(je[sś]li|je[zż]eli|w przypadku)\b[^,:]{0,40}\b(nie|przecz)\b", re.IGNORECASE)
_PL_ONLY = re.compile(r"^(wojew[oó]dztwo|powiat|gmina|kod pocztowy)$", re.IGNORECASE)
_ABROAD = re.compile(r"zagranic|za granic", re.IGNORECASE)
_WHOSE = "Wybierz, w czyim imieniu wnioskujesz"
_OTHER_PERSON = re.compile(r"innej osoby|^pe[lł]nomocnictwo$|^op[lł]ata skarbowa", re.IGNORECASE)
_ENTITY = re.compile(r"dane podmiotu|adres siedziby", re.IGNORECASE)


def _option(opts: list[str], pattern: str) -> str | None:
    return next((o for o in opts if re.search(pattern, o.strip(), re.IGNORECASE)), None)


def infer_dependencies(pages: list[dict], warnings: list[str]) -> int:
    """Dopisuje show_if dla wzorców ze standardu COI. Nie nadpisuje warunków od LLM. Zwraca liczbę dodanych."""
    added = 0

    def put(node: dict, field: str, equals: str, what: str) -> None:
        nonlocal added
        node["show_if"] = {"field": field, "equals": equals}
        added += 1
        warnings.append(f"Dodano warunek: {what} widoczne, gdy „{field}” = „{equals}”.")

    whose = next((f for p in pages for s in p["sections"] for f in s["fields"]
                  if f["label"] == _WHOSE and f["type"] in CHOICE), None)
    for page in pages:
        for sec in page["sections"]:
            # Podmiot wniosku -> sekcje innej osoby / podmiotu
            if whose and not sec.get("show_if") and not any(f["label"] == _WHOSE for f in sec["fields"]):
                if _ENTITY.search(sec["title"]) and (o := _option(whose["options"], r"prawn|podmiot|jednostk")):
                    put(sec, _WHOSE, o, f"sekcja „{sec['title']}”")
                elif _OTHER_PERSON.search(sec["title"]) and (o := _option(whose["options"], r"innej osoby")):
                    put(sec, _WHOSE, o, f"sekcja „{sec['title']}”")
            last_yes_no: dict | None = None
            country = next((f for f in sec["fields"] if f["label"].strip().lower() == "kraj" and f["type"] in CHOICE), None)
            for f in sec["fields"]:
                if not f.get("show_if"):
                    want = "^tak$" if _IF_YES.search(f["label"]) else "^nie$" if _IF_NO.search(f["label"]) else None
                    if want and last_yes_no and (o := _option(last_yes_no["options"], want)):
                        # „Jeśli tak, podaj…” -> ostatnie wcześniejsze pytanie Tak/Nie w sekcji
                        put(f, last_yes_no["label"], o, f"pole „{f['label'][:50]}”")
                    elif country and f is not country:
                        # Polska / zagranica w sekcji adresu
                        if _ABROAD.search(f["label"]) and (o := _option(country["options"], r"inny|zagranic")):
                            put(f, country["label"], o, f"pole „{f['label'][:50]}”")
                        elif _PL_ONLY.match(f["label"].strip()) and (o := _option(country["options"], r"^polska$")):
                            put(f, country["label"], o, f"pole „{f['label'][:50]}”")
                if f["type"] in CHOICE and _option(f["options"], r"^tak$") and _option(f["options"], r"^nie$"):
                    last_yes_no = f
    return added


def postprocess(draft: Draft, removed: list[str], warnings: list[str]) -> Draft | None:
    d = draft.model_dump()
    d["title"] = normalize_title(d.get("title") or "", warnings)
    pages = []
    for pi, page in enumerate(d.get("pages") or [], 1):
        page["title"] = re.sub(r"\s+", " ", page.get("title") or "").strip() or f"Strona {pi}"
        sections = []
        for sec in page.get("sections") or []:
            sec["title"] = re.sub(r"\s+", " ", sec.get("title") or "").strip() or "Dane"
            where = f"„{page['title']}” / „{sec['title']}”"
            sec["fields"] = [f for f in (_fix_field(f, where, removed, warnings) for f in sec.get("fields") or []) if f]
            if sec["fields"]:
                sections.append(sec)
            else:
                warnings.append(f"Sekcja {where} bez pól — usunięta.")
        page["sections"] = sections
        if sections:
            pages.append(page)
        else:
            warnings.append(f"Strona „{page['title']}” bez pól — usunięta.")
    if not pages:
        return None
    d["pages"] = pages
    infer_dependencies(pages, warnings)

    # show_if: tylko do istniejących pól (builder adresuje po labelu; TEXT_BLOCK nie ma odpowiedzi)
    labels: dict[str, list[list[str] | None]] = {}
    for page in pages:
        for sec in page["sections"]:
            for f in sec["fields"]:
                if f["type"] != "TEXT_BLOCK":
                    labels.setdefault(f["label"], []).append(f["options"] if f["type"] in CHOICE else None)
    for page in pages:
        for sec in page["sections"]:
            _resolve_show_if(sec, f"Sekcja „{sec['title']}”", labels, None, warnings)
            for f in sec["fields"]:
                _resolve_show_if(f, f"Pole „{f['label'][:60]}”", labels, f["label"], warnings)
    removed[:] = list(dict.fromkeys(removed))
    return Draft.model_validate(d)
