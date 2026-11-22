# AI Act, RODO i zatwierdzenie urzędnika

Jak spełniamy wymagania AI Act (art. 4, 14, 50) i RODO oraz jak działa bramka zatwierdzenia urzędnika (F-18).

[← powrót do README](../README.md)

## Zatwierdzenie urzędnika (playbook, F-18)

Zasada: AI proponuje, a człowiek zatwierdza. Przy `APPROVAL_REQUIRED=true` formularz z `/convert` ma status DRAFT i nie da się go pobrać, dopóki urzędnik go nie zatwierdzi. Bramka siedzi w procesie, więc nie zależy od dobrej woli urzędnika.

1. **Pochodzenie:** `/convert` zwraca podpisany token z SHA-256 pliku źródłowego i wygenerowanego JSON-a oraz nazwą modelu.
2. **Obejrzenie całości:** przycisk „Zatwierdź” odblokowuje się dopiero, gdy urzędnik otworzy w podglądzie każdą stronę formularza. To przeciwdziała klikaniu bez czytania.
3. **Elementy wrażliwe potwierdzane osobno**, bez „zaznacz wszystko”: zgodność z oryginałem, pola tylko do odczytu i dane z profilu zaufanego, pola wymagane, zgody i RODO, opłaty i numery kont. Do tego oświadczenie „Sprawdziłem zgodność formularza z oryginałem i przepisami”.
4. **Kontrola serwera:** `/approve` odrzuca JSON zmieniony poza systemem (409), formularz, który nie przechodzi `rules_check` (422), niepełną listę kontrolną i nieobejrzane strony (400).
5. **Rekord audytu obok JSON-a**, a nie w nim, więc JSON zostaje czysty: login z JWT, data, SHA-256 źródła i wyniku, model, hash promptu i szablonów, wynik lintera, czas przeglądu. Rekord nie zawiera danych osobowych z dokumentu. Zapisuje się w `AUDIT_DIR`, a „Pobierz JSON” zapisuje go jako `<nazwa>.approval.json` obok formularza.

Podstawa: AI Act art. 14 (nadzór człowieka) i art. 50 (przejrzystość). Dalsze kroki (diff ręcznych poprawek, zasada czterech oczu, akceptacja każdej zmiany z listy „co zmieniliśmy”) są opisane w SPEC jako rozwój.

## AI Act i RODO

**Klasyfikacja ryzyka:** system przygotowuje konfigurację formularza dla urzędnika. Nie ocenia obywatela i nie decyduje o świadczeniach, więc nie jest systemem wysokiego ryzyka w rozumieniu rozporządzenia (UE) 2024/1689. Załącznik III pkt 5a obejmuje ocenę uprawnień do świadczeń i usług publicznych, a tego nie robimy.

| Wymóg | Jak go spełniamy | Gdzie |
|---|---|---|
| Art. 14: nadzór człowieka | AI proponuje, urzędnik zatwierdza. Przy `APPROVAL_REQUIRED=true` eksport jest zablokowany do zatwierdzenia, a urzędnik musi obejrzeć każdą stronę i osobno potwierdzić elementy wrażliwe | [Zatwierdzenie urzędnika](#zatwierdzenie-urzędnika-playbook-f-18) |
| Art. 50: przejrzystość treści AI | Przy `COMPLIANCE_ENABLED=true` odpowiedź ma blok `ai_disclosure` (czy użyto AI, model, hash promptu, które części są deterministyczne, `human_verified`). Rekord zatwierdzenia zapisuje model i wersje promptu oraz szablonów. Wszystko leży **obok** JSON-a, więc JSON formularza zostaje czysty i zgodny ze schematem | `/convert`, `AUDIT_DIR` |
| Art. 4: kompetencje w zakresie AI | Lista kontrolna w UI mówi urzędnikowi, co sprawdzić: zgodność z oryginałem, pola tylko do odczytu i dane z profilu zaufanego, pola wymagane, zgody i RODO, opłaty i konta | panel „Zatwierdzenie urzędnika” |
| Wyjaśnialność wyniku | Karta „Co zmieniliśmy względem oryginału” (`trace.changes`): co usunęliśmy z papieru i dlaczego, co doszło ze standardu COI (z podstawą prawną), co poprawiliśmy i co urzędnik musi sprawdzić | UI, `/convert?debug=true` |
| Ograniczenie roli AI | LLM opisuje tylko część merytoryczną. Strony „Dane” i „Kontakt i zgody”, identyfikatory, siatkę i stronę końcową robi deterministyczny builder z szablonów, a każdy wynik przechodzi walidator `rules_check` | `app/form_builder/` |
| RODO: minimalizacja danych | Przy `COMPLIANCE_ENABLED=true` PESEL, NIP, REGON, IBAN, e-mail, telefon i nr dowodu z wypełnionego dokumentu są maskowane, zanim tekst trafi do LLM. Logi klienta LLM nie zawierają treści dokumentu. Wariant lokalny (profil `local-llm`, Ollama) sprawia, że dane w ogóle nie opuszczają urzędu | `hackcore/privacy.py`, [LLM: API albo model lokalny](#llm-api-albo-model-lokalny) |
| Otwarte modele | Rejestr `config/models.yaml` dopuszcza tylko modele z otwartymi wagami i licencją z allowlisty (Apache-2.0). Licencje sprawdzone na kartach modeli | `config/models.yaml` |

Obie flagi są domyślnie wyłączone (`false`), żeby jury mogło od razu pobrać JSON. W pracy urzędu włączamy obie.
