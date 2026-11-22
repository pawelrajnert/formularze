# Ewaluacja Form2Norm względem ground truth

Wygenerowano: 2026-11-22 09:27 · commit `5c03a62` · `python -m scripts.evaluate --convert`

| Nr | GT | Techn. OK | Pola GT/wynik | Kompletność | Precyzja | F1 | Zmyślenia | Warianty | Warunki | Wymagane | Załączniki | Słowniki (pola / pokrycie) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | wzorzec COI | tak | 4/4 | 100.0% | 100.0% | 100.0% | 0 | — | — | — | — | 8 / 100.0% |
| 2 | dokument źródłowy | tak | 6/9 | 100.0% | 100.0% | 100.0% | 0 | 100.0% | 100.0% | 100.0% | — | 7 / — |
| 3 | dokument źródłowy | tak | 2/9 | 100.0% | 33.3% | 50.0% | 0 | 100.0% | 100.0% | 100.0% | — | 5 / 0.0% |
| 4 | dokument źródłowy | tak | 10/14 | 90.0% | 92.9% | 91.4% | 0 | 100.0% | 100.0% | 90.0% | 100.0% | 5 / — |
| 5 | wzorzec COI | tak | 5/9 | 80.0% | 77.8% | 78.9% | 0 | 100.0% | 50.0% | — | 100.0% | 7 / — |
| 6 | dokument źródłowy | tak | 19/33 | 94.7% | 100.0% | 97.3% | 0 | — | — | 88.9% | 100.0% | 9 / 66.7% |
| 7 | dokument źródłowy | tak | 11/29 | 90.9% | 48.3% | 63.1% | 0 | 100.0% | 100.0% | 75.0% | 0.0% | 8 / 75.0% |
| 8 | dokument źródłowy | tak | 21/59 | 85.7% | 92.9% | 89.2% | 1 | 100.0% | 25.0% | 50.0% | 50.0% | 12 / 83.3% |
| 9 | dokument źródłowy | tak | 25/98 | 88.0% | 96.9% | 92.2% | 0 | 50.0% | 50.0% | 88.9% | 80.0% | 19 / 70.0% |
| **średnia** | | **9/9** | | **92.1%** | **82.5%** | **84.7%** | **1** | **92.9%** | **75.0%** | **84.7%** | **71.7%** | **80 / 65.8%** |

## Definicje metryk

- **Poprawność techniczna** — app.rules_check.check(form) == [] oraz oryginalny importowanyPlikJsonSchemat (Draft 2020-12) bez błędów.
- **Kompletność pól (recall)** — % pól GT, dla których w części merytorycznej wyniku jest pole z labelem zawierającym wszystkie klucze GT.
- **Precyzja** — % pól wejściowych części merytorycznej wyniku dopasowanych do pola/wariantu/załącznika GT (pola z poza_zakresem — treść standardowa COI — nie są liczone).
- **F1** — Średnia harmoniczna kompletności i precyzji.
- **Zmyślenia** — Liczba pól wyniku pasujących do listy nie_powinno_byc (rzeczy, których nie ma w papierze).
- **Warianty** — % wyborów z papieru odwzorowanych jako RADIO/SELECT/CHECKBOX zawierające wszystkie opcje.
- **Warunki** — % pól warunkowych GT, których pole lub sekcja ma states SHOW z warunkiem na właściwą opcję.
- **Wymagane** — % pól GT oznaczonych wymagane: true, które w wyniku mają walidację REQUIRED.
- **Załączniki** — % pozycji listy załączników GT odwzorowanych jako FILE_UPLOADER.
- **Słowniki** — Liczba pól z dictionaryName w całym formularzu; pokrycie = % pól kraj/województwo/gmina/miejscowość/numer kierunkowy w części merytorycznej ze słownikiem.

## Ograniczenia

- GT dla formularzy 2–4 i 6–9 napisaliśmy sami z treści dokumentów źródłowych (bez zaglądania do wyników); dla 1 i 5 wygenerowano go z oficjalnych wzorców COI.
- Dopasowanie po słowach kluczowych (początek słowa, alternatywy) — synonimy spoza listy kluczy liczą się jako brak, a ogólne klucze mogą zawyżać trafienia.
- GT obejmuje tylko część merytoryczną; dane wnioskodawcy, kontakt, podpis, RODO, pełnomocnictwo i opłata pochodzą z szablonów standardowych COI.
- Wynik LLM jest niedeterministyczny — kolejna konwersja może dać inne liczby; ocena gotowego JSON-a jest deterministyczna.

## Szczegóły per formularz

### 1. Wniosek o ustalenie numeru porządkowego nieruchomości  (`eval/out/1.json`)

### 2. Wniosek o zwrot opłaty skarbowej  (`wyniki/2.json`)

### 3. Wniosek o wydanie zaświadczenia  (`wyniki/3.json`)
- Pola spoza GT (obniżają precyzję): Czy posiadasz użytki rolne lub gospodarstwo rolne na terenie Gminy Młynary?; Okres posiadania gospodarstwa rolnego (od - do); Ilość użytków rolnych (w hektarach fizycznych); Ilość użytków rolnych (w hektarach przeliczeniowych); Ilość dzierżawionych użytków rolnych (w hektarach fizycznych); Ilość dzierżawionych użytków rolnych (w hektarach przeliczeniowych)

### 4. Wniosek o wynajęcie lub użyczenie świetlicy wiejskiej  (`wyniki/4.json`)
- Brakujące pola GT: Oświadczenie: zapoznałem się z warunkami wynajmu
- Wymagane bez REQUIRED: Oświadczenie: zapoznałem się z warunkami wynajmu
- Pola spoza GT (obniżają precyzję): Potwierdzam zapoznanie się z warunkami wynajmu świetlicy wiejskiej

### 5. Wniosek o stwierdzenie nadpłaty podatku  (`eval/out/5.json`)
- Brakujące pola GT: Nazwa podatku
- Brakujące warunki: nazw podat ⇐ zalicz pocz (brak pola)
- Pola spoza GT (obniżają precyzję): Opis załącznika; Plik załącznika

### 6. Wniosek o wydanie zezwolenia na zajęcie pasa drogowego w celu prowadzenia robót  (`wyniki/6.json`)
- Brakujące pola GT: Adres osoby odpowiedzialnej (zam.)
- Wymagane bez REQUIRED: Rodzaj robót i sposób wykonania

### 7. Wniosek o wydanie zezwolenia na hodowanie lub utrzymywanie psów ras uznawanych za agresywne  (`wyniki/7.json`)
- Brakujące pola GT: Adres miejsca utrzymywania psa
- Wymagane bez REQUIRED: Pochodzenie psa (metryka, rodowód, poprzedni właściciel); Adres miejsca utrzymywania psa
- Brakujące załączniki: szczepi|wscieklizn
- Pola spoza GT (obniżają precyzję): Imię poprzedniego właściciela; Nazwisko poprzedniego właściciela; Kraj (Adres poprzedniego właściciela); Ulica (Adres poprzedniego właściciela); Numer budynku (Adres poprzedniego właściciela); Numer lokalu (Adres poprzedniego właściciela); Kod pocztowy (Adres poprzedniego właściciela); Miejscowość (Adres poprzedniego właściciela); Miejscowość (za granicą) (Adres poprzedniego właściciela); Kod pocztowy (za granicą) (Adres poprzedniego właściciela); Ulica; Numer budynku; Numer lokalu; Miejscowość; Kod pocztowy

### 8. Deklaracja o wysokości miesięcznej opłaty za gospodarowanie odpadami komunalnymi  (`wyniki/8.json`)
- Brakujące pola GT: Współmałżonek – nazwisko, imię (B.2.5); Współmałżonek – adres zamieszkania (B.2.6); Współmałżonek – PESEL (B.2.7)
- Wymagane bez REQUIRED: Suma opłaty (E.1.51 / E.2.67)
- Brakujące warunki: malzon nazwisk|imie ⇐ wspolnosc|majatk (brak pola); malzon pesel ⇐ wspolnosc|majatk (brak pola); kwota|poz zalacznik ⇐ tak
- Brakujące załączniki: upowazn|pelnomocn; inne|inny
- Zmyślenia: Oświadczam, że dane zawarte w deklaracji są prawdziwe i kompletne.
- Pola spoza GT (obniżają precyzję): Inne załączniki (opis); Oświadczam, że dane zawarte w deklaracji są prawdziwe i kompletne.; Zamieszkuję na nieruchomości, której dotyczy deklaracja.

### 9. Wniosek o przyznanie stypendium, nagrody lub wyróżnienia sportowego Rady Miasta  (`wyniki/9.json`)
- Brakujące pola GT: Pełnomocnik klubu – imię; Pełnomocnik klubu – nazwisko; Pełnomocnik klubu – seria i numer dowodu osobistego
- Wymagane bez REQUIRED: Opinia macierzystego klubu
- Brakujące warianty: Wnioskodawca; Dane reprezentanta czy pełnomocnika klubu; Sposób korespondencji z urzędem; Kandydat pełnoletni czy nieletni
- Brakujące warunki: klub nazwa|nazwy ⇐ klub; epuap adres|skrzyn ⇐ epuap; doreczen|edoreczen adres|skrzyn ⇐ doreczen|edoreczen; rodzic|opiekun ⇐ nielet|niepelnolet|maloletn
- Brakujące załączniki: pelnomocn
- Pola spoza GT (obniżają precyzję): Numer kierunkowy; Czy wniosek składa reprezentant klubu?; Numer kierunkowy
