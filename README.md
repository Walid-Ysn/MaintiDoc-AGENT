# MaintiDoc-AGENT

Assistant conversationnel Flask orienté maintenance, avec spécialités configurables, persistance SQLite, export Markdown et résumé de documents.

## Prérequis et installation

Python 3.11 ou plus récent est requis. Node.js est uniquement nécessaire pour reconstruire le CSS Tailwind.

```bash
poetry install --with dev
cp .env.example .env
# Renseignez GROQ_API_KEY dans .env
poetry run python app.py
```

Ouvrez ensuite http://127.0.0.1:5000. SQLite est initialisé automatiquement dans `instance/maintidoc.sqlite3`. Les fichiers PDF, TXT, Markdown et DOCX jusqu’à 10 Mo peuvent être soumis au résumé; ils sont extraits en mémoire et ne sont pas conservés.

## Configuration

`GROQ_API_KEY` est requis. `LLM_MODEL`, `LLM_BASE_URL` et `MAINTIDOC_DATABASE` sont facultatifs. La clé `OPENAI_API_KEY` peut également être utilisée, mais avec l’URL Groq par défaut il faut toujours une clé Groq; pour OpenAI, configurez aussi `LLM_BASE_URL` avec l’URL appropriée.

## Fonctions

- Le menu de spécialité couvre maintenance, éducation, santé et programmation. Le contexte est imposé côté serveur.
- Les conversations sont stockées dans SQLite. Le bouton Effacer supprime la conversation enregistrée et en démarre une nouvelle.
- L’export télécharge un fichier Markdown.
- L’ajout de fichiers extrait le texte des formats autorisés puis demande un résumé au modèle; seul le résumé et la trace de la demande sont enregistrés.
- Les erreurs d’API et de fichier sont signalées dans l’interface. L’application démarre sans clé API, mais les appels au modèle renvoient alors une erreur explicite.

## Tailwind

```bash
npm install
npm run tailwind:build
# pendant le développement : npm run tailwind:watch
```
