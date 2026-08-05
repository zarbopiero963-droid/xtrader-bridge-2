FROM python:3.11-slim

# ⚠️ Il build context DEVE essere `website/` (su Railway: Settings → Root Directory =
# `website`). Le COPY qui sotto sono relative a questa cartella: buildando dalla radice del
# repository `requirements.txt` non verrebbe trovato. Vedi README.md → «Deploy su Railway».

WORKDIR /app

# Le dipendenze prima del codice: il layer di pip resta in cache quando cambia solo il sito.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Cosa NON entra qui dentro lo decide `.dockerignore` (segreti, cache, ambienti locali).
COPY . .

# L'app non scrive nulla su disco: gira senza privilegi. Un servizio esposto su internet non
# ha motivo di essere root nel proprio container.
RUN useradd --create-home --uid 10001 betrelay && chown -R betrelay:betrelay /app
USER betrelay

# Railway inietta PORT; 8000 è il default per l'uso locale. Il `:-8000` copre anche il caso in
# cui la variabile esista ma sia VUOTA: senza, uvicorn riceverebbe `--port ` e non partirebbe.
ENV PORT=8000
# `exec`: senza, PID 1 resta `sh`, che NON inoltra SIGTERM a uvicorn — il deploy verrebbe
# ucciso a fine grace period invece di chiudersi pulito.
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
