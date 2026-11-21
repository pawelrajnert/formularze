"""Ekstrakcja tekstu z dokumentu. TYMCZASOWY adapter — do podmiany na hackcore C-02/C-03."""
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

from app import config

SOFFICE_TIMEOUT = 60
# macOS: LibreOffice.app nie wkłada soffice do PATH
SOFFICE_MAC = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
W_P = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"


class IngestError(Exception):
    """Nie da się wyciągnąć tekstu (brak narzędzia, uszkodzony plik) -> 422."""


def _ocr(img) -> str:
    try:
        import pytesseract
        return pytesseract.image_to_string(img, lang=config.settings.ocr_lang)
    except Exception as e:  # TesseractNotFoundError, brak pakietu językowego
        raise IngestError(f"OCR niedostępny: {e}") from e


def _pdf(data: bytes) -> str:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(data)
    text = "\n".join(p.get_textpage().get_text_range() for p in pdf)
    if text.strip():
        return text
    return "\n".join(_ocr(p.render(scale=300 / 72).to_pil()) for p in pdf)  # skan -> OCR


def _docx(data: bytes) -> str:
    import docx
    d = docx.Document(io.BytesIO(data))
    lines = [p.text for p in d.paragraphs]
    for t in d.tables:
        for row in t.rows:
            lines.append(" | ".join(dict.fromkeys(c.text.strip() for c in row.cells)))  # scalone komórki się powtarzają
    if not "".join(lines).strip():  # docx z PDF-a: cały tekst w polach tekstowych (w:txbxContent)
        ps = [p for p in d.element.body.iter(W_P) if not any(a.tag.endswith("}Fallback") for a in p.iterancestors())]
        lines = [t for p in ps if (t := "".join(x.text or "" for x in p.xpath("./w:r/w:t|./w:hyperlink/w:r/w:t"))).strip()]
    return "\n".join(lines)


def _xlsx(data: bytes) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    return "\n".join(
        " | ".join(str(v).strip() for v in row if v is not None and str(v).strip())
        for ws in wb.worksheets for row in ws.iter_rows(values_only=True)
    )


def _convert(data: bytes, ext: str, to: str) -> bytes:
    exe = shutil.which("soffice") or shutil.which("libreoffice") or (SOFFICE_MAC if Path(SOFFICE_MAC).exists() else None)
    if not exe:
        raise IngestError(f"Brak LibreOffice (soffice) — nie można przetworzyć pliku .{ext}")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in.{ext}"
        src.write_bytes(data)
        # osobny profil: równoległe wywołania soffice nie blokują się nawzajem
        cmd = [exe, f"-env:UserInstallation=file://{tmp}/profile", "--headless", "--convert-to", to, "--outdir", tmp, str(src)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=SOFFICE_TIMEOUT, check=True)
            return (Path(tmp) / f"in.{to}").read_bytes()
        except (subprocess.SubprocessError, OSError) as e:
            raise IngestError(f"Konwersja .{ext} -> .{to} nie powiodła się: {e}") from e


def extract_text(data: bytes, ext: str) -> str:
    try:
        if ext == "pdf":
            return _pdf(data)
        if ext == "docx":
            return _docx(data)
        if ext == "xlsx":
            return _xlsx(data)
        if ext == "doc":
            return _docx(_convert(data, ext, "docx"))
        if ext == "ods":
            return _xlsx(_convert(data, ext, "xlsx"))
        if ext in ("jpg", "jpeg", "png"):
            from PIL import Image
            return _ocr(Image.open(io.BytesIO(data)))
    except IngestError:
        raise
    except Exception as e:  # uszkodzony plik itp.
        raise IngestError(f"Nie udało się odczytać pliku .{ext}: {e}") from e
    raise IngestError(f"Nieobsługiwany format: {ext}")
