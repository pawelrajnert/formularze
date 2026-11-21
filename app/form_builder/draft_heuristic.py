"""F-06 fallback bez LLM: tekst formularza papierowego -> Draft regułami (linie z „....”/„___”, ☐, „:”, nagłówki, tabele).

Cel: zawsze poprawny Draft (≥1 strona, ≥1 sekcja, ≥1 pole), żeby API nigdy nie zwróciło 500 przy braku/awarii LLM.
Jakość niższa niż LLM — wynik oznaczamy source="heuristic", a urzędnik poprawia go w podglądzie.
"""
import re

from hackcore import Document

from app.form_builder.draft import Draft, DraftField, DraftPage, DraftSection
from app.form_builder.draft_postprocess import paper_reason

LEADER = re.compile(r"(?:[.…_]\s?){4,}|…{2,}|_{3,}")
BOX = re.compile(r"[☐☑☒□■▢❑❒◻◽○●-]|\[\s?[xX]?\s?\]")
CAPTION_PAREN = re.compile(r"^\(\s*(.+?)\s*\)+\s*\**$")
CAPTION_SLASH = re.compile(r"^/\s*(.+?)\s*/$")
HEADING_NUM = re.compile(r"^\s*(?:(?:\d+\.)+\d*|[IVX]+\.|[A-H]\.|[A-H]\))\s+(\S.{1,90})$")
TITLE_LINE = re.compile(r"^\s*(wniosek|zgłoszenie|deklaracja|oświadczenie|podanie)\b", re.I)
ORGAN_LINE = re.compile(r"^\s*(do\s+)?(wójt|burmistrz|prezydent|starosta|marszałek|urząd|dyrektor|kierownik|naczelnik|zarząd)\w*\b", re.I)
ADDRESS_LINE = re.compile(r"^\s*(ul\.|al\.|pl\.|\d{2}-\d{3})", re.I)
CLAUSE = re.compile(r"klauzul\w*\s+informacyjn|informacj\w*\s+o\s+przetwarzaniu|ochron\w*\s+danych\s+osobowych", re.I)
CONSENT = re.compile(r"^\s*(oświadczam|wyrażam\s+zgodę|potwierdzam|zobowiązuję\s+się)", re.I)
DATE_MASK = re.compile(r"^\s*[dmr]{2}\s*[-./]\s*[dmr]{2}\s*[-./]\s*r{4}\s*$", re.I)
PAGE_MARK = re.compile(r"^\s*(strona\s+\d+\s*(/|z)\s*\d+|\d+\s*/\s*\d+)\s*$", re.I)
PERSONAL = re.compile(r"^(imię|nazwisko|imię i nazwisko|nr telefonu|numer telefonu|telefon|e-?mail|adres e-?mail|"
                      r"adres poczty elektronicznej|nr telefonu/adres e-mail\)?)$", re.I)
OTHER_PERSON_SECTION = re.compile(r"pełnomoc|inn\w+ osob|współ|dzie|małż|właściciel", re.I)
LEADING_PREP = re.compile(r"^(w|we|przy|na|o|z|do|dla|od|i)\s+", re.I)
FOOTNOTE = re.compile(r"\s*(\d\)|\*+|\d+\s*$)\s*$")

MAX_FIELDS = 200
DEFAULT_SECTION = "Informacje z wniosku"
RODO_CONSENT = "Oświadczam, że znam klauzulę informacyjną o przetwarzaniu moich danych osobowych."


def _sentence_case(s: str) -> str:
    letters = [c for c in s if c.isalpha()]
    if len(s.split()) > 1 and letters and sum(c.isupper() for c in letters) / len(letters) > 0.8:
        s = s.lower()  # „DANE WNIOSKODAWCY” -> „Dane wnioskodawcy”; pojedyncze skróty (PESEL, NIP) zostają
    return s[:1].upper() + s[1:]


def _clean_label(s: str) -> tuple[str, bool]:
    """Etykieta z kawałka linii; zwraca (etykieta, czy oznaczona jako wymagana *)."""
    required = "*" in s
    s = LEADER.sub(" ", s).replace("*", " ")
    s = re.sub(r"\s+", " ", s).strip(" \t:;,.-–()/|`")
    s = FOOTNOTE.sub("", s).strip(" \t:;,.-–()")
    if len(s) > 80:  # długie zdanie przed kropkami -> ostatnie słowa
        s = " ".join(re.split(r"[.;:]\s+", s)[-1].split()[-8:])
    if (m := LEADING_PREP.match(s)) and len(s) - m.end() >= 3:
        s = s[m.end():]
    return _sentence_case(s.strip()), required


def guess_type(label: str) -> tuple[str, list[str]]:
    lo = label.lower()
    if re.search(r"\bpesel\b", lo):
        return "TEXT_FIELD", ["PESEL"]
    if re.search(r"\bnip\b", lo):
        return "TEXT_FIELD", ["NIP"]
    if re.search(r"\bregon\b", lo):
        return "TEXT_FIELD", ["REGON"]
    if re.search(r"e-?mail|poczty elektronicznej", lo):
        return "TEXT_FIELD", ["EMAIL"]
    if "kod pocztowy" in lo:
        return "TEXT_FIELD", ["ZIP_CODE"]
    if "epuap" in lo:
        return "TEXT_FIELD", ["EPUAP"]
    if re.search(r"^(\d+\.\s*)?(załącz|kopia|kopie|skan|odpis)|dowód (uiszczenia|wpłaty)|potwierdzenie (przelewu|wpłaty)", lo):
        return "FILE_UPLOADER", []
    if re.search(r"\bdata\b|\bdnia\b|\bod dnia\b|\bdo dnia\b", lo):
        return "DATEPICKER", []
    if re.search(r"uzasadnieni|opis|uwagi|wyjaśnieni|\bcel\b|treść|informacje dodatkowe", lo):
        return "TEXTAREA", []
    if re.search(r"\bkwot|wysokość|\bliczba\b|\bilość\b|powierzchni|\bzł\b|\bha\b|\bm2\b|m²", lo):
        return "NUMBER", []
    return "TEXT_FIELD", []


class _Collector:
    def __init__(self):
        self.sections: list[list] = [[DEFAULT_SECTION, [], False]]  # [tytuł, pola, powtarzalna]
        self.consents: list[str] = []
        self.removed: list[str] = []
        self.count = 0
        self.last_colon_field: DraftField | None = None  # pole z linii „Etykieta:” — może okazać się nagłówkiem listy ☐

    def section(self, title: str, repeating: bool = False) -> None:
        title = _clean_label(title)[0] or DEFAULT_SECTION
        if not self.sections[-1][1]:  # pusta poprzednia sekcja -> tylko zmiana tytułu
            self.sections[-1] = [title, [], repeating]
        else:
            self.sections.append([title, [], repeating])
        self.last_colon_field = None

    def add(self, raw_label: str, ftype: str | None = None, options: list[str] | None = None) -> DraftField | None:
        label, required = _clean_label(raw_label)
        if len(label) < 2 or self.count >= MAX_FIELDS or not re.search(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]", label):
            return None
        sec_title, fields, repeating = self.sections[-1]
        if PERSONAL.match(label) and not repeating and not OTHER_PERSON_SECTION.search(sec_title):
            return None  # te dane są w sekcjach standardowych „Twoje dane” / „Dane do kontaktu”
        t, validators = guess_type(label)
        if ftype:
            t = ftype
        if reason := paper_reason(label, t):
            self.removed.append(f"Pole „{label}” — pominięte; {reason}.")
            return None
        if any(f.label == label for f in fields):
            return None
        f = DraftField(label=label, type=t, required=required, options=options or [], validators=validators)
        fields.append(f)
        self.count += 1
        return f


def _organ(lines: list[str]) -> tuple[str, set[int]]:
    for i, ln in enumerate(lines[:25]):
        if ORGAN_LINE.match(ln) and len(ln) < 90 and not LEADER.search(ln):
            used, parts = {i}, [re.sub(r"^\s*do\s+", "", ln.strip(), flags=re.I)]
            for j in range(i + 1, min(i + 3, len(lines))):
                if ADDRESS_LINE.match(lines[j]) and len(lines[j]) < 60:
                    parts.append(lines[j].strip())
                    used.add(j)
            return ", ".join(parts), used
    return "", set()


def _is_heading(ln: str) -> str | None:
    if LEADER.search(ln) or BOX.search(ln) or len(ln) > 95:
        return None
    if m := HEADING_NUM.match(ln):
        return m.group(1)
    letters = [c for c in ln if c.isalpha()]
    if len(letters) >= 4 and sum(c.isupper() for c in letters) / len(letters) > 0.85 and len(ln.split()) <= 12:
        return ln
    return None


def _boxes(c: _Collector, ln: str, prev_label: str) -> None:
    parts = BOX.split(ln)
    head, opts = parts[0].strip(), [_clean_label(p)[0] for p in parts[1:]]
    opts = [o for o in opts if o]
    if not opts:
        return
    sec_fields = c.sections[-1][1]
    target = None
    if head:
        target = c.add(head, "CHECKBOX")
    elif c.last_colon_field is not None and c.last_colon_field in sec_fields:
        target = c.last_colon_field
        if target.type not in ("RADIO", "CHECKBOX"):
            target.type, target.validators = "CHECKBOX", []
    elif sec_fields and sec_fields[-1].type in ("RADIO", "CHECKBOX") and sec_fields[-1].options:
        target = sec_fields[-1]
    else:
        target = c.add(prev_label or "Wybierz opcję", "CHECKBOX")
    if target is None:
        return
    for o in opts:
        if o not in target.options:
            target.options.append(o)
    if {o.lower() for o in target.options} <= {"tak", "nie"}:
        target.type = "RADIO"
    c.last_colon_field = target


def heuristic_draft(doc: Document) -> tuple[Draft, list[str]]:
    """Szkic z samych reguł. Zwraca (draft, removed_paper_elements)."""
    text = doc.text or ""
    lines = [ln.strip() for ln in re.split(r"[\n\f\r]+", text)]
    lines = [ln for ln in lines if ln and not PAGE_MARK.match(ln)]
    organ, used = _organ(lines)
    leader_lines = sum(1 for ln in lines if LEADER.search(ln))
    sparse = leader_lines < 3  # formularz-tabela bez kropek: krótkie linie traktujemy jak etykiety

    c = _Collector()
    title, in_clause, clause_seen, prev_label = "", False, False, ""
    for i, ln in enumerate(lines):
        if i in used:
            continue
        if CLAUSE.search(ln) and len(ln) < 120:
            in_clause = clause_seen = True
            continue
        heading = _is_heading(ln)
        if in_clause:
            if heading and not CLAUSE.search(ln) and len(ln) < 60:
                in_clause = False
            else:
                continue
        if not title and TITLE_LINE.match(ln) and len(ln) < 200 and not LEADER.search(ln):
            title = ln
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if len(ln.split()) <= 2 and nxt and len(nxt) < 150 and not LEADER.search(nxt) and not BOX.search(nxt):
                title, used = f"{ln} {nxt}", used | {i + 1}  # „WNIOSEK” + „o wydanie …” w osobnej linii
            continue
        if DATE_MASK.match(ln):
            continue
        if CONSENT.match(ln) and not LEADER.search(ln):
            c.consents.append(re.sub(r"\s+", " ", ln))
            continue
        if BOX.search(ln):
            _boxes(c, ln, prev_label)
            continue
        if cap := (CAPTION_PAREN.match(ln) or CAPTION_SLASH.match(ln)):
            inner = cap.group(1)
            for piece in re.split(r"\)\s*\(|/(?=\s*\w+\s*$)", inner)[:1]:
                if reason := paper_reason(piece, "TEXT_FIELD"):
                    c.removed.append(f"Pole „{_clean_label(piece)[0]}” — pominięte; {reason}.")
                else:
                    c.add(piece)
            continue
        if LEADER.search(ln):
            pieces = LEADER.split(ln)
            for piece in pieces[:-1]:  # tekst za ostatnią linią kropek to zwykle ciąg dalszy zdania
                if piece.strip(" .:-–,;"):
                    c.add(piece)
            c.last_colon_field = None
            continue
        if heading:
            c.section(heading)
            prev_label = ""
            continue
        if ln.rstrip("* ").endswith(":") and len(ln) <= 100:
            c.last_colon_field = c.add(ln)
            prev_label = ln
            continue
        if sparse and len(ln) <= 50 and len(ln.split()) <= 7 and ln[:1].isupper() and not ln.endswith("."):
            c.add(ln)
            continue
        prev_label = ln if len(ln) <= 100 else ""

    for table in doc.tables or []:
        _table(c, table)

    # F-14: organ, dane wnioskodawcy, kontakt i RODO wstawia builder z szablonów
    subject = [DraftSection(title=t, fields=fs, repeating=rep) for t, fs, rep in c.sections if fs]
    if not subject:
        subject = [DraftSection(title="Treść wniosku", fields=[
            DraftField(label="Treść wniosku", type="TEXTAREA", required=True,
                       hint="Nie udało się automatycznie rozpoznać pól formularza — opisz swoją sprawę.")])]
    consents = list(dict.fromkeys(c.consents))
    if consents:
        subject.append(DraftSection(title="Oświadczenia", fields=[
            DraftField(label=t, type="CONSENT_SECTION", required=True) for t in consents]))

    return Draft(title=title or "Wniosek", pages=[DraftPage(title="Przedmiot wniosku", sections=subject)],
                 organ=organ or ""), c.removed


def _table(c: _Collector, table: list[list[str]]) -> None:
    """Tabela: wiersz nagłówka + puste wiersze -> sekcja powtarzalna; „etykieta | pusto” -> pole."""
    rows = [[(cell or "").strip() for cell in row] for row in table if any((cell or "").strip() for cell in row)]
    if not rows:
        return
    header = rows[0]
    empty_rows = sum(1 for r in rows[1:] if not any(LEADER.sub("", x).strip(" .") for x in r[1:]))
    if len(header) >= 2 and all(0 < len(h) <= 60 for h in header) and len(rows) >= 2 and empty_rows >= len(rows) - 1:
        cols = [h for h in header if not re.fullmatch(r"(lp\.?|l\.p\.?|nr)", h, re.I)]
        if cols:
            c.section(cols[0] if len(cols) == 1 else "Lista", repeating=True)
            for h in cols:
                c.add(h)
            c.section(DEFAULT_SECTION)
            return
    for r in rows:
        if len(r) >= 2 and 0 < len(r[0]) <= 80 and not any(LEADER.sub("", x).strip(" .") for x in r[1:]):
            c.add(r[0])
