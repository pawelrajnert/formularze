"""C-03: JPG/PNG -> Tesseract. Strona = klatka obrazu albo kawałek A4 długiego obrazu (split_tall)."""
import io

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
    pages: list[str] = []
    for frame in ImageSequence.Iterator(img):
        for part in split_tall(frame.copy()):  # strony sklejone w jeden długi obraz -> osobne strony
            if max_pages is not None and len(pages) >= max_pages:
                break
            pages.append(ocr_image(part))
    return Document.from_pages(pages or [""], fmt, ocr_used=True)


@register("jpg")
def load_jpg(data: bytes, max_pages: int | None = None) -> Document:
    return _load_image(data, max_pages, "jpg")


@register("png")
def load_png(data: bytes, max_pages: int | None = None) -> Document:
    return _load_image(data, max_pages, "png")
