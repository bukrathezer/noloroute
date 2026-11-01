"""Pages the web app opens by their own address (besides shared plans: test_share_integration)."""

from pathlib import Path

from fastapi.testclient import TestClient

from tests.test_share_integration import INDEX_HTML, frontend_index


def test_the_privacy_note_has_an_address_in_both_languages(client: TestClient, tmp_path: Path) -> None:
    index = tmp_path / "index.html"
    index.write_bytes(INDEX_HTML.encode())  # as built: served byte for byte
    with frontend_index(index):
        for path in ("/gizlilik", "/privacy"):
            resp = client.get(path)
            assert resp.status_code == 200 and resp.text == INDEX_HTML  # the app opens on the note
            assert resp.headers["cache-control"] == "no-cache"


def test_without_a_built_frontend_the_privacy_address_is_not_found(client: TestClient, tmp_path: Path) -> None:
    with frontend_index(tmp_path / "missing.html"):
        assert client.get("/gizlilik").status_code == 404
