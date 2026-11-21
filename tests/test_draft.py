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
    import json
    from app.form_builder.llm_draft import messages
    msgs = messages("x" * 100_000)
    Draft.model_validate_json(msgs[2]["content"])  # przykład few-shot to poprawny szkic
    assert msgs[2]["role"] == "assistant" and "RADIO" in msgs[2]["content"] and "show_if" in msgs[2]["content"]
    total = sum(len(m["content"]) for m in msgs) + len(json.dumps(Draft.model_json_schema(), ensure_ascii=False))
    assert total < 60_000  # ~15k tokenów przy ~4 znakach/token


def test_llm_draft_cleans_bad_enums(monkeypatch):
    import json
    from types import SimpleNamespace
    from app.form_builder import llm_draft as m
    raw = json.dumps({"title": "T", "finish_text": {"type": "TEXT_BLOCK", "content": "RODO"}, "pages": [
        {"title": "Pusta", "sections": [{"title": "S", "fields": []}]},
        {"title": "Dane", "sections": [{"title": "S", "fields": [
            {"label": "Telefon", "type": "PHONE", "validators": ["PHONE", "EMAIL"], "dictionary": "Miasta"}]}]}]})
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=raw))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: resp)))
    monkeypatch.setattr(m, "_client", lambda: client)
    d = m.llm_draft("tekst")
    f = d.pages[0].sections[0].fields[0]
    assert d.finish_text == "RODO" and len(d.pages) == 1 and (f.type, f.validators, f.dictionary) == ("TEXT_FIELD", ["EMAIL"], "")


def test_clean_coerces_non_string_values():
    import json
    from app.form_builder.llm_draft import clean
    raw = {"title": "T", "pages": [{"title": "P", "sections": [{"title": "S", "show_if": {"field": "Pełnomocnik", "equals": True}, "fields": [
        {"label": "Pełnomocnik", "type": "RADIO", "options": ["Tak", 2], "default": ["Tak"]},
        {"label": "Kwota", "type": "NUMBER", "default": 17, "show_if": {"field": "Pełnomocnik", "equals": ["Tak"]}},
        "śmieć",
    ]}]}]}
    d = clean(json.dumps(raw))
    s = d.pages[0].sections[0]
    assert s.show_if.equals == "Tak"
    assert [f.default for f in s.fields] == ["Tak", "17"]
    assert s.fields[0].options == ["Tak", "2"] and s.fields[1].show_if.equals == "Tak"
