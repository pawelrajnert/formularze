"""Zewnętrzne binarki: Tesseract (OCR) i LibreOffice (DOC/ODS -> DOCX/XLSX).

Odnajdywanie: env (TESSERACT_CMD / SOFFICE_CMD) -> PATH -> domyślna ścieżka instalacji na Windows.
"""
import functools
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageOps

from hackcore.document import IngestError, MissingDependency

_WIN_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
_WIN_SOFFICE = (r"C:\Program Files\LibreOffice\program\soffice.exe",
                r"C:\Program Files (x86)\LibreOffice\program\soffice.exe")

MIN_OCR_WIDTH = 2000      # węższe obrazy powiększamy (Tesseract lubi ~300 DPI, x-height >= 20 px)
SOFFICE_TIMEOUT_S = float(os.environ.get("SOFFICE_TIMEOUT", "120"))
# S-01: profil LO z wyłączonymi makrami (poziom "bardzo wysoki" + DisableMacrosExecution) - makra z DOC/ODS nie ruszą
_NO_MACROS = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema">
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
<item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
</oor:items>
"""


def _find(env: str, names: tuple[str, ...], fallbacks: tuple[str, ...]) -> str | None:
    if os.environ.get(env):
        return os.environ[env]
    for n in names:
        if p := shutil.which(n):
            return p
    return next((f for f in fallbacks if Path(f).is_file()), None)


def find_tesseract() -> str | None:
    return _find("TESSERACT_CMD", ("tesseract",), (_WIN_TESSERACT,))


def find_soffice() -> str | None:
    return _find("SOFFICE_CMD", ("soffice", "libreoffice"), _WIN_SOFFICE)


# ---------------------------------------------------------------- OCR

def ocr_lang() -> str:
    return os.environ.get("OCR_LANG", "pol")


@functools.cache
def _tesseract_ready(lang: str) -> str:
    import pytesseract
    cmd = find_tesseract()
    if cmd is None:
        raise MissingDependency(
            "Brak Tesseract OCR — potrzebny do skanów i obrazów. Zainstaluj: "
            "Debian/Ubuntu `apt install tesseract-ocr tesseract-ocr-pol`, "
            "Windows: instalator UB-Mannheim (https://github.com/UB-Mannheim/tesseract/wiki) z językiem polskim, "
            "albo ustaw TESSERACT_CMD na ścieżkę do tesseract.")
    pytesseract.pytesseract.tesseract_cmd = cmd
    try:
        have = set(pytesseract.get_languages(config=""))
    except Exception as e:
        raise MissingDependency(f"Tesseract ({cmd}) nie działa: {e}") from e
    missing = [x for x in lang.split("+") if x not in have]
    if missing:
        raise MissingDependency(
            f"Tesseract nie ma danych językowych {missing} (OCR_LANG={lang}). Zainstaluj np. "
            "`apt install tesseract-ocr-pol` albo dodaj pol.traineddata do katalogu tessdata.")
    return cmd


def preprocess(img: Image.Image) -> Image.Image:
    """Odcienie szarości + powiększenie małych obrazów. Binaryzację robi Tesseract (Otsu)."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, "white")
        img = Image.alpha_composite(bg, img)
    img = img.convert("L")
    if img.width < MIN_OCR_WIDTH:
        f = MIN_OCR_WIDTH / img.width
        img = img.resize((MIN_OCR_WIDTH, round(img.height * f)), Image.Resampling.LANCZOS)
    return img


A4_RATIO = 2 ** 0.5


def split_tall(img: Image.Image) -> list[Image.Image]:
    """Obraz z kilkoma stronami A4 sklejonymi w pionie -> lista stron.

    Tesseract ma limit 32767 px wysokości, a krótsze kawałki OCR-uje szybciej i stabilniej.
    Cięcie w najjaśniejszym wierszu w okolicy granicy strony (żeby nie przeciąć linii tekstu).
    """
    page_h = round(img.width * A4_RATIO)
    if img.height <= page_h * 1.15:
        return [img]
    gray = img.convert("L")
    w = gray.width
    out, top = [], 0
    while img.height - top > page_h * 1.15:
        target = top + page_h
        lo, hi = max(top + page_h // 2, target - page_h // 20), min(img.height - 1, target + page_h // 20)
        band = gray.crop((0, lo, w, hi + 1)).resize((max(1, w // 8), hi - lo + 1))
        px = band.load()
        sums = [sum(px[x, y] for x in range(band.width)) for y in range(band.height)]
        best = max(sums)  # najjaśniejszy wiersz; wśród remisów najbliższy granicy strony
        cut = lo + min((y for y, v in enumerate(sums) if v >= best), key=lambda y: abs(lo + y - target))
        out.append(img.crop((0, top, img.width, cut)))
        top = cut
    out.append(img.crop((0, top, img.width, img.height)))
    return out


def ocr_image(img: Image.Image) -> str:
    engine = os.environ.get("OCR_ENGINE", "tesseract").lower()
    if engine != "tesseract":
        raise MissingDependency(
            f"OCR_ENGINE={engine} nieobsługiwany — dostępny tylko 'tesseract' "
            "(rapidocr nie ma modelu dla polskich znaków diakrytycznych).")
    import pytesseract
    lang = ocr_lang()
    _tesseract_ready(lang)
    # psm 3 = automatyczny układ strony; preserve_interword_spaces pomaga przy formularzach w kolumnach
    text = pytesseract.image_to_string(preprocess(img), lang=lang,
                                       config="--psm 3 -c preserve_interword_spaces=1")
    return normalize_text(text)


def normalize_text(text: str) -> str:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    out: list[str] = []
    for ln in lines:  # zwiń wielokrotne puste linie
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()


# ---------------------------------------------------------------- LibreOffice

def soffice_convert(data: bytes, src_ext: str, target: str) -> bytes:
    """Konwersja w tymczasowym katalogu (sprzątany zaraz po), osobny profil LO na wywołanie."""
    cmd = find_soffice()
    if cmd is None:
        raise MissingDependency(
            f"Brak LibreOffice — potrzebny do plików .{src_ext}. Zainstaluj: "
            "Debian/Ubuntu `apt install libreoffice-writer-nogui libreoffice-calc-nogui`, "
            "Windows: https://www.libreoffice.org/download/ (albo ustaw SOFFICE_CMD).")
    with tempfile.TemporaryDirectory(prefix="hackcore-lo-") as tmp:
        t = Path(tmp)
        src = t / f"in.{src_ext}"
        src.write_bytes(data)
        out_dir = t / "out"
        (t / "profile" / "user").mkdir(parents=True)
        (t / "profile" / "user" / "registrymodifications.xcu").write_text(_NO_MACROS, "utf-8")
        args = [cmd, f"-env:UserInstallation={(t / 'profile').as_uri()}",
                "--headless", "--norestore", "--nolockcheck",
                "--convert-to", target, "--outdir", str(out_dir), str(src)]
        try:
            r = subprocess.run(args, capture_output=True, timeout=SOFFICE_TIMEOUT_S,
                               env={**os.environ, "HOME": tmp})
        except subprocess.TimeoutExpired as e:
            raise IngestError(f"LibreOffice: przekroczony czas konwersji .{src_ext} ({SOFFICE_TIMEOUT_S:.0f} s)") from e
        out = out_dir / f"in.{target}"
        if not out.is_file():
            msg = (r.stderr or r.stdout).decode(errors="replace").strip()[:300]
            raise IngestError(f"LibreOffice nie skonwertował .{src_ext} -> .{target} (kod {r.returncode}): {msg}")
        return out.read_bytes()
