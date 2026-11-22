"""F-10: propozycje nowych słowników z wyniki/*.json (+ wzorce data/1, data/5) -> wyniki/slowniki/proponowane_slowniki.json.

Użycie: python -m scripts.propose_dictionaries
"""
import json
from pathlib import Path

from app.form_builder.dictionary_proposals import analyze

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "wyniki" / "slowniki" / "proponowane_slowniki.json"  # podkatalog: wyniki/*.json to tylko formularze


def sources() -> list[tuple[str, Path]]:
    out = [(p.stem, p) for p in sorted((ROOT / "wyniki").glob("*.json")) if p.stem.isdigit()]
    for nr in ("1", "5"):  # oficjalne wzorce konfiguracji
        out += [(nr, p) for p in sorted((ROOT / "data" / nr).rglob("konfiguracja*.json"))][:1]
    return sorted(out, key=lambda x: int(x[0]))


def main() -> None:
    src = sources()
    forms = [json.loads(p.read_text("utf-8")) for _, p in src]
    proposals, remaining = analyze(forms, [i for i, _ in src])
    OUT.write_text(json.dumps({
        "opis": ("Propozycje nowych słowników współdzielonych (F-10), wyznaczone automatycznie z list wyboru "
                 "w formularzach. Do akceptacji przez urzędnika; po akceptacji pole dostaje dictionaryName."),
        "zrodla": [{"formularz": i, "plik": p.relative_to(ROOT).as_posix(), "tytul": f.get("title", "")}
                   for (i, p), f in zip(src, forms)],
        "proponowaneSlowniki": proposals,
        "pozostaleListy": remaining,
    }, ensure_ascii=False, indent=2), "utf-8")
    for p in proposals:
        forms_ = sorted({w["formularz"] for w in p["wystapienia"]}, key=int)
        print(f"{p['nazwa']}: {len(p['pozycje'])} pozycji, formularze {forms_}, pewność {p['pewnosc']}")
    print(f"pozostałe listy: {len(remaining)} -> {OUT.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
