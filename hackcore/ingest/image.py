"""C-03: JPG/PNG -> Tesseract. Strona = klatka obrazu albo kawałek A4 długiego obrazu (split_tall)."""
import io
import os
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageSequence, UnidentifiedImageError

from hackcore.document import Document, IngestError, register
from hackcore.ingest.tools import ocr_image, split_tall

Image.MAX_IMAGE_PIXELS = 120_000_000  # ochrona przed "decompression bomb", A4 @600 DPI ~ 35 Mpx


def _load_image(data: bytes, max_pages: int | None = None, fmt: str = "jpg") -> Document:
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise IngestError(f"Nie można odczytać obrazu ({fmt}): {e}") from e
    parts: list[Image.Image] = []
    for frame in ImageSequence.Iterator(img):
        for part in split_tall(frame.copy()):  # strony sklejone w jeden długi obraz -> osobne strony
            if max_pages is not None and len(parts) >= max_pages:
                break
            parts.append(part)
    return Document.from_pages(_ocr_all(parts) or [""], fmt, ocr_used=True)


def ocr_workers() -> int:
    """OCR_WORKERS z env (domyślnie min(4, liczba CPU)); 1 = po kolei."""
    try:
        return max(1, int(os.environ.get("OCR_WORKERS", "")))
    except ValueError:
        return max(1, min(4, os.cpu_count() or 1))


def _ocr_all(parts: list[Image.Image]) -> list[str]:
    """R-02: kawałki obrazu OCR-owane równolegle (każdy to osobny proces tesseracta), kolejność stron zachowana."""
    workers = min(ocr_workers(), len(parts))
    if workers <= 1:
        return [ocr_image(p) for p in parts]
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")  # tesseract sam nie wątkuje -> procesy nie walczą o rdzenie
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(ocr_image, parts))


@register("jpg")
def load_jpg(data: bytes, max_pages: int | None = None) -> Document:
    return _load_image(data, max_pages, "jpg")


@register("png")
def load_png(data: bytes, max_pages: int | None = None) -> Document:
    return _load_image(data, max_pages, "png")
