import io
import uuid
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import app as maintidoc


@pytest.fixture()
def client(tmp_path):
    database = tmp_path / "test.sqlite3"
    maintidoc.app.config.update(TESTING=True, DATABASE=str(database))
    maintidoc.init_db()
    return maintidoc.app.test_client()


def test_conversation_persists_exports_and_clears(client):
    cid = str(uuid.uuid4())
    maintidoc.ensure_conversation(cid, "education")
    maintidoc.store_message(cid, "user", "Explique les fractions")
    maintidoc.store_message(cid, "assistant", "Une fraction représente une partie d’un tout.")

    history = client.get(f"/api/conversations/{cid}")
    assert history.status_code == 200
    assert history.json["specialty"] == "education"
    assert [m["role"] for m in history.json["messages"]] == ["user", "assistant"]

    exported = client.get(f"/api/conversations/{cid}/export")
    assert exported.status_code == 200
    assert b"Explique les fractions" in exported.data

    assert client.delete(f"/api/conversations/{cid}").json["ok"] is True
    assert client.get(f"/api/conversations/{cid}").json["messages"] == []


def test_prompt_validates_specialty_and_message_shape(client):
    cid = str(uuid.uuid4())
    response = client.post("/prompt", json={
        "conversation_id": cid,
        "specialty": "unknown",
        "messages": [{"role": "user", "content": "Bonjour"}],
    })
    assert response.status_code == 400
    assert "Spécialité" in response.json["error"]


def test_text_extraction_and_extension_validation():
    upload = maintidoc.app.test_client()
    _ = upload  # Keep this test independent of an external model.
    source = type("Upload", (), {"filename": "notes.txt", "read": lambda self, n: "Procédure de sécurité".encode("utf-8")})()
    assert maintidoc.extract_file_text(source) == "Procédure de sécurité"
    bad = type("Upload", (), {"filename": "payload.exe", "read": lambda self, n: b"data"})()
    with pytest.raises(ValueError, match="Formats acceptés"):
        maintidoc.extract_file_text(bad)


def test_summarize_rejects_unsupported_format(client):
    response = client.post("/api/summarize", data={
        "file": (io.BytesIO(b"binary"), "payload.exe"),
        "specialty": "maintenance",
        "conversation_id": str(uuid.uuid4()),
    })
    assert response.status_code == 400
