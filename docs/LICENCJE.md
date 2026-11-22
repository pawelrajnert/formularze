# Licencje zależności

Brak GPL/AGPL — szczegóły i uzasadnienie dla MPL-2.0.

[← powrót do README](../README.md)

## Licencje

Wszystkie zależności to open source o licencjach permisywnych albo z weak copyleft na poziomie pliku. **Nie ma GPL ani AGPL.** Nie używamy PyMuPDF (AGPL). Licencje pakietów Pythona odczytano z metadanych w `.venv` (`importlib.metadata`).

| Zależność | Wersja | Licencja |
|---|---|---|
| fastapi (`[standard]`: uvicorn, starlette, httpx, jinja2…) | 0.121.3 | MIT (uvicorn, starlette, httpx: BSD-3-Clause) |
| python-multipart | 0.0.20 | Apache-2.0 |
| pytest | 9.0.1 | MIT |
| jsonschema (+ jsonschema-specifications, referencing, rpds-py, attrs) | 4.26.0 | MIT |
| pyjwt | 2.15.1 | MIT |
| filetype | 1.2.0 | MIT |
| openai | 3.57.0 | Apache-2.0 |
| pypdfium2 (PDFium w środku) | 5.15.2 | Apache-2.0 / BSD-3-Clause |
| python-docx | 1.2.0 | MIT |
| openpyxl (+ et_xmlfile) | 3.1.5 | MIT |
| pytesseract | 0.3.13 | Apache-2.0 |
| pillow | 13.0.0 | MIT-CMU (rodzina HPND, permisywna) |
| pyyaml | 6.0.4 | MIT |
| pydantic / pydantic-core | 2.14.4 / 2.50.5 | MIT |
| lxml (pośrednio, python-docx) | 6.1.3 | BSD-3-Clause |
| certifi (pośrednio, httpx) | 2026.11.20 | MPL-2.0 (niemodyfikowany pakiet danych) |
| JSONata (`web/vendor/jsonata.min.js`) | 2.2.2 | MIT |
| Tesseract OCR + `tesseract-ocr-pol` | Debian bookworm | Apache-2.0 |
| LibreOffice (headless) | Debian bookworm | MPL-2.0 |
| Ollama (opcjonalnie, profil `local-llm`) | 0.40.17 | MIT |
| Ministral 3 (14B / 8B), wagi modelu | — | Apache-2.0 |

Pozostałe pakiety pośrednie, czyli to, co ciągnie za sobą `fastapi[standard]` (np. anyio, click, rich, typer, websockets, uvloop, idna, urllib3, sentry-sdk), mają licencje MIT, BSD, ISC, Apache-2.0, PSF-2.0, 0BSD albo Unlicense.

**MPL-2.0 (LibreOffice, certifi)** to weak copyleft działający na poziomie pliku. Obowiązek udostępnienia zmian dotyczy tylko zmodyfikowanych plików objętych MPL. LibreOffice uruchamiamy jako osobny, niezmodyfikowany proces (`soffice --headless --convert-to`) i nie linkujemy go z naszym kodem. certifi to niezmieniony pakiet. Żaden z nich nie obejmuje licencją naszego kodu.

Obraz bazowy Debian zawiera standardowe narzędzia systemu (część na GPL), które nie są linkowane z aplikacją. To typowa sytuacja dla każdego obrazu opartego na Debianie.
