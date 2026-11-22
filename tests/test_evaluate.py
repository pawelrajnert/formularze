"""Ewaluacja względem ground truth: dopasowanie kluczy, metryki na małym przykładzie, generowanie raportu."""
import json

from scripts import evaluate as ev

UUID = "00000000-0000-4000-8000-{:012d}"


def _f(i, typ, title, **kw):
    return {"x": 0, "y": i, "rows": 1, "cols": 3, "field": {
        "id": UUID.format(i), "type": typ, "techName": f"p{i}", "title": title, "description": "",
        "options": kw.get("options", []), "validation": kw.get("validation", []), "readOnly": False,
        "repeatingSectionGrid": kw.get("grid", []), "states": kw.get("states", []), "questionOrder": i,
        "tooltipMessage": "", **({"dictionaryName": kw["dict"]} if "dict" in kw else {})}}


def _form():
    opts = [{"id": "Gotówką", "name": "Gotówką", "techName": "g"}, {"id": "Przelewem", "name": "Przelewem", "techName": "p"}]
    show = [{"type": "SHOW", "query": '("Przelewem" in tabs[0].sposob)'}]
    grid = [_f(2, "DATEPICKER", "Data uiszczenia opłaty", validation=["REQUIRED"]),
            _f(3, "RADIO", "Sposób zwrotu", options=opts),
            _f(4, "TEXT_FIELD", "Numer rachunku", states=show),
            _f(5, "TEXT_FIELD", "Nazwa banku"),
            _f(6, "FILE_UPLOADER", "Dowód uiszczenia opłaty"),
            _f(7, "SELECT", "Kraj", dict="Kraje")]
    return {"title": "T", "tabs": [
        {"id": UUID.format(90), "title": "Dane", "type": "MAIN", "questions": [_f(1, "SECTION", "Wnioskodawca", grid=[_f(8, "TEXT_FIELD", "Imię")])]},
        {"id": UUID.format(91), "title": "Informacje", "type": "MAIN", "questions": [_f(9, "SECTION", "Opłata", grid=grid)]},
        {"id": UUID.format(92), "title": "Strona końcowa", "type": "FINISH", "questions": []}], "flow": {"links": []}}


GT = {"pola": [{"nazwa": "Data", "klucze": ["data", "uiszcz"], "wymagane": True},
               {"nazwa": "Rachunek", "klucze": ["rachunk"], "wymagane": True},
               {"nazwa": "Uzasadnienie", "klucze": ["uzasadn"]}],
      "warianty": [{"nazwa": "Sposób", "opcje": [["gotowk"], ["przelew"]]}],
      "warunkowe": [{"pole": ["rachunk"], "gdy": ["przelew"]}],
      "zalaczniki": [["dowod", "uiszcz"]], "poza_zakresem": [["kraj"]], "nie_powinno_byc": [["nazw", "bank"]]}


def test_key_match():
    assert ev.key_match("uiszcz", "data uiszczenia oplaty")
    assert not ev.key_match("od", "termin")  # początek słowa, nie podciąg
    assert ev.key_match("termin od", "termin wynajmu od")  # fraza z jednym słowem przerwy
    assert not ev.key_match("powyzej 50", "powyzej 20 do 50")
    assert ev.key_match("gotowk|kasa", "kasa urzedu")


def test_metrics_on_small_form():
    r = ev.evaluate(_form(), GT, tech=False)
    assert r["recall"] == round(100 * 2 / 3, 1)  # brak uzasadnienia
    assert r["szczegoly"]["brakujace_pola"] == ["Uzasadnienie"]
    assert r["wymagane"] == 50.0  # rachunek bez REQUIRED
    assert r["warianty"] == 100.0 and r["warunki"] == 100.0 and r["zalaczniki"] == 100.0
    assert r["nie_powinno_byc"] == 1  # „Nazwa banku”
    # wynik: data, radio, rachunek, upload = trafione; nazwa banku = nadmiar; kraj = poza zakresem (neutralne)
    assert r["precision"] == 80.0 and r["szczegoly"]["neutralne_poza_zakresem"] == 1
    assert r["slowniki_pol"] == 1 and r["slowniki_pokrycie"] == 100.0


def test_technical_check_runs():
    r = ev.evaluate(_form(), GT)
    assert "technicznie_ok" in r and isinstance(r["bledy_schematu"], int)


def test_report_generated(tmp_path, monkeypatch):
    gt_dir, res_dir = tmp_path / "gt", tmp_path / "wyniki"
    gt_dir.mkdir(), res_dir.mkdir()
    (gt_dir / "2.yaml").write_text(json.dumps({"formularz": "Test", **GT}), "utf-8")  # JSON to poprawny YAML
    (res_dir / "2.json").write_text(json.dumps(_form()), "utf-8")
    monkeypatch.setattr(ev, "GT_DIR", gt_dir)
    monkeypatch.setattr(ev, "result_path", lambda nr: res_dir / f"{nr}.json" if nr == "2" else None)
    monkeypatch.setattr(ev, "ensure_coi_gt", lambda: None)
    rep = ev.main(["2", "--out", str(tmp_path / "out")])
    assert rep["formularze"]["2"]["recall"] is not None
    html = (tmp_path / "out" / "raport.html").read_text("utf-8")
    assert "<table" in html and "Średnia" in html and "http" not in html.split("<body>")[1]
    assert "| 2 |" in (tmp_path / "out" / "raport.md").read_text("utf-8")
    assert json.loads((tmp_path / "out" / "raport.json").read_text("utf-8"))["srednia"]


def test_gt_from_coi_template():
    import glob
    src = glob.glob(str(ev.ROOT / "data" / "5" / "*" / "konfiguracja*.json"))
    if not src:
        return
    gt = ev.gt_from_coi(ev.Path(src[0]))
    assert gt["pola"] and gt["warianty"] and gt["warunkowe"] and gt["zalaczniki"]
