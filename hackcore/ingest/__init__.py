"""C-02/C-03: loadery formatów. Import rejestruje je w hackcore.document._LOADERS.

Licencje (tylko permisywne): pypdfium2 (Apache-2.0/BSD), pytesseract + Tesseract (Apache-2.0),
python-docx (MIT), openpyxl (MIT), Pillow (MIT-CMU). LibreOffice (MPL-2.0) tylko jako osobny proces.
❌ PyMuPDF/fitz (AGPL), Surya/Marker (GPL).
"""
from hackcore.ingest import image, office, pdf  # noqa: F401
