from app.form_builder.draft import Draft


def test_draft_contract_parses_sample():
    d = Draft.model_validate({
        "title": "Wniosek o ustalenie numeru porządkowego",
        "pages": [{"title": "Dane", "sections": [{"title": "Wnioskodawca", "fields": [
            {"label": "Rodzaj wnioskodawcy", "type": "RADIO", "required": True, "options": ["Osoba fizyczna", "Firma"]},
            {"label": "PESEL", "type": "TEXT_FIELD", "required": True, "validators": ["PESEL"],
             "show_if": {"field": "Rodzaj wnioskodawcy", "equals": "Osoba fizyczna"}},
        ]}]}],
    })
    assert d.pages[0].sections[0].fields[1].show_if.equals == "Osoba fizyczna"
    assert "$defs" in Draft.model_json_schema()


def test_llm_prompt_has_fewshot_and_fits_limit():
    # prompt F-06 (draft_llm); naprawę złych enumów (dawne clean()) testuje test_draft_llm::test_coerce_draft_fixes_bad_values
    import json
    from app.form_builder.draft_llm import MAX_CHUNK_CHARS, system_prompt
    sys_p = system_prompt()
    example = sys_p.split("Poprawny szkic dla przykładu:\n", 1)[1].split("\n", 1)[0]
    example2 = sys_p.split("Strony przedmiotu wniosku dla przykładu 2:\n", 1)[1]
    for ex in (example, example2):
        Draft.model_validate_json(ex)  # przykłady few-shot to poprawne szkice
    # F-14: przykład 1 = pola sterujące + tylko strony merytoryczne (Dane/Kontakt z szablonów)
    ex = Draft.model_validate_json(example)
    assert ex.organ and ex.applicant_kinds and [p.title for p in ex.pages] == ["Informacje o budynku"]
    assert "applicant_kinds" in sys_p and "show_if" in example2
    total = len(sys_p) + MAX_CHUNK_CHARS + len(json.dumps(Draft.model_json_schema(), ensure_ascii=False))
    assert total < 60_000  # ~15k tokenów przy ~4 znakach/token
