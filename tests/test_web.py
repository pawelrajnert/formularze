from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>" in r.text


def test_jsonata_vendored():
    r = client.get("/web/vendor/jsonata.min.js")
    assert r.status_code == 200
    assert "jsonata" in r.text
