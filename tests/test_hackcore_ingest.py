"""C-02/C-03: ingest. Testy bez binarek zawsze; OCR/LibreOffice — skip, gdy brak (pełny przebieg w Dockerze)."""
import io
from pathlib import Path

import pytest

from hackcore import Document, IngestError, MissingDependency, UnsupportedFormat, load_document
from hackcore.document import PAGE_SEP
from hackcore.ingest import tools
from hackcore.ingest.office import BOX_CHECKED, BOX_EMPTY

DATA = Path(__file__).resolve().parent.parent / "data"
FILES = sorted(p for d in "123456789" for p in (DATA / d).rglob("*")
               if p.is_file() and p.suffix.lower() != ".json")

HAS_TESSERACT = tools.find_tesseract() is not None
HAS_SOFFICE = tools.find_soffice() is not None
needs_tesseract = pytest.mark.skipif(not HAS_TESSERACT, reason="brak Tesseracta (test w Dockerze)")
needs_soffice = pytest.mark.skipif(not HAS_SOFFICE, reason="brak LibreOffice (test w Dockerze)")

NEEDS = {".jpg": needs_tesseract, ".jpeg": needs_tesseract, ".jpe": needs_tesseract, ".png": needs_tesseract,
         ".doc": needs_soffice, ".ods": needs_soffice}


def _one(pattern: str) -> Path:
    hits = [p for p in FILES if p.match(pattern)]
    assert hits, pattern
    return hits[0]


# ---------------------------------------------------------------- AC C-03: każdy plik z data/1..9

@pytest.mark.parametrize("path", [pytest.param(p, id=f"{p.parent.parent.name}/{p.name}",
                                               marks=NEEDS.get(p.suffix.lower(), ()))
                                  for p in FILES])
def test_every_data_file_loads(path: Path):
    doc = load_document(path.read_bytes(), path.name)
    assert isinstance(doc, Document)
    assert doc.text.strip(), "pusty tekst"
    assert doc.text == PAGE_SEP.join(doc.pages)
    if path.suffix.lower() in (".jpg", ".jpeg", ".jpe", ".png"):
        assert doc.ocr_used
        assert len(doc.text) > 200


def test_data_present():
    assert len(FILES) >= 60


# ---------------------------------------------------------------- PDF

def test_pdf_text_layer_no_ocr():
    p = _one("8/*/Deklaracja o wysokości opłaty.pdf")
    doc = load_document(p.read_bytes(), p.name)
    assert doc.source_format == "pdf" and not doc.ocr_used
    assert len(doc.pages) == 6
    assert "DEKLARACJA O WYSOKOŚCI MIESIĘCZNEJ OPŁATY" in doc.pages[0]


def test_pdf_max_pages():
    p = _one("9/*/Wniosek o przyznanie stypendium.pdf")
    full = load_document(p.read_bytes(), p.name)
    head = load_document(p.read_bytes(), p.name, max_pages=3)
    assert len(head.pages) == 3 and head.pages == full.pages[:3]


def _blank_pdf() -> bytes:
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument.new()
    pdf.new_page(595, 842)
    buf = io.BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def test_pdf_without_text_goes_to_ocr(monkeypatch):
    calls = []
    monkeypatch.setattr("hackcore.ingest.pdf.ocr_image", lambda img: calls.append(img.size) or "TEKST Z OCR " * 5)
    doc = load_document(_blank_pdf(), "skan.pdf")
    assert doc.ocr_used and "TEKST Z OCR" in doc.text
    assert calls and calls[0][0] == pytest.approx(595 * 300 / 72, abs=2)  # render 300 DPI


def test_pdf_broken():
    with pytest.raises(IngestError):
        load_document(b"%PDF-1.7 to nie jest pdf", "x.pdf")


# ---------------------------------------------------------------- DOCX

def _docx_bytes(build) -> bytes:
    import docx
    d = docx.Document()
    build(d)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_docx_order_tables_and_merged_cells():
    def build(d):
        d.add_paragraph("Przed tabelą")
        t = d.add_table(rows=2, cols=3)
        a = t.cell(0, 0).merge(t.cell(0, 1))
        a.text = "Scalona"
        t.cell(0, 2).text = "C"
        t.cell(1, 0).text = "PESEL"
        t.cell(1, 2).text = "Nazwisko"
        d.add_paragraph("Po tabeli")

    doc = load_document(_docx_bytes(build), "f.docx")
    lines = doc.text.splitlines()
    assert lines[0] == "Przed tabelą" and lines[-1] == "Po tabeli"
    assert doc.text.count("Scalona") == 1
    assert doc.tables == [[["Scalona", "C"], ["PESEL", "", "Nazwisko"]]]


def test_docx_checkboxes():
    from docx.oxml import parse_xml
    from docx.oxml.ns import nsdecls

    def build(d):
        p = d.add_paragraph()
        p._p.append(parse_xml(f'<w:r {nsdecls("w")}><w:sym w:font="Wingdings" w:char="F0A8"/></w:r>'))
        p.add_run(" Tak ")
        p._p.append(parse_xml(f'<w:r {nsdecls("w")}><w:sym w:font="Wingdings" w:char="F078"/></w:r>'))
        p.add_run(" Nie")
        p2 = d.add_paragraph()
        p2._p.append(parse_xml(
            f'<w:r {nsdecls("w")}><w:fldChar w:fldCharType="begin"><w:ffData><w:checkBox>'
            '<w:default w:val="0"/><w:checked/></w:checkBox></w:ffData></w:fldChar></w:r>'))
        p2.add_run("Zgoda")

    doc = load_document(_docx_bytes(build), "f.docx")
    assert f"{BOX_EMPTY} Tak {BOX_CHECKED} Nie" in doc.text
    assert f"{BOX_CHECKED} Zgoda" in doc.text


def test_docx_textboxes_not_duplicated():
    p = _one("2/*/Wniosek o zwrot opłaty skarbowej.docx")  # 260 pól tekstowych (mc:Choice + mc:Fallback)
    doc = load_document(p.read_bytes(), p.name)
    assert doc.text.count("Wniosek o zwrot opłaty skarbowej") == 1


def test_docx_header_and_footer():
    """D-01: nagłówek przed treścią, stopka po niej, tekst powtórzony w kilku sekcjach raz."""
    import docx
    d = docx.Document()
    d.sections[0].header.paragraphs[0].text = "Załącznik nr 2 do uchwały"
    d.sections[0].footer.paragraphs[0].text = "* niepotrzebne skreślić"
    d.add_paragraph("Wniosek o coś")
    buf = io.BytesIO()
    d.save(buf)
    lines = load_document(buf.getvalue(), "x.docx").text.splitlines()
    assert lines == ["Załącznik nr 2 do uchwały", "Wniosek o coś", "* niepotrzebne skreślić"]


def test_docx_broken():
    with pytest.raises(IngestError):
        load_document(b"PK\x03\x04 uszkodzony", "x.docx")


# ---------------------------------------------------------------- XLSX

def test_xlsx_rows_sheets_merged():
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "A"
    ws["A1"] = "Nagłówek scalony"
    ws.merge_cells("A1:C1")
    ws.append(["Imię", None, 3.0])
    ws2 = wb.create_sheet("B")
    ws2["B2"] = "Drugi arkusz"
    buf = io.BytesIO()
    wb.save(buf)

    doc = load_document(buf.getvalue(), "f.xlsx")
    assert len(doc.pages) == 2
    assert doc.pages[0] == "[Arkusz: A]\nNagłówek scalony\nImię | 3"
    assert doc.text.count("Nagłówek scalony") == 1
    assert doc.tables[0] == [["Nagłówek scalony", ""], ["Imię", "3"]]  # pusta kolumna B usunięta
    assert doc.tables[1] == [["Drugi arkusz"]]


def test_xlsx_shapes_and_comments():
    """D-01: wzór krajowy (gov.pl) trzyma listę załączników w polach tekstowych, a uwagi w komentarzach komórek."""
    import zipfile
    import openpyxl
    from openpyxl.comments import Comment
    wb = openpyxl.Workbook()
    wb.active["A1"] = "Wniosek"
    wb.active["A1"].comment = Comment("Pole obowiązkowe", "urząd")
    buf = io.BytesIO()
    wb.save(buf)
    with zipfile.ZipFile(buf, "a") as z:
        z.writestr("xl/drawings/drawing1.xml", '<xdr:wsDr xmlns:xdr="x" xmlns:a="y"><xdr:sp><xdr:txBody>'
                   '<a:p><a:r><a:t>1. Mapa &amp; wypis</a:t></a:r></a:p></xdr:txBody></xdr:sp></xdr:wsDr>')
    doc = load_document(buf.getvalue(), "f.xlsx")
    assert doc.pages[-1] == "[Pola tekstowe i komentarze]\nPole obowiązkowe\n1. Mapa & wypis"


def test_xlsx_broken():
    with pytest.raises(IngestError):
        load_document(b"nie zip", "x.xlsx")


# ---------------------------------------------------------------- obrazy / OCR

def test_image_preprocess_upscales_and_grayscales():
    from PIL import Image
    out = tools.preprocess(Image.new("RGBA", (500, 700), (255, 0, 0, 128)))
    assert out.mode == "L" and out.width == tools.MIN_OCR_WIDTH and out.height == 2800


def test_split_tall_image_into_a4_pages():
    from PIL import Image, ImageDraw
    w, page_h = 400, round(400 * 2 ** 0.5)
    img = Image.new("L", (w, page_h * 3), 255)
    d = ImageDraw.Draw(img)
    for y in range(20, page_h * 3 - 20, 30):  # "linie tekstu" poza marginesami stron
        if y % page_h > 20 and y % page_h < page_h - 20:
            d.rectangle((20, y, w - 20, y + 12), fill=0)
    parts = tools.split_tall(img)
    assert len(parts) == 3 and sum(p.height for p in parts) == img.height
    assert tools.split_tall(Image.new("L", (w, page_h), 255)) != [] and len(tools.split_tall(Image.new("L", (w, page_h)))) == 1


def test_image_broken():
    with pytest.raises(IngestError):
        load_document(b"\xff\xd8 to nie jpeg", "x.jpg")


def test_missing_tesseract_message(monkeypatch):
    from PIL import Image
    monkeypatch.setattr(tools, "find_tesseract", lambda: None)
    tools._tesseract_ready.cache_clear()
    buf = io.BytesIO()
    Image.new("RGB", (50, 50), "white").save(buf, "PNG")
    try:
        with pytest.raises(MissingDependency, match="tesseract-ocr-pol"):
            load_document(buf.getvalue(), "x.png")
    finally:
        tools._tesseract_ready.cache_clear()


def test_missing_soffice_message(monkeypatch):
    monkeypatch.setattr(tools, "find_soffice", lambda: None)
    with pytest.raises(MissingDependency, match="LibreOffice"):
        load_document(b"\xd0\xcf\x11\xe0 doc", "x.doc")


def test_unsupported_and_empty():
    with pytest.raises(UnsupportedFormat):
        load_document(b"x", "a.txt")
    with pytest.raises(IngestError):
        load_document(b"", "a.pdf")


@needs_tesseract
def test_ocr_polish_labels():
    p = _one("4/*/Wniosek o wynajęcie świetlicy.jpg")
    doc = load_document(p.read_bytes(), p.name)
    low = doc.text.lower()
    assert "wniosek" in low and "świetlic" in low


@needs_soffice
def test_doc_and_ods_via_libreoffice():
    doc = load_document(_one("8/*/Deklaracja o wysokości opłaty.doc").read_bytes(), "a.doc")
    assert doc.source_format == "doc" and "DEKLARACJA" in doc.text
    ods = load_document(_one("8/*/Deklaracja o wysokości opłaty.ods").read_bytes(), "a.ods")
    assert ods.source_format == "ods" and ods.tables and "DEKLARACJA" in ods.text
