"""F-12: generuje wyniki/<nr>.json dla formularzy do oceny. Użycie: python -m scripts.generate_wyniki [nr ...]"""
import json
import sys
from pathlib import Path

from app.pipeline import convert_document

ROOT = Path(__file__).resolve().parent.parent
FORMS = ["2", "3", "4", "6", "7", "8", "9"]
PREFERRED = ["docx", "pdf", "xlsx", "odt", "ods", "doc", "png", "jpg", "jpeg"]  # najlepszy tekst najpierw


def pick(folder: Path) -> Path:
    files = [p for p in folder.rglob("*") if p.is_file() and "wizualizacja" not in p.name.lower()]
    by_ext = {p.suffix.lower().lstrip("."): p for p in files}
    return next(by_ext[e] for e in PREFERRED if e in by_ext)


def main(forms: list[str]) -> None:
    for nr in forms:
        src = pick(ROOT / "data" / nr)
        out = convert_document(src.read_bytes(), src.suffix.lower().lstrip("."), True)
        (ROOT / "wyniki" / f"{nr}.json").write_text(json.dumps(out["form"], ensure_ascii=False, indent=2), "utf-8")
        t = out["trace"]
        print(f"{nr}: {src.name} -> źródło={t['source']} błędy={len(t.get('rules_errors') or [])} "
              f"do sprawdzenia={len(t['changes']['check'])} {str(t.get('reason') or '')[:120]}", flush=True)
        for c in t["changes"]["check"]:
            print("   ?", c[:160], flush=True)


if __name__ == "__main__":  # import (np. pick() w innym skrypcie) nie może nadpisać wyniki/
    main(sys.argv[1:] or FORMS)
