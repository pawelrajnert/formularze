"""F-06: ręczny test szkicu z prawdziwym LLM.

użycie: .venv/Scripts/python scripts/try_draft.py <plik> [--no-llm] [--out draft.json]
Wczytuje formularze/.env (bez nadpisywania istniejących zmiennych), NIGDY nie wypisuje klucza.
Darmowy Mistral: 2 req/min — nie odpalaj w pętli.
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from hackcore import Document, LLMClient, load_document  # noqa: E402

from app.form_builder.builder import build  # noqa: E402
from app.form_builder.draft_llm import make_draft  # noqa: E402
from app.rules_check import check  # noqa: E402


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text("utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def local_text(path: Path) -> Document:
    """Zapas, gdy ingest hackcore jeszcze nie obsługuje formatu: python-docx / pypdfium2 (warstwa tekstowa)."""
    ext = path.suffix.lower()
    if ext == ".docx":
        import docx
        d = docx.Document(str(path))
        lines = [p.text for p in d.paragraphs if p.text.strip()]
        tables = [[[c.text.strip() for c in r.cells] for r in t.rows] for t in d.tables]
        lines += [" | ".join(dict.fromkeys(c for c in row if c)) for t in tables for row in t if any(row)]
        return Document.from_pages(["\n".join(lines)], "docx", tables=tables)
    if ext == ".pdf":
        import pypdfium2 as pdfium
        return Document.from_pages([p.get_textpage().get_text_range() for p in pdfium.PdfDocument(str(path))], "pdf")
    raise SystemExit(f"brak lokalnego ekstraktora dla {ext}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("file", type=Path)
    ap.add_argument("--no-llm", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args()
    load_env(ROOT / ".env")

    doc = None
    try:
        doc = load_document(a.file.read_bytes(), a.file.name)
    except Exception as e:  # noqa: BLE001
        print(f"ingest hackcore: {type(e).__name__}: {e}")
    if doc is None or len((doc.text or "").strip()) < 50:
        doc = local_text(a.file)
    llm = None if a.no_llm else LLMClient.from_env()
    print(f"plik: {a.file.name}  znaków: {len(doc.text)}  LLM: {'tak (' + llm.model + ')' if llm else 'nie'}"
          f"  klucz: {'ustawiony' if os.environ.get('LLM_API_KEY') else 'BRAK'}")

    r = make_draft(doc, llm)
    form = build(r.draft)
    errs = check(form)
    fields = [f for p in r.draft.pages for s in p.sections for f in s.fields]
    print(f"źródło: {r.source}  czas: {r.seconds:.1f} s  tytuł: {r.draft.title}")
    print(f"strony: {len(r.draft.pages)}  sekcje: {sum(len(p.sections) for p in r.draft.pages)}  pola: {len(fields)}"
          f"  show_if: {sum(1 for f in fields if f.show_if) + sum(1 for p in r.draft.pages for s in p.sections if s.show_if)}")
    for p in r.draft.pages:
        print(f"  [{p.title}] " + ", ".join(f"{s.title}({len(s.fields)})" for s in p.sections))
    print("removed_paper_elements:", *(f"  - {x}" for x in r.removed_paper_elements), sep="\n")
    print("warnings:", *(f"  - {x}" for x in r.warnings), sep="\n")
    print("rules_check:", "OK" if not errs else errs)
    if a.out:
        a.out.write_text(r.draft.model_dump_json(indent=2), "utf-8")
        print("zapisano", a.out)


if __name__ == "__main__":
    main()
