"""R-15: oficjalne słowniki COI wszędzie, gdzie pasują w części merytorycznej (jak w szablonach standardowych).

COI udostępnia tylko: Województwo / Powiat / Gmina / Miejscowość (w JSON-ie drzewo TERYT_4G_DOWODOWY), Kraje
i Numery kierunkowe („Hacknation - Słowniki”) — innych `dictionaryName` nie używamy, bo import by ich nie znalazł.
Działa ogólnie (po etykietach), więc także na nowych dokumentach:

1. Grupa adresowa z polem „Kraj” -> układ jak w szablonie COI: Kraj (Kraje, domyślnie Polska); przy Polsce Kod
   pocztowy + Miejscowość z drzewa TERYT; przy innym kraju Kod pocztowy i Miejscowość tekstem (warunki show_if).
2. Miejscowość w sekcji bez pola Kraj (adres tylko w Polsce: działka, świetlica, miejsce robót) -> drzewo TERYT.
3. Każdy telefon -> wcześniej „Numer kierunkowy” (słownik Numery kierunkowe), chyba że już jest.

Wyjątek: sekcja powtarzalna z kilkoma adresami w środku (etykiety z dopiskiem) — builder trzyma jedno drzewo TERYT na
sekcję, więc tam Miejscowość zostaje tekstem.
"""
import re

from app.form_builder.draft import Draft, DraftField, DraftSection, ShowIf
from app.form_builder.enrich import norm

TERYT = "TERYT_4G_DOWODOWY"
POLSKA, INNY = "Polska", "Inny kraj"
_KRAJ = re.compile(r"^(kraj|panstwo)\b")
_MIEJSC = re.compile(r"^miejscowosc\b")
_KOD = re.compile(r"^kod pocztowy\b")
_TEL = re.compile(r"\b(numer telefonu|telefon\w*|nr tel\w*|tel komorkow\w*)\b")
_PREFIX = re.compile(r"kierunkow|prefiks")
_ABROAD = re.compile(r"za granica|zagranic")


def _suffix(label: str, base: str) -> str:
    """„Miejscowość (Adres klubu)” -> „ (Adres klubu)” — dopisek grupy w sekcji powtarzalnej."""
    return label[len(base):] if label.lower().startswith(base.lower()) else ""


def _address_groups(sec: DraftSection) -> list[tuple[DraftField, DraftField, DraftField | None]]:
    """(Kraj, Miejscowość, Kod pocztowy) z tym samym dopiskiem — pola jednej grupy adresowej."""
    out = []
    for k in sec.fields:
        if not _KRAJ.search(norm(k.label)) or k.type not in ("TEXT_FIELD", "SELECT"):
            continue
        suf = _suffix(k.label, "Kraj")
        m = next((f for f in sec.fields if _MIEJSC.search(norm(f.label)) and _suffix(f.label, "Miejscowość") == suf
                  and not _ABROAD.search(norm(f.label))), None)
        z = next((f for f in sec.fields if _KOD.search(norm(f.label)) and _suffix(f.label, "Kod pocztowy") == suf
                  and not _ABROAD.search(norm(f.label))), None)
        if m is not None and m.type == "TEXT_FIELD" and not m.dictionary:
            out.append((k, m, z))
    return out


def apply_dictionaries(draft: Draft, notes: list) -> Draft:
    for page in draft.pages:
        for sec in page.sections or []:
            several = sum(bool(_KRAJ.search(norm(f.label))) for f in sec.fields) > 1
            # 1. grupy adresowe z Krajem: Polska -> TERYT, inny kraj -> tekst
            for kraj, miej, kod in _address_groups(sec):
                if sec.repeating and several:
                    continue  # jedno drzewo TERYT na sekcję (builder) — kilka adresów w wierszu zostaje tekstem
                kraj.type, kraj.dictionary, kraj.options, kraj.default = "SELECT", "Kraje", [POLSKA, INNY], POLSKA
                pl, abroad = ShowIf(field=kraj.label, equals=POLSKA), ShowIf(field=kraj.label, equals=INNY)
                suf = _suffix(miej.label, "Miejscowość")
                new = []
                if kod is not None:
                    kod.show_if = kod.show_if or pl
                    new.append(DraftField(label=f"Kod pocztowy (za granicą){suf}", type="TEXT_FIELD", required=kod.required,
                                          show_if=abroad))
                miej_abroad = DraftField(label=f"Miejscowość (za granicą){suf}", type="TEXT_FIELD", required=miej.required,
                                         show_if=abroad)
                miej.type, miej.dictionary, miej.show_if = "SELECT", TERYT, miej.show_if or pl
                i = sec.fields.index(miej)
                sec.fields[i + 1:i + 1] = [miej_abroad, *new]
                notes.append(f"słowniki: {miej.label!r} -> drzewo TERYT (Polska), pola zagraniczne tekstem")
            # 2. Miejscowość w Polsce (sekcja bez pola Kraj)
            if not any(_KRAJ.search(norm(f.label)) for f in sec.fields):
                for f in sec.fields:
                    if (f.type == "TEXT_FIELD" and not f.dictionary and _MIEJSC.search(norm(f.label))
                            and not _ABROAD.search(norm(f.label))):
                        f.type, f.dictionary = "SELECT", TERYT
                        notes.append(f"słowniki: {f.label!r} -> drzewo TERYT (adres w Polsce)")
            # 3. telefon -> numer kierunkowy przed nim
            i = 0
            while i < len(sec.fields):
                f = sec.fields[i]
                prev = sec.fields[i - 1] if i else None
                if (f.type in ("TEXT_FIELD", "NUMBER") and _TEL.search(norm(f.label)) and not _PREFIX.search(norm(f.label))
                        and not (prev is not None and _PREFIX.search(norm(prev.label)))):
                    sec.fields.insert(i, DraftField(label="Numer kierunkowy", type="SELECT", dictionary="Numery kierunkowe",
                                                    show_if=f.show_if))
                    notes.append(f"słowniki: przed {f.label!r} dodano „Numer kierunkowy” (Numery kierunkowe)")
                    i += 1
                i += 1
    return draft
