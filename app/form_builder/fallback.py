"""Heurystyczny szkic formularza bez LLM (fallback, gdy brak klucza albo LLM zawiedzie)."""
import re

from app.form_builder.draft import Draft, DraftField, DraftPage, DraftSection

MAX_FIELDS = 60
FILLER = re.compile(r"(\.{3,}|…{2,}|_{3,})")


def _clean(s: str) -> str:
    s = FILLER.sub(" ", s.replace("*", ""))
    return re.sub(r"\s+", " ", s).strip(" :.|_-–\t")


def _is_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    upper = len(letters) >= 3 and all(c.isupper() for c in letters)
    numbered = bool(re.match(r"^(\d{1,2}|[IVX]{1,5})[.)]\s+\S", line))
    return (upper or numbered) and ":" not in line and not FILLER.search(line) and len(line) <= 80


def heuristic_draft(text: str, title_hint: str) -> Draft:
    lines = [ln.strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if len(_clean(ln)) >= 2]
    title = next((_clean(ln) for ln in lines if ln.lower().startswith("wniosek")), "") \
        or next((_clean(ln) for ln in lines if len(_clean(ln)) >= 5), "") or title_hint or "Wniosek"
    title = title[:255]

    sections: list[DraftSection] = []
    sec_title, fields, seen = "Dane wniosku", [], set()
    count, finish = 0, ""
    for i, ln in enumerate(lines):
        if count >= MAX_FIELDS:
            break
        if re.search(r"klauzula informacyjna|RODO", ln, re.I):  # pouczenie RODO -> strona końcowa, nie pola
            finish = "\n".join(lines[i:])
            break
        if _is_heading(ln) and _clean(ln) != title:
            if fields:
                sections.append(DraftSection(title=sec_title, fields=fields))
            sec_title, fields = _clean(ln)[:120], []
            continue
        if ":" in ln or FILLER.search(ln):
            label = (_clean(ln.split(":")[0]) if ":" in ln else "") or _clean(ln)
            label = re.sub(r"\s\.(?=\s)", "", label)[:200]
            if len(label) < 2 or len(label) > 120 or label.lower() in seen:  # długie = proza, nie etykieta
                continue
            seen.add(label.lower())
            fields.append(DraftField(label=label, type="TEXT_FIELD", required="*" in ln))
            count += 1
    if fields:
        sections.append(DraftSection(title=sec_title, fields=fields))
    if not sections:
        sections = [DraftSection(title="Wniosek", fields=[DraftField(label="Treść wniosku", type="TEXTAREA", required=True)])]
    return Draft(title=title, pages=[DraftPage(title="Wniosek", sections=sections)], finish_text=finish)
