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
