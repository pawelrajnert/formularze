"""F-02: walidacja wgrywanego pliku (nazwa, rozmiar, typ z treści). Plik tylko w pamięci."""
import io
import zipfile
from pathlib import PurePath

import filetype
from fastapi import HTTPException, UploadFile

ALLOWED = {"pdf", "doc", "docx", "ods", "xlsx", "jpg", "jpeg", "png"}
BAD_CHARS = set(";:><\\/|'*%$")
ODS_MIME = b"application/vnd.oasis.opendocument.spreadsheet"
CHUNK = 64 * 1024


def check_name(name: str | None) -> str:
    if not name or not name.strip() or len(name) > 250 or BAD_CHARS & set(name):
        raise HTTPException(400, "Niedozwolona nazwa pliku (pusta, > 250 znaków lub znaki ; : > < / \\ | ' * % $)")
    ext = PurePath(name).suffix.lower().lstrip(".")
    if ext not in ALLOWED:
        raise HTTPException(415, f"Nieobsługiwany typ pliku: .{ext}; dozwolone: {', '.join(sorted(ALLOWED))}")
    return ext


async def read_limited(file: UploadFile, max_bytes: int) -> bytes:
    buf = bytearray()
    while chunk := await file.read(CHUNK):
        buf += chunk
        if len(buf) > max_bytes:
            raise HTTPException(413, f"Plik większy niż {max_bytes // (1024 * 1024)} MB")
    return bytes(buf)


def _zip_kind(data: bytes) -> str | None:
    # tylko spis plików i mały 'mimetype' - bez rozpakowywania całości (zip-bomba)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = set(z.namelist())
            if "word/document.xml" in names:
                return "docx"
            if "xl/workbook.xml" in names:
                return "xlsx"
            if "mimetype" in names and z.getinfo("mimetype").file_size <= 100 and z.read("mimetype").strip() == ODS_MIME:
                return "ods"
    except zipfile.BadZipFile:
        pass
    return None


def check_content(data: bytes, ext: str) -> None:
    if ext in {"docx", "xlsx", "ods"}:
        actual = _zip_kind(data) if data[:4] == b"PK\x03\x04" else None
    else:
        actual = filetype.guess_extension(data)
    if actual != {"jpeg": "jpg"}.get(ext, ext):
        raise HTTPException(415, f"Treść pliku ({actual or 'nieznany typ'}) nie zgadza się z rozszerzeniem .{ext}")
