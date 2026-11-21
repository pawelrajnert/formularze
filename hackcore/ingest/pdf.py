"""C-02: PDF — warstwa tekstowa pypdfium2, strony bez tekstu -> render 300 DPI -> OCR."""
import pypdfium2 as pdfium

from hackcore.document import Document, IngestError, register
from hackcore.ingest.tools import normalize_text, ocr_image

MIN_TEXT_CHARS = 30
OCR_DPI = 300


@register("pdf")
def load_pdf(data: bytes, max_pages: int | None = None) -> Document:
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as e:
        raise IngestError(f"Uszkodzony lub zaszyfrowany PDF: {e}") from e
    pages: list[str] = []
    ocr_used = False
    try:
        n = len(pdf) if max_pages is None else min(len(pdf), max(0, max_pages))
        for i in range(n):
            page = pdf[i]
            try:
                tp = page.get_textpage()
                text = normalize_text(tp.get_text_range())
                tp.close()
                if len("".join(text.split())) < MIN_TEXT_CHARS:
                    bitmap = page.render(scale=OCR_DPI / 72, grayscale=True)
                    img = bitmap.to_pil()
                    bitmap.close()
                    ocr = ocr_image(img)
                    ocr_used = True
                    if len(ocr) > len(text):
                        text = ocr
            finally:
                page.close()
            pages.append(text)
    finally:
        pdf.close()
    return Document.from_pages(pages or [""], "pdf", ocr_used=ocr_used)
