"""F-10: propozycje nowych słowników współdzielonych z gotowych formularzy COI (bez LLM, deterministycznie).

Szukamy pól wyboru (SELECT/RADIO/CHECKBOX) z zamkniętą listą opcji, które warto wynieść do słownika:
- nie Tak/Nie, nie pole z szablonów standardowych (config/section_templates), nie istniejący słownik;
- podobne listy z różnych formularzy / pól łączymy (normalizacja + podobieństwo zbiorów opcji);
- propozycja przechodzi tylko, gdy ma >= 3 pozycje ORAZ lista się powtarza (>= 2 pola) albo jest długa (>= 6 pozycji).
  Pozostałe listy trafiają do `remaining_candidates` (do ręcznej oceny), żeby nie zaśmiecać propozycji.
"""
import json
import re
from pathlib import Path

import yaml

from app.form_builder.enrich import CHOICE, norm

ROOT = Path(__file__).resolve().parents[2]
MIN_ITEMS = 3
LONG_LIST = 6
SEARCH_FROM = 10  # od tylu pozycji włączamy wyszukiwanie w liście (jak Kraje)

YES_NO = {"tak", "nie"}
# opcje zbyt ogólne, by na ich podstawie uznać dwie listy za ten sam słownik
GENERIC_OPTIONS = {"inne", "inny", "inna", "brak", "nie dotyczy", "pozostale", "tak", "nie"}
STOP = {"na", "w", "z", "do", "i", "o", "od", "po", "lub", "oraz", "dla", "przy", "ze", "sie", "a"}
# początki tytułów, które nie niosą treści nazwy słownika
TITLE_PREFIX = re.compile(r"^(wybierz|wskaz|zaznacz|podaj|preferowany|preferowana|preferowane)\b\s*")
DICT_NOUN = re.compile(r"^(RODZAJ|TYP|SPOSOB|KATEGORIA|FORMA|POWOD|CEL|STATUS|DYSCYPLIN)")
# wycinki z istniejących słowników (Słowniki.docx: Województwo, Powiat, Gmina, Miejscowość, Kraje, Numery kierunkowe)
KNOWN_VALUES = {
    "dolnoslaskie", "kujawsko pomorskie", "lubelskie", "lubuskie", "lodzkie", "malopolskie", "mazowieckie", "opolskie",
    "podkarpackie", "podlaskie", "pomorskie", "slaskie", "swietokrzyskie", "warminsko mazurskie", "wielkopolskie",
    "zachodniopomorskie", "polska", "niemcy", "ukraina", "czechy", "slowacja", "litwa", "francja", "+48",
}


def _known_dictionaries() -> set[str]:
    cfg = yaml.safe_load((ROOT / "config" / "field_rules.yaml").read_text("utf-8"))
    names = set(cfg.get("dictionaries") or {})
    return {norm(n).replace(" ", "_").upper() for n in names} | {"WOJEWODZTWO", "POWIAT", "GMINA", "MIEJSCOWOSC"}


def _template_tech_names() -> set[str]:
    out: set[str] = set()

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("techName"), str):
                out.add(o["techName"])
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for p in sorted((ROOT / "config" / "section_templates").glob("*.json")):
        walk(json.loads(p.read_text("utf-8")))
    return out


KNOWN = _known_dictionaries()
TEMPLATE_FIELDS = _template_tech_names()


def _tokens(text: str) -> set[str]:
    return {t for t in norm(text).split() if t not in STOP}


def _same_option(a: str, b: str) -> bool:
    if norm(a) == norm(b):
        return True
    ta, tb = _tokens(a), _tokens(b)
    return len(ta & tb) >= 2 and len(ta & tb) / len(ta | tb) >= 0.75


def _base_tech(tech: str) -> str:
    """'plec_psa_2' -> 'plec_psa' (pola powtórzone w formularzu dostają sufiks)."""
    return re.sub(r"_\d+$", "", tech or "")


def _code(name: str) -> str:
    words = norm(name).upper().split()
    code = ""
    for w in words:  # max ~40 znaków, cięcie na granicy słowa
        if code and len(code) + 1 + len(w) > 40:
            break
        code = f"{code}_{w}" if code else w
    return code or "POZYCJA"


def _dict_name(titles: list[str]) -> str:
    """Nazwa techniczna z tytułu pola: 'Sposób oznakowania psa' -> 'SPOSOB_OZNAKOWANIA_PSA'.

    Pierwszeństwo mają tytuły zaczynające się od rzeczownika „słownikowego” (rodzaj, typ, sposób...), potem krótsze."""
    cleaned = []
    for t in titles:
        t = re.sub(r"\(.*?\)", " ", t)  # „(wybierz wszystkie, które dotyczą)”
        n = TITLE_PREFIX.sub("", norm(t))
        words = [w for w in n.split() if w not in STOP][:4]
        if words:
            cleaned.append("_".join(words).upper())
    return min(cleaned, key=lambda s: (not DICT_NOUN.match(s), len(s), s)) if cleaned else "NOWY_SLOWNIK"


def choice_lists(form: dict, form_id: str = "") -> list[dict]:
    """Wszystkie pola wyboru z zamkniętą listą opcji, które w ogóle mogą być słownikiem."""
    out: list[dict] = []
    form_title = form.get("title") or form_id

    def walk(o):
        if isinstance(o, dict):
            if o.get("type") in CHOICE and not o.get("dictionaryName") and o.get("options"):
                opts = [str(x.get("name") or x.get("id") or "").strip() for x in o["options"]]
                opts = list(dict.fromkeys(x for x in opts if x))
                normed = {norm(x) for x in opts}
                if (opts and normed - YES_NO and o.get("techName") not in TEMPLATE_FIELDS
                        and len(normed & KNOWN_VALUES) < max(2, len(normed) // 2)):
                    out.append({"form": form_id, "formTitle": form_title, "techName": o.get("techName", ""),
                                "title": (o.get("title") or "").strip(), "type": o["type"], "options": opts})
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(form.get("tabs", form))
    return out


def _similar(a: list[str], b: list[str]) -> bool:
    """Dwie listy = ten sam słownik: >= połowa krótszej listy się pokrywa (nie licząc opcji ogólnych typu „inne”)."""
    a = [x for x in a if norm(x) not in GENERIC_OPTIONS]
    b = [x for x in b if norm(x) not in GENERIC_OPTIONS]
    if not a or not b:
        return False
    matched = sum(any(_same_option(x, y) for y in b) for x in a)
    return matched >= 1 and matched / min(len(a), len(b)) >= 0.5


def _cluster(lists: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for item in lists:
        hit = next((g for g in groups if any(_similar(item["options"], o["options"]) for o in g)), None)
        if hit is None:
            groups.append([item])
        else:
            hit.append(item)
    return groups


def _merge_items(group: list[dict]) -> list[str]:
    """Suma opcji z grupy; z wariantów tej samej opcji bierzemy najczęstszy, przy remisie krótszy."""
    variants: list[tuple[list[str], set[int]]] = []  # (warianty zapisu, z których pól pochodzą)
    for i, g in enumerate(group):
        for opt in g["options"]:
            # opcje z tego samego pola nigdy się nie scalają („Jezdnia do 20%” ≠ „Jezdnia powyżej 50%”)
            v = next((v for v in variants if i not in v[1] and _same_option(v[0][0], opt)), None)
            if v is None:
                variants.append(([opt], {i}))
            else:
                v[0].append(opt)
                v[1].add(i)
    return [min(set(v), key=lambda s: (-v.count(s), len(s), s)) for v, _ in variants]


def _proposal(group: list[dict]) -> dict:
    items = _merge_items(group)
    forms = list(dict.fromkeys(g["form"] for g in group))
    titles = list(dict.fromkeys(g["title"] for g in group if g["title"]))
    form_titles = list(dict.fromkeys(g["formTitle"] for g in group))
    types = sorted({g["type"] for g in group})
    codes: list[str] = []
    for it in items:
        c, i = _code(it), 2
        while c in codes:
            c, i = f"{_code(it)}_{i}", i + 1
        codes.append(c)

    why = []
    if len(forms) >= 2:
        why.append(f"ta sama lista wyboru występuje w {len(forms)} formularzach ({', '.join(forms)})")
    elif len(group) >= 2:
        why.append(f"lista powtarza się w {len(group)} polach jednego formularza (sekcja powtarzalna)")
    if len(items) >= LONG_LIST:
        why.append(f"długa zamknięta lista ({len(items)} pozycji) - łatwiej ją utrzymywać centralnie niż w każdym polu")
    if len(group) > 1 and len({tuple(g["options"]) for g in group}) > 1:
        why.append("warianty zapisu różnią się między polami - słownik ujednolici wartości")

    return {
        "nazwa": _dict_name(titles),
        "etykieta": min(titles, key=len) if titles else "",
        "opis": f"Zamknięta lista {len(items)} pozycji dla pola „{min(titles, key=len) if titles else ''}”.",
        "zastosowanie": (f"Pola typu {'/'.join(types)} w formularzach: {'; '.join(form_titles)}. "
                         "Podpięcie: field.dictionaryName = nazwa słownika zamiast listy options."),
        "struktura": {"multiLevelTree": False, "searchEnabled": len(items) >= SEARCH_FROM, "pozycja": ["kod", "nazwa"]},
        "pozycje": [{"kod": c, "nazwa": it} for c, it in zip(codes, items)],
        "wystapienia": [{"formularz": g["form"], "tytulFormularza": g["formTitle"], "techName": g["techName"],
                         "tytulPola": g["title"], "typ": g["type"]} for g in group],
        "uzasadnienie": "; ".join(why),
        "pewnosc": "wysoka" if len(forms) >= 2 else "srednia",
    }


def _qualifies(p: dict) -> bool:
    n = len(p["pozycje"])
    return n >= MIN_ITEMS and (len(p["wystapienia"]) >= 2 or n >= LONG_LIST) and p["nazwa"] not in KNOWN


def analyze(forms: list[dict], ids: list[str] | None = None) -> tuple[list[dict], list[dict]]:
    """(propozycje, pozostałe listy do ręcznej oceny). `ids` - identyfikatory formularzy (np. numer z data/)."""
    ids = ids or [str(i + 1) for i in range(len(forms))]
    lists = [cl for f, i in zip(forms, ids) for cl in choice_lists(f, i)]
    proposals, rest = [], []
    for group in _cluster(lists):
        p = _proposal(group)
        (proposals if _qualifies(p) else rest).append(p)
    proposals.sort(key=lambda p: (p["pewnosc"] != "wysoka", -len(p["wystapienia"]), -len(p["pozycje"]), p["nazwa"]))
    # unikalne nazwy słowników
    seen: dict[str, int] = {}
    for p in proposals:
        if p["nazwa"] in seen:
            seen[p["nazwa"]] += 1
            p["nazwa"] = f"{p['nazwa']}_{seen[p['nazwa']]}"
        else:
            seen[p["nazwa"]] = 1
    remaining = [{"tytulPola": p["etykieta"], "formularze": sorted({w["formularz"] for w in p["wystapienia"]}),
                  "liczbaPozycji": len(p["pozycje"]),
                  "powod": "za mało pozycji" if len(p["pozycje"]) < MIN_ITEMS
                  else "pojedyncza krótka lista - do oceny przez urzędnika"}
                 for p in rest]
    return proposals, remaining


def propose_dictionaries(forms: list[dict], ids: list[str] | None = None) -> list[dict]:
    """Propozycje nowych słowników dla zbioru formularzy COI (JSON-y jak w wyniki/*.json)."""
    return analyze(forms, ids)[0]


def propose_for_form(form: dict, form_id: str = "") -> list[dict]:
    """Wariant dla jednego formularza (np. trace.proposedDictionaries w trybie debug)."""
    return propose_dictionaries([form], [form_id or form.get("title") or "1"])
