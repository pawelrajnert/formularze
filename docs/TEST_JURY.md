# Test „jak jury” — 69 plików na żywo przez REST API (22.11 ~07:00, `main` 551680b)

[← powrót do README](../README.md)

Procedura jak u komisji: kontener Docker z `main`, JWT, `POST /api/v1/forms/convert` po kolei dla **każdego** pliku z `data/1–9` (wszystkie formaty: PDF, DOC, DOCX, XLSX, ODS, JPG, JPEG, JPE, PNG; skany przez OCR). Każdy JSON sprawdzony: `rules_check` (schemat COI + reguły techniczne), **oryginalny** `importowanyPlikJsonSchemat` dosłownie i — z powodu literówki `repetingSectionGrid` w oryginale — schemat pytania na **każdym** poziomie. Skrypt: `python -m scripts.jury_test --url …`.

**Wynik:** 69 plików → **68/69 poprawny JSON w pierwszym przebiegu, 69/69 po ponowieniu** (jedyny błąd: klient testowy przerwał po 300 s przy `6/…ods`; serwer ukończył konwersję w 39 s — ponowione: 200, poprawny). **0 × szkic heurystyczny** — wszystko z LLM. Model: 14B w 49 przypadkach, zapasowy 8B w 19 (69 konwersji bez przerw = limit 2/min na model; jury tak nie wrzuca). Łączne czekanie na limit: 213 s na 69 plików.

| Format | Plików | Czas mediana | Max |
|---|---|---|---|
| DOCX | 8 | 14,8 s | 50,4 s |
| PDF | 9 | 15,2 s | 79,9 s |
| DOC (LibreOffice) | 9 | 31,7 s | 76,3 s |
| ODS (LibreOffice) | 8+1 | 29,7 s | 67,2 s |
| XLSX | 7 | 30,3 s | 64,2 s |
| JPG / JPEG / JPE / PNG (OCR) | 27 | 11,6–37,3 s | 60,2 s |

Najdłuższe: formularz 8 i 9 (najwięcej pól). OCR max 25 s. Pełna tabela niżej.

| Plik | Format | HTTP | Czas | Źródło | Model | OCR | Reguły | Schemat (korzeń/poziomy) | Do sprawdzenia |
|---|---|---|---|---|---|---|---|---|---|
| 1/Wniosek o ustalenie numeru porządkowego nieruchomości (1).png | png | 200 | 7.9 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 0 |
| 1/Wniosek o ustalenie numeru porządkowego nieruchomości.doc | doc | 200 | 6.8 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 1/Wniosek o ustalenie numeru porządkowego nieruchomości.docx | docx | 200 | 2.8 s | llm | ministral-8b-latest |  | 0 | 0/0 | 0 |
| 1/Wniosek o ustalenie numeru porządkowego nieruchomości.jpeg | jpeg | 200 | 5.1 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 0 |
| 1/Wniosek o ustalenie numeru porządkowego nieruchomości.jpg | jpg | 200 | 42.2 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 1 |
| 1/Wniosek o ustalenie numeru porządkowego nieruchomości.ods | ods | 200 | 5.1 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 1/Wniosek o ustalenie numeru porządkowego nieruchomości.pdf | pdf | 200 | 4.5 s | llm | ministral-8b-latest |  | 0 | 0/0 | 0 |
| 1/Wniosek o ustalenie numeru porządkowego nieruchomości.xlsx | xlsx | 200 | 5.2 s | llm | ministral-8b-latest |  | 0 | 0/0 | 0 |
| 2/Wniosek o zwrot opłaty skarbowej.doc | doc | 200 | 47.3 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 2/Wniosek o zwrot opłaty skarbowej.docx | docx | 200 | 10.0 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 2/Wniosek o zwrot opłaty skarbowej.jpeg | jpeg | 200 | 10.9 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 0 |
| 2/Wniosek o zwrot opłaty skarbowej.jpg | jpg | 200 | 7.5 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 0 |
| 2/Wniosek o zwrot opłaty skarbowej.ods | ods | 200 | 29.7 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 2/Wniosek o zwrot opłaty skarbowej.pdf | pdf | 200 | 10.7 s | llm | ministral-14b-latest |  | 0 | 0/0 | 1 |
| 2/Wniosek o zwrot opłaty skarbowej.png | png | 200 | 9.1 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 0 |
| 2/Wniosek o zwrot opłaty skarbowej.xlsx | xlsx | 200 | 9.4 s | llm | ministral-8b-latest |  | 0 | 0/0 | 0 |
| 3/Wniosek o wydanie zaświadczenia.doc | doc | 200 | 31.7 s | llm | ministral-14b-latest |  | 0 | 0/0 | 1 |
| 3/Wniosek o wydanie zaświadczenia.docx | docx | 200 | 6.5 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 3/Wniosek o wydanie zaświadczenia.jpeg | jpeg | 200 | 11.6 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 0 |
| 3/Wniosek o wydanie zaświadczenia.jpg | jpg | 200 | 8.1 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 0 |
| 3/Wniosek o wydanie zaświadczenia.ods | ods | 200 | 22.0 s | llm | ministral-14b-latest |  | 0 | 0/0 | 1 |
| 3/Wniosek o wydanie zaświadczenia.pdf | pdf | 200 | 14.7 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 3/Wniosek o wydanie zaświadczenia.png | png | 200 | 11.3 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 0 |
| 3/Wniosek o wydanie zaświadczenia.xlsx | xlsx | 200 | 9.2 s | llm | ministral-8b-latest |  | 0 | 0/0 | 0 |
| 4/Wniosek o wynajęcie świetlicy.doc | doc | 200 | 27.6 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 4/Wniosek o wynajęcie świetlicy.docx | docx | 200 | 14.8 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 4/Wniosek o wynajęcie świetlicy.jpeg | jpeg | 200 | 8.8 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 1 |
| 4/Wniosek o wynajęcie świetlicy.jpg | jpg | 200 | 6.4 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 2 |
| 4/Wniosek o wynajęcie świetlicy.ods | ods | 200 | 27.6 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 4/Wniosek o wynajęcie świetlicy.pdf | pdf | 200 | 14.0 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 4/Wniosek o wynajęcie świetlicy.png | png | 200 | 11.6 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 3 |
| 4/Wniosek o wynajęcie świetlicy.xlsx | xlsx | 200 | 30.3 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 5/Wniosek o stwierdzenie nadpłaty podatku.DOC | doc | 200 | 13.5 s | llm | ministral-14b-latest |  | 0 | 0/0 | 3 |
| 5/Wniosek o stwierdzenie nadpłaty podatku.docx | docx | 200 | 0.0 s | llm | ministral-14b-latest |  | 0 | 0/0 | 3 |
| 5/Wniosek o stwierdzenie nadpłaty podatku.jpeg | jpeg | 200 | 8.2 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 2 |
| 5/Wniosek o stwierdzenie nadpłaty podatku.JPG | jpg | 200 | 9.1 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 1 |
| 5/Wniosek o stwierdzenie nadpłaty podatku.ODS | ods | 200 | 24.1 s | llm | ministral-14b-latest |  | 0 | 0/0 | 1 |
| 5/Wniosek o stwierdzenie nadpłaty podatku.PDF | pdf | 200 | 15.2 s | llm | ministral-14b-latest |  | 0 | 0/0 | 1 |
| 5/Wniosek o stwierdzenie nadpłaty podatku.PNG | png | 200 | 8.8 s | llm | ministral-8b-latest | tak | 0 | 0/0 | 2 |
| 6/Wniosek o wydanie zezwolenia na zajęcie pasa drogowego.doc | doc | 200 | 17.8 s | llm | ministral-8b-latest |  | 0 | 0/0 | 1 |
| 6/Wniosek o wydanie zezwolenia na zajęcie pasa drogowego.docx | docx | 200 | 50.4 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 6/Wniosek o wydanie zezwolenia na zajęcie pasa drogowego.jpeg | jpeg | 200 | 56.2 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 0 |
| 6/Wniosek o wydanie zezwolenia na zajęcie pasa drogowego.jpg | jpg | 200 | 60.2 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 0 |
| 6/Wniosek o wydanie zezwolenia na zajęcie pasa drogowego.ods | ods | 0 | 449.2 s | — | — |  | — | —/— | ReadTimeout: timed out |
| 6/Wniosek o wydanie zezwolenia na zajęcie pasa drogowego.pdf | pdf | 200 | 79.9 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 6/Wniosek o wydanie zezwolenia na zajęcie pasa drogowego.png | png | 200 | 49.9 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 1 |
| 6/Wniosek o wydanie zezwolenia na zajęcie pasa drogowego.xlsx | xlsx | 200 | 54.8 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 7/Wniosek o wydanie zezwolenia na hodowanie.DOC | doc | 200 | 39.7 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 7/Wniosek o wydanie zezwolenia na hodowanie.JPE | jpe | 200 | 37.3 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 1 |
| 7/Wniosek o wydanie zezwolenia na hodowanie.JPG | jpg | 200 | 32.1 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 5 |
| 7/Wniosek o wydanie zezwolenia na hodowanie.ODS | ods | 200 | 32.8 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 7/Wniosek o wydanie zezwolenia na hodowanie.PDF | pdf | 200 | 30.9 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 7/Wniosek o wydanie zezwolenia na hodowanie.PNG | png | 200 | 22.3 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 2 |
| 8/Deklaracja o wysokości opłaty.doc | doc | 200 | 76.3 s | llm | ministral-14b-latest |  | 0 | 0/0 | 1 |
| 8/Deklaracja o wysokości opłaty.docx | docx | 200 | 46.2 s | llm | ministral-14b-latest |  | 0 | 0/0 | 1 |
| 8/Deklaracja o wysokości opłaty.jpeg | jpeg | 200 | 45.4 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 0 |
| 8/Deklaracja o wysokości opłaty.jpg | jpg | 200 | 38.3 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 2 |
| 8/Deklaracja o wysokości opłaty.ods | ods | 200 | 67.2 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 8/Deklaracja o wysokości opłaty.pdf | pdf | 200 | 45.2 s | llm | ministral-14b-latest |  | 0 | 0/0 | 3 |
| 8/Deklaracja o wysokości opłaty.png | png | 200 | 53.4 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 1 |
| 8/Deklaracja o wysokości opłaty.xlsx | xlsx | 200 | 64.2 s | llm | ministral-14b-latest |  | 0 | 0/0 | 2 |
| 9/Wniosek o przyznanie stypendium.doc | doc | 200 | 40.5 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 9/Wniosek o przyznanie stypendium.docx | docx | 200 | 46.0 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 9/Wniosek o przyznanie stypendium.jpeg | jpeg | 200 | 55.5 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 0 |
| 9/Wniosek o przyznanie stypendium.jpg | jpg | 200 | 50.0 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 0 |
| 9/Wniosek o przyznanie stypendium.ods | ods | 200 | 53.4 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 9/Wniosek o przyznanie stypendium.pdf | pdf | 200 | 40.7 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
| 9/Wniosek o przyznanie stypendium.png | png | 200 | 40.4 s | llm | ministral-14b-latest | tak | 0 | 0/0 | 0 |
| 9/Wniosek o przyznanie stypendium.xlsx | xlsx | 200 | 41.8 s | llm | ministral-14b-latest |  | 0 | 0/0 | 0 |
