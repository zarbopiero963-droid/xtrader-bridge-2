# BetRelay Site

Sito vetrina + supporto di **BetRelay** (già XTrader Signal Bridge): homepage, demo interattiva,
FAQ, contatti e chatbot di supporto (solo sul bridge, sola lettura).

> Capitolato completo: issue «[SITO WEB] betrelay-site» (#229 del repo bridge,
> da trasferire qui).

## Lingue e famiglia Betting Toolkit

- Sito **trilingue IT / EN / ES** con **auto-riconoscimento** dalla lingua del browser
  (`navigator.language`: it→IT, es→ES, altro→EN) e **selettore manuale** IT|EN|ES nella
  nav (scelta ricordata in `localStorage`). Implementazione: `static/i18n.js`
  (dizionari + attributi `data-i18n`); l'italiano è il testo di default nel markup.
- Il sito presenta il bridge come compatibile con **tutta la famiglia**: XTrader
  (Italia) + BETTINGTOOLKIT.COM (World) + BETTINGTOOLKIT.ES (Spagna) +
  BETTINGTOOLKIT.LAT (America Latina) — sezione dedicata in homepage e knowledge
  base del chatbot aggiornata.
- Il **chatbot** riceve la lingua dell'interfaccia (`lang` in `/api/chat`) e risponde
  in quella lingua sia in modalità demo (risposte predefinite IT/EN/ES) sia in
  modalità live (istruzione nel system prompt; se l'utente scrive in un'altra lingua,
  segue quella).
- La **demo interattiva** (`/demo`) per ora è in italiano, con nota trilingue; la
  traduzione della demo è un lavoro successivo.

## Test in locale (Windows)

Requisiti: Python 3.11+ ([python.org](https://www.python.org/downloads/), spunta
"Add python.exe to PATH").

```bat
cd xtrader-bridge-site
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
```

Apri **http://127.0.0.1:8000** — pagine: `/` (home), `/demo`, `/faq`, `/contatti`.

### Chatbot: due modalità

- **Senza API key (default):** modalità **demo** — risposte predefinite basate sulle
  FAQ, a costo zero. Perfetta per testare il sito in locale.
- **Con API key Anthropic:** risposte vere dal modello, vincolate alla knowledge
  base del bridge (`knowledge/bridge_kb.md`). Per provarla in locale:

```bat
set ANTHROPIC_API_KEY=sk-ant-...   &REM la tua chiave, MAI committarla
uvicorn main:app --reload
```

Verifica quale modalità è attiva: http://127.0.0.1:8000/api/health
(`"chatbot": "demo"` oppure `"live"`).

### Guardrail del chatbot (server-side)

- Risponde SOLO su XTrader Signal Bridge; fuori tema → rifiuto cortese + rimando a Contatti.
- Nessuna azione: solo Q&A su knowledge base fissa. Nessun tool, nessun web.
- Rate limit: 20 messaggi/ora per IP (variabile `CHAT_RATE_LIMIT`).
- Input limitato a 1000 caratteri; storia limitata a 6 turni.
- La API key vive SOLO in variabile d'ambiente (in produzione: Railway → Variables).

## Deploy su Railway

1. Crea il progetto Railway e collega questo repository (il Dockerfile viene rilevato
   da solo).
2. In **Variables** imposta `ANTHROPIC_API_KEY` (e, se vuoi, `ANTHROPIC_MODEL`,
   `CHAT_RATE_LIMIT`).
3. Genera il dominio pubblico (Settings → Networking → Generate Domain).

Senza `ANTHROPIC_API_KEY` il sito funziona comunque, col chatbot in modalità demo.

## Struttura

```
main.py                  FastAPI: pagine statiche + POST /api/chat + /api/health
knowledge/bridge_kb.md   knowledge base del chatbot (dalle docs reali del bridge)
static/                  index.html · demo.html · faq.html · contatti.html · style.css · chat.js
Dockerfile               build per Railway / locale
```

## Da fare prima di andare pubblici

- [ ] Sostituire `supporto@example.com` in `static/contatti.html` con l'indirizzo reale
      (o implementare `/api/contact` con invio email dal backend).
- [ ] Aggiornare la demo quando ci sono screenshot freschi dell'app.
- [ ] (Opzionale) Dominio personalizzato su Railway.
