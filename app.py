from __future__ import annotations

import io
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request, send_file
from openai import OpenAI
from pypdf import PdfReader
from werkzeug.exceptions import RequestEntityTooLarge

load_dotenv()
SPECIALTIES = {
    "maintenance": "Tu es un assistant spécialisé en maintenance industrielle. Donne des réponses prudentes, structurées et pratiques. Signale les risques et n'invente pas de références.",
    "education": "Tu es un assistant pédagogique. Explique clairement, étape par étape, avec des exemples adaptés.",
    "medical": "Tu fournis des informations générales de santé uniquement, sans diagnostic ni prescription. Encourage à consulter un professionnel; en cas d'urgence, contacter les services d'urgence.",
    "programming": "Tu es un assistant de programmation. Fournis des solutions exactes, explique les choix et signale les hypothèses.",
}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
app.config["DATABASE"] = os.getenv("MAINTIDOC_DATABASE", str(Path(app.instance_path) / "maintidoc.sqlite3"))
Path(app.instance_path).mkdir(parents=True, exist_ok=True)


def db_connection():
    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    return db


def init_db():
    with db_connection() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS conversations(id TEXT PRIMARY KEY, specialty TEXT NOT NULL DEFAULT 'maintenance', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE, role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id,id);
        """)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def valid_id(value):
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return None


def ensure_conversation(cid, specialty):
    if specialty not in SPECIALTIES:
        raise ValueError("Spécialité inconnue.")
    stamp = now_iso()
    with db_connection() as db:
        db.execute("INSERT OR IGNORE INTO conversations VALUES(?,?,?,?)", (cid, specialty, stamp, stamp))
        db.execute("UPDATE conversations SET specialty=?,updated_at=? WHERE id=?", (specialty, stamp, cid))


def get_messages(cid):
    with db_connection() as db:
        rows = db.execute("SELECT role,content FROM messages WHERE conversation_id=? ORDER BY id", (cid,)).fetchall()
    return [dict(row) for row in rows]


def store_message(cid, role, content):
    with db_connection() as db:
        db.execute("INSERT INTO messages(conversation_id,role,content,created_at) VALUES(?,?,?,?)", (cid, role, content, now_iso()))
        db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now_iso(), cid))


def make_client():
    key = os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("Clé API absente. Configurez GROQ_API_KEY dans .env.")
    return OpenAI(api_key=key, base_url=os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1"))


def model_name():
    return os.getenv("LLM_MODEL", "openai/gpt-oss-20b")


@app.get("/")
def home():
    return render_template("index.html", specialties=SPECIALTIES)


@app.get("/api/conversations/<cid>")
def load_conversation(cid):
    cid = valid_id(cid)
    if not cid:
        return jsonify(error="Identifiant de conversation invalide."), 400
    with db_connection() as db:
        row = db.execute("SELECT specialty FROM conversations WHERE id=?", (cid,)).fetchone()
    return jsonify(messages=get_messages(cid), specialty=row["specialty"] if row else "maintenance")


@app.delete("/api/conversations/<cid>")
def clear_conversation(cid):
    cid = valid_id(cid)
    if not cid:
        return jsonify(error="Identifiant de conversation invalide."), 400
    with db_connection() as db:
        db.execute("DELETE FROM conversations WHERE id=?", (cid,))
    return jsonify(ok=True)


@app.get("/api/conversations/<cid>/export")
def export_conversation(cid):
    cid = valid_id(cid)
    if not cid:
        return jsonify(error="Identifiant de conversation invalide."), 400
    with db_connection() as db:
        convo = db.execute("SELECT specialty,created_at FROM conversations WHERE id=?", (cid,)).fetchone()
    messages = get_messages(cid)
    if not convo or not messages:
        return jsonify(error="Conversation vide ou introuvable."), 404
    lines = [f"Conversation MaintiDoc — spécialité : {convo['specialty']}", f"Créée le : {convo['created_at']}", ""]
    for m in messages:
        lines += ["Vous :" if m["role"] == "user" else "MaintiDoc :", m["content"], ""]
    return send_file(io.BytesIO("\n".join(lines).encode()), mimetype="text/markdown; charset=utf-8", as_attachment=True, download_name="conversation-maintidoc.md")


@app.post("/prompt")
def prompt():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify(error="Le corps doit être un objet JSON valide."), 400
    cid, messages, specialty = valid_id(data.get("conversation_id")), data.get("messages"), data.get("specialty", "maintenance")
    if not cid:
        return jsonify(error="Identifiant de conversation invalide."), 400
    if specialty not in SPECIALTIES:
        return jsonify(error="Spécialité inconnue."), 400
    if not isinstance(messages, list) or not messages or len(messages) > 100:
        return jsonify(error="La conversation doit contenir de 1 à 100 messages."), 400
    if any(not isinstance(m, dict) or m.get("role") not in ("user", "assistant") or not isinstance(m.get("content"), str) or not m["content"].strip() for m in messages):
        return jsonify(error="Chaque message doit avoir un rôle et un texte non vide."), 400
    if messages[-1]["role"] != "user":
        return jsonify(error="Le dernier message doit être une question utilisateur."), 400
    try:
        ensure_conversation(cid, specialty)
        store_message(cid, "user", messages[-1]["content"])
    except ValueError as exc:
        return jsonify(error=str(exc)), 400

    def stream():
        parts = []
        try:
            client = make_client()
            response = client.chat.completions.create(model=model_name(), messages=[{"role": "system", "content": SPECIALTIES[specialty]}, *messages], stream=True)
            for chunk in response:
                if chunk.choices:
                    text = chunk.choices[0].delta.content or ""
                    if text:
                        parts.append(text)
                        yield text
            if parts:
                store_message(cid, "assistant", "".join(parts).strip())
        except Exception:
            app.logger.exception("Échec du flux de réponse")
            yield "\n\n[ERREUR] Réponse impossible. Vérifiez la configuration API ou réessayez."
    return Response(stream(), content_type="text/plain; charset=utf-8", headers={"X-Content-Type-Options": "nosniff"})


def extract_file_text(file):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Formats acceptés : TXT, MD, PDF et DOCX.")
    raw = file.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise ValueError("Le fichier est vide.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise ValueError("Le fichier dépasse la limite de 10 Mo.")
    if ext in {".txt", ".md"}:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ValueError("Le fichier texte doit être encodé en UTF-8.") from exc
    elif ext == ".pdf":
        try:
            text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(raw)).pages)
        except Exception as exc:
            raise ValueError("PDF illisible, chiffré ou endommagé.") from exc
    else:
        try:
            from docx import Document
            text = "\n".join(p.text for p in Document(io.BytesIO(raw)).paragraphs)
        except ImportError as exc:
            raise RuntimeError("Le support DOCX nécessite python-docx.") from exc
        except Exception as exc:
            raise ValueError("Document DOCX illisible.") from exc
    text = text.strip()
    if not text:
        raise ValueError("Aucun texte exploitable n’a été trouvé.")
    return text[:100_000]


@app.post("/api/summarize")
def summarize_file():
    file = request.files.get("file")
    if file is None:
        return jsonify(error="Sélectionnez un fichier."), 400
    try:
        text = extract_file_text(file)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except RuntimeError as exc:
        return jsonify(error=str(exc)), 500
    specialty, cid = request.form.get("specialty", "maintenance"), valid_id(request.form.get("conversation_id"))
    if specialty not in SPECIALTIES or not cid:
        return jsonify(error="Spécialité ou identifiant invalide."), 400
    try:
        response = make_client().chat.completions.create(model=model_name(), messages=[
            {"role": "system", "content": SPECIALTIES[specialty]},
            {"role": "user", "content": "Résume ce document en français avec les points essentiels, actions et avertissements. N’ajoute aucune information absente du document.\n\n" + text}], stream=False)
        summary = response.choices[0].message.content or "Aucun résumé retourné."
        ensure_conversation(cid, specialty)
        store_message(cid, "user", f"Résumé du fichier « {Path(file.filename or 'document').name} » demandé.")
        store_message(cid, "assistant", summary)
        return jsonify(summary=summary)
    except Exception:
        app.logger.exception("Échec du résumé")
        return jsonify(error="Résumé impossible. Vérifiez la configuration API puis réessayez."), 502


@app.errorhandler(RequestEntityTooLarge)
def too_large(_error):
    return jsonify(error="Le fichier dépasse la limite de 10 Mo."), 413


@app.errorhandler(500)
def internal_error(error):
    app.logger.error("Erreur serveur : %s", error)
    return jsonify(error="Erreur interne. Réessayez plus tard."), 500


init_db()

if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
