"""Ingest: dowolny plik (bytes) -> Document. Kontrakt SPEC §2.

C-01: kontrakt + rozpoznanie formatu. C-02 (PDF + OCR) i C-03 (pozostałe formaty) wypełniają _LOADERS.
Pliki tylko w pamięci; jeśli konwerter wymaga pliku (LibreOffice) — tempfile.TemporaryDirectory sprzątany od razu.
"""
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePath

PAGE_SEP = "\n\f\n"


@dataclass
class Document:
    text: str                       # pełny tekst (strony połączone PAGE_SEP)
    pages: list[str]
    source_format: str              # pdf|docx|doc|xlsx|ods|png|jpg
    ocr_used: bool = False
    tables: list[list[list[str]]] = field(default_factory=list)  # xlsx/ods/docx: tabela -> wiersze -> komórki

    @classmethod
    def from_pages(cls, pages: list[str], source_format: str, ocr_used: bool = False,
                   tables: list[list[list[str]]] | None = None) -> "Document":
        return cls(PAGE_SEP.join(pages), pages, source_format, ocr_used, tables or [])


class UnsupportedFormat(ValueError):
    pass


class IngestError(ValueError):
    """Pliku nie da się odczytać (uszkodzony / niezgodny z rozszerzeniem / pusty)."""


class MissingDependency(RuntimeError):
    """Brak zewnętrznej binarki (Tesseract, LibreOffice) — komunikat mówi, co zainstalować."""


# rozszerzenie -> znormalizowany format (w danych COI są np. .JPE, .DOC, .jpeg)
_FORMATS = {
    "pdf": "pdf", "docx": "docx", "doc": "doc", "xlsx": "xlsx", "ods": "ods",
    "png": "png", "jpg": "jpg", "jpeg": "jpg", "jpe": "jpg",
}

# loader(data, max_pages=None) -> Document; max_pages ignorowane przez formaty bez stron
Loader = Callable[..., Document]
_LOADERS: dict[str, Loader] = {}


def source_format(filename: str) -> str:
    ext = PurePath(filename).suffix.lower().lstrip(".")
    if ext not in _FORMATS:
        raise UnsupportedFormat(f"Nieobsługiwany format: .{ext}")
    return _FORMATS[ext]


def register(fmt: str) -> Callable[[Loader], Loader]:
    def deco(fn: Loader) -> Loader:
        _LOADERS[fmt] = fn
        return fn
    return deco


def load_document(data: bytes, filename: str, *, max_pages: int | None = None) -> Document:
    """bytes -> Document. max_pages: tylko pierwsze N stron (PDF), None = wszystkie.

    Wyjątki: UnsupportedFormat (rozszerzenie), IngestError (uszkodzony plik),
    MissingDependency (brak Tesseracta / LibreOffice).
    """
    fmt = source_format(filename)
    import hackcore.ingest  # noqa: F401  (rejestruje loadery; leniwie — bez cyklu importów)
    loader = _LOADERS.get(fmt)
    if loader is None:
        return Document.from_pages([""], fmt)
    if not data:
        raise IngestError(f"Pusty plik: {filename}")
    try:
        return loader(data, max_pages=max_pages)
    except (IngestError, MissingDependency, UnsupportedFormat):
        raise
    except Exception as e:  # biblioteki rzucają różne typy na uszkodzonych plikach
        raise IngestError(f"Nie udało się odczytać pliku {filename} ({fmt}): {type(e).__name__}: {e}") from e
