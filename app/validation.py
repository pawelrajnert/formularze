"""F-02: walidacja wgrywanego pliku (nazwa, rozmiar, typ z treści). Plik tylko w pamięci."""
import io
import zipfile
from pathlib import PurePath

import filetype
from fastapi import HTTPException, UploadFile

ALLOWED = {"pdf", "doc", "docx", "ods", "xlsx", "jpg", "jpeg", "jpe", "png"}  # .jpe: JPEG (data/7)
BAD_CHARS = set(";:><\\/|'*%$")
ODS_MIME = b"application/vnd.oasis.opendocument.spreadsheet"
CHUNK = 64 * 1024
MAX_UNZIPPED = 200 * 1024 * 1024  # python-docx/openpyxl rozpakowują całe XML-e do pamięci


def check_name(name: str | None) -> str:
    if (not name or not name.strip() or len(name) > 250 or BAD_CHARS & set(name)
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):  # R-10: także znaki sterujące (np. \x00)
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
            # rozmiary z nagłówków: zipfile i tak nie rozpakuje wpisu ponad zadeklarowany file_size
            if sum(i.file_size for i in z.infolist()) > MAX_UNZIPPED:
                raise HTTPException(413, f"Archiwum po rozpakowaniu przekracza {MAX_UNZIPPED // (1024 * 1024)} MB (zip-bomba?)")
            if any(n.lower().endswith("vbaproject.bin") or n.startswith(("Basic/", "Scripts/")) for n in names):
                raise HTTPException(415, "Plik zawiera makra lub skrypty - niedozwolone")
            if "word/document.xml" in names:
                return "docx"
            if "xl/workbook.xml" in names:
                return "xlsx"
            if "mimetype" in names and z.getinfo("mimetype").file_size <= 100 and z.read("mimetype").strip() == ODS_MIME:
                return "ods"
    except zipfile.BadZipFile:
        pass
    return None


# R-10 (audyt): Word zapisany pod „starą” albo „nową” końcówką to dalej dokument Word — urzędy tak robią
# (data/5, data/7: plik .DOC z treścią DOCX; dla formularza 7 to jedyny plik Word). Przyjmujemy i czytamy wg TREŚCI.
_SAME_KIND = {("doc", "docx"), ("docx", "doc")}
_ALIASES = {"jpeg": "jpg", "jpe": "jpg"}


def check_content(data: bytes, ext: str) -> str:
    """Typ z treści musi pasować do rozszerzenia. Zwraca typ, wg którego czytamy plik (np. 'docx' dla .doc z DOCX)."""
    if ext in {"docx", "xlsx", "ods"} or data[:4] == b"PK\x03\x04":  # ZIP: zawsze spis (makra, zip-bomba)
        actual = _zip_kind(data) if data[:4] == b"PK\x03\x04" else filetype.guess_extension(data)
    else:
        actual = filetype.guess_extension(data)
    want = _ALIASES.get(ext, ext)
    if actual == want:
        return ext
    if (want, actual) in _SAME_KIND:
        return actual
    raise HTTPException(415, f"Treść pliku ({actual or 'nieznany typ'}) nie zgadza się z rozszerzeniem .{ext}")
