"""BetRelay Site — sito vetrina + chatbot di supporto (solo bridge).

Avvio locale:  uvicorn main:app --reload
Il chatbot usa l'API Anthropic SOLO se ANTHROPIC_API_KEY è impostata;
senza chiave risponde in "modalità demo" con risposte predefinite,
così il sito è testabile in locale a costo zero.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
KB_PATH = BASE_DIR / "knowledge" / "bridge_kb.md"

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# Rate limit: max N messaggi per IP per ora (in-memory: sufficiente per un
# singolo processo; su Railway gira un processo solo).
RATE_LIMIT_PER_HOUR = int(os.environ.get("CHAT_RATE_LIMIT", "20"))
_hits: dict[str, list[float]] = defaultdict(list)

MAX_MESSAGE_CHARS = 1000
MAX_HISTORY_TURNS = 6

SYSTEM_PROMPT = """Sei l'assistente di supporto del sito di BetRelay (nuovo nome di XTrader Signal Bridge).

REGOLE NON NEGOZIABILI:
- Rispondi SOLO a domande su BetRelay (il Signal Bridge): installazione, requisiti,
  configurazione (token, chat, CSV, timeout), parser personalizzato, dizionari,
  modalità Simulazione/Collaudo/Reale, conferme del software, sicurezza, FAQ,
  e la compatibilità con la famiglia di software di destinazione: XTrader
  (Italia, TradingSportivo) e Betting Toolkit — BETTINGTOOLKIT.COM (World),
  BETTINGTOOLKIT.ES (Spagna), BETTINGTOOLKIT.LAT (America Latina).
- Se la domanda è fuori tema (altro software, meteo, codice generico, consigli
  di scommesse, pronostici, altro), rifiuta con cortesia in UNA frase e invita a
  usare la pagina Contatti per tutto il resto.
- NON dai consigli di scommessa e NON piazzi scommesse: il bridge scrive solo un
  CSV che il software di betting legge.
- NON chiedere mai token, password o dati personali; se l'utente li incolla,
  invitalo a NON condividerli in chat.
- Rispondi nella LINGUA DELL'UTENTE. La lingua dell'interfaccia scelta
  dall'utente è indicata a inizio conversazione; se l'utente scrive in un'altra
  lingua, segui la lingua dei suoi messaggi. Sii breve e pratico.
- Basa le risposte SOLO sulla documentazione qui sotto; se non sai, dillo e
  rimanda alla pagina Contatti. Non inventare funzionalità.

DOCUMENTAZIONE DEL BRIDGE:
"""

_LANG_NAMES = {"it": "italiano", "en": "English", "es": "español"}


def load_kb() -> str:
    try:
        return KB_PATH.read_text(encoding="utf-8")
    except OSError:
        return "(documentazione non disponibile)"


# Risposte predefinite per la modalità demo (senza API key): matcher a parole
# chiave sulle FAQ reali nelle tre lingue del sito, così il flusso è testabile
# in locale a costo zero.
_DEMO_ANSWERS: dict[str, list[tuple[tuple[str, ...], str]]] = {
    "it": [
        (("token", "botfather"),
         "Il Bot Token si crea con @BotFather su Telegram e si incolla nel campo «🔑 Bot Token» "
         "(tab ⚙️ Generale). Viene salvato nel keyring di Windows, non in chiaro. Senza token il "
         "pulsante AVVIA resta bloccato."),
        (("chat id", "chat_id", "canale"),
         "Il Chat ID è l'ID della chat/canale sorgente dei segnali (es. -1001234567890). Il bridge "
         "ascolta SOLO le chat configurate: ogni altro messaggio viene ignorato. Puoi configurare "
         "più canali da 🧰 Strumenti → 📡 Chat sorgenti."),
        (("betting toolkit", "bettingtoolkit", "toolkit"),
         "Il bridge è nato per XTrader (Italia) e parla lo stesso CSV degli altri prodotti della "
         "stessa casa madre: BETTINGTOOLKIT.COM (World), BETTINGTOOLKIT.ES (Spagna) e "
         "BETTINGTOOLKIT.LAT (America Latina). Scegli nel bridge la lingua sorgente del tuo "
         "software e il separatore decimale del CSV si allinea da solo."),
        (("csv", "segnali.csv", "file"),
         "Il bridge scrive un CSV a 14 colonne nel percorso «📄 CSV Path»: è il file che il tuo "
         "software monitora. Dopo il timeout configurato (default 90s) il CSV torna a solo header, "
         "così non vengono mai ripetute scommesse vecchie."),
        (("reale", "collaudo", "simulazione", "dry_run", "dry run", "modalità"),
         "Tre modalità (tab 🛡️ Sicurezza): 🧪 Simulazione (default, NON scrive il CSV), 🔬 Collaudo "
         "(scrive il CSV col software in simulazione, conferma Sì/No) e ⚠️ Reale (scommesse vere: "
         "richiede di digitare la parola REALE, banner rosso persistente e conferma a ogni avvio)."),
        (("parser",),
         "Il Parser Personalizzato (🧰 Strumenti → 🧩 Parser) insegna al bridge a leggere il TUO "
         "canale: per ogni colonna del CSV definisci come estrarla («Inizia dopo»/«Finisce prima», "
         "valori fissi, value-map). Con «🧪 Prova messaggio» vedi l'anteprima della riga generata. "
         "Senza un parser attivo lo START è bloccato."),
        (("connessione", "riconnessione", "internet", "offline"),
         "Se cade la connessione il bridge si riconnette da solo con attese crescenti (2s→60s) e lo "
         "stato mostra RICONNESSIONE…. I messaggi più vecchi di max_signal_age (default 120s) "
         "vengono ignorati: gli arretrati non diventano scommesse vecchie."),
        (("requisiti", "windows", "vps", "pc"),
         "Serve Windows 10/11 a 64 bit col software di betting installato sulla stessa macchina "
         "(comunicano via file CSV locale), un bot Telegram (token + chat ID) e connessione "
         "internet. L'EXE include già tutto: non serve installare Python."),
        (("non parte", "non si avvia", "avvia", "bloccato"),
         "Se AVVIA è bloccato controlla nel log il motivo esatto: manca il Bot Token, manca il CSV "
         "Path, il Timeout non è valido, nessuna chat configurata o nessun Parser Personalizzato "
         "attivo. La tab 🚦 Salute mostra 7 semafori con lo stato di ogni requisito."),
        (("wizard",),
         "Il 🧙 Wizard prima configurazione ti guida in 5 passi con verifiche dal vivo: token "
         "(getMe), chat, parser su un messaggio reale, CSV di prova e checklist finale. Non attiva "
         "mai la modalità Reale."),
    ],
    "en": [
        (("token", "botfather"),
         "Create the Bot Token with @BotFather on Telegram and paste it into «🔑 Bot Token» "
         "(⚙️ General tab). It's stored in the Windows keyring, not in plain text. Without a "
         "token the START button stays locked."),
        (("chat id", "chat_id", "channel"),
         "The Chat ID is the ID of the source chat/channel (e.g. -1001234567890). The bridge "
         "listens ONLY to configured chats: any other message is ignored. You can add several "
         "channels from 🧰 Tools → 📡 Source chats."),
        (("betting toolkit", "bettingtoolkit", "toolkit", "xtrader"),
         "The bridge was born for XTrader (Italy) and writes the same CSV used by the other "
         "products of the same maker: BETTINGTOOLKIT.COM (World), BETTINGTOOLKIT.ES (Spain) and "
         "BETTINGTOOLKIT.LAT (Latin America). Pick your software's source language in the bridge "
         "and the CSV decimal separator aligns automatically."),
        (("csv", "file"),
         "The bridge writes a 14-column CSV at the «📄 CSV Path»: that's the file your software "
         "monitors. After the configured timeout (default 90s) the CSV returns to header-only, "
         "so old bets are never repeated."),
        (("real", "test", "simulation", "dry_run", "dry run", "mode"),
         "Three modes (🛡️ Security tab): 🧪 Simulation (default, does NOT write the CSV), "
         "🔬 Test (writes the CSV with your software in simulation, Yes/No confirmation) and "
         "⚠️ Real (real bets: requires typing the word REALE, persistent red banner and "
         "confirmation at every start)."),
        (("parser",),
         "The Custom Parser (🧰 Tools → 🧩 Parser) teaches the bridge to read YOUR channel: for "
         "each CSV column you define how to extract it («Starts after»/«Ends before», fixed "
         "values, value-maps). «🧪 Test message» previews the generated row. Without an active "
         "parser, START is locked."),
        (("connection", "reconnect", "internet", "offline"),
         "If the connection drops the bridge reconnects by itself with growing delays (2s→60s) "
         "showing RECONNECTING…. Messages older than max_signal_age (default 120s) are ignored: "
         "backlogs never become old bets."),
        (("requirements", "windows", "vps", "pc", "computer"),
         "You need 64-bit Windows 10/11 with your betting software on the same machine (they "
         "communicate via a local CSV file), a Telegram bot (token + chat ID) and an internet "
         "connection. The EXE includes everything: no Python needed."),
        (("won't start", "not start", "start", "locked", "blocked"),
         "If START is locked, the exact reason is in the log: missing Bot Token, missing CSV "
         "Path, invalid Timeout, no chat configured or no active Custom Parser. The 🚦 Health "
         "tab shows 7 lights with each requirement's status."),
        (("wizard",),
         "The 🧙 First-configuration Wizard guides you through 5 steps with live checks: token "
         "(getMe), chat, parser on a real message, test CSV and final checklist. It never "
         "enables Real mode."),
    ],
    "es": [
        (("token", "botfather"),
         "El Bot Token se crea con @BotFather en Telegram y se pega en «🔑 Bot Token» (pestaña "
         "⚙️ General). Se guarda en el keyring de Windows, no en texto plano. Sin token el botón "
         "START queda bloqueado."),
        (("chat id", "chat_id", "canal"),
         "El Chat ID es el ID del chat/canal fuente (ej. -1001234567890). El bridge escucha SOLO "
         "los chats configurados: cualquier otro mensaje se ignora. Puedes añadir varios canales "
         "desde 🧰 Herramientas → 📡 Chats fuente."),
        (("betting toolkit", "bettingtoolkit", "toolkit", "xtrader"),
         "El bridge nació para XTrader (Italia) y escribe el mismo CSV que los demás productos "
         "del mismo fabricante: BETTINGTOOLKIT.COM (Mundo), BETTINGTOOLKIT.ES (España) y "
         "BETTINGTOOLKIT.LAT (Latinoamérica). Elige en el bridge el idioma fuente de tu software "
         "y el separador decimal del CSV se alinea solo."),
        (("csv", "archivo", "fichero"),
         "El bridge escribe un CSV de 14 columnas en la «📄 Ruta CSV»: es el archivo que tu "
         "software monitorea. Tras el timeout configurado (90s por defecto) el CSV vuelve a solo "
         "encabezado: nunca se repiten apuestas viejas."),
        (("real", "prueba", "simulación", "simulacion", "dry_run", "dry run", "modo"),
         "Tres modos (pestaña 🛡️ Seguridad): 🧪 Simulación (por defecto, NO escribe el CSV), "
         "🔬 Prueba (escribe el CSV con el software en simulación, confirmación Sí/No) y ⚠️ Real "
         "(apuestas reales: exige escribir la palabra REALE, banner rojo persistente y "
         "confirmación en cada arranque)."),
        (("parser",),
         "El Parser Personalizado (🧰 Herramientas → 🧩 Parser) enseña al bridge a leer TU canal: "
         "para cada columna del CSV defines cómo extraerla («Empieza después»/«Termina antes», "
         "valores fijos, value-maps). «🧪 Probar mensaje» muestra la vista previa de la fila. Sin "
         "parser activo, START queda bloqueado."),
        (("conexión", "conexion", "reconexión", "reconexion", "internet", "offline"),
         "Si se cae la conexión el bridge se reconecta solo con esperas crecientes (2s→60s) "
         "mostrando RECONEXIÓN…. Los mensajes más viejos que max_signal_age (120s por defecto) "
         "se ignoran: los atrasados nunca se convierten en apuestas viejas."),
        (("requisitos", "windows", "vps", "pc", "ordenador"),
         "Necesitas Windows 10/11 de 64 bits con tu software de apuestas en la misma máquina "
         "(se comunican por un archivo CSV local), un bot de Telegram (token + chat ID) y "
         "conexión a internet. El EXE lo incluye todo: no hace falta Python."),
        (("no arranca", "no inicia", "arranca", "bloqueado"),
         "Si START está bloqueado, el motivo exacto está en el log: falta el Bot Token, falta la "
         "ruta CSV, Timeout inválido, ningún chat configurado o ningún Parser Personalizado "
         "activo. La pestaña 🚦 Salud muestra 7 semáforos con cada requisito."),
        (("wizard", "asistente"),
         "El 🧙 Asistente de primera configuración te guía en 5 pasos con verificaciones en vivo: "
         "token (getMe), chat, parser sobre un mensaje real, CSV de prueba y checklist final. "
         "Nunca activa el modo Real."),
    ],
}

_DEMO_FALLBACK = {
    "it": "Posso aiutarti su BetRelay (e la famiglia Betting Toolkit): "
          "configurazione, token, chat, parser, CSV, modalità di sicurezza. Prova a chiedermi "
          "«come creo il bot Telegram?» o «perché il bridge non parte?». Per il resto usa la "
          "pagina Contatti.",
    "en": "I can help with BetRelay (and the Betting Toolkit family): setup, token, "
          "chats, parser, CSV, safety modes. Try asking «how do I create the Telegram bot?» or "
          "«why won't the bridge start?». For anything else use the Contact page.",
    "es": "Puedo ayudarte con BetRelay (y la familia Betting Toolkit): "
          "configuración, token, chats, parser, CSV, modos de seguridad. Prueba con «¿cómo creo "
          "el bot de Telegram?» o «¿por qué no arranca el bridge?». Para lo demás usa la página "
          "de Contacto.",
}

_OFF_TOPIC_REPLY = {
    "it": "Posso rispondere solo a domande su BetRelay e la famiglia Betting "
          "Toolkit. Per tutto il resto usa la pagina Contatti. 🙂",
    "en": "I can only answer questions about BetRelay and the Betting Toolkit "
          "family. For anything else, please use the Contact page. 🙂",
    "es": "Solo puedo responder preguntas sobre BetRelay y la familia Betting "
          "Toolkit. Para lo demás, usa la página de Contacto. 🙂",
}

_OFF_TOPIC_WORDS = ("meteo", "weather", "clima", "ricetta", "recipe", "receta", "bitcoin",
                    "pronostic", "prediction", "tip ", "tips", "schedina", "picks")


def demo_reply(message: str, lang: str) -> str:
    lang = lang if lang in _DEMO_ANSWERS else "it"
    low = message.lower()
    if any(w in low for w in _OFF_TOPIC_WORDS):
        return _OFF_TOPIC_REPLY[lang]
    for keys, answer in _DEMO_ANSWERS[lang]:
        if any(k in low for k in keys):
            return answer
    return _DEMO_FALLBACK[lang]


class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    message: str
    lang: str = "it"
    history: list[ChatTurn] = []


app = FastAPI(title="BetRelay Site", docs_url=None, redoc_url=None)


def _rate_limited(ip: str) -> bool:
    now = time.time()
    hits = _hits[ip]
    hits[:] = [t for t in hits if now - t < 3600]
    if len(hits) >= RATE_LIMIT_PER_HOUR:
        return True
    hits.append(now)
    return False


@app.post("/api/chat")
async def chat(req: ChatRequest, request: Request) -> JSONResponse:
    ip = request.client.host if request.client else "?"
    if _rate_limited(ip):
        limited = {"it": "Hai raggiunto il limite di messaggi per questa ora. "
                         "Riprova più tardi o scrivici dalla pagina Contatti.",
                   "en": "You've reached this hour's message limit. "
                         "Try again later or write to us from the Contact page.",
                   "es": "Has alcanzado el límite de mensajes de esta hora. "
                         "Inténtalo más tarde o escríbenos desde la página de Contacto."}
        lang_rl = req.lang if req.lang in limited else "it"
        return JSONResponse(
            {"reply": limited[lang_rl], "demo": not ANTHROPIC_API_KEY},
            status_code=429,
        )

    message = req.message.strip()[:MAX_MESSAGE_CHARS]
    lang = req.lang if req.lang in ("it", "en", "es") else "it"
    if not message:
        empty = {"it": "Scrivi una domanda sul bridge. 🙂",
                 "en": "Type a question about the bridge. 🙂",
                 "es": "Escribe una pregunta sobre el bridge. 🙂"}
        return JSONResponse({"reply": empty[lang], "demo": not ANTHROPIC_API_KEY})

    if not ANTHROPIC_API_KEY:
        return JSONResponse({"reply": demo_reply(message, lang), "demo": True})

    history = req.history[-MAX_HISTORY_TURNS:]
    messages = [{"role": t.role, "content": t.content[:MAX_MESSAGE_CHARS]} for t in history]
    messages.append({"role": "user", "content": message})

    lang_note = ("\n\nLINGUA INTERFACCIA SCELTA DALL'UTENTE: "
                 + _LANG_NAMES.get(lang, "italiano")
                 + " — rispondi in questa lingua salvo che l'utente scriva in un'altra.")
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 600,
        "system": SYSTEM_PROMPT + load_kb() + lang_note,
        "messages": messages,
    }
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(ANTHROPIC_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        reply = "".join(b.get("text", "") for b in data.get("content", [])
                        if b.get("type") == "text").strip()
        if not reply:
            reply = "Non sono riuscito a formulare una risposta: riprova o usa la pagina Contatti."
        return JSONResponse({"reply": reply, "demo": False})
    except httpx.HTTPError:
        return JSONResponse(
            {"reply": "Il servizio di supporto è momentaneamente non disponibile: "
                      "riprova tra poco o usa la pagina Contatti.", "demo": False},
            status_code=502,
        )


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "chatbot": "live" if ANTHROPIC_API_KEY else "demo"}


# Pagine (route esplicite, così /faq funziona senza estensione)
_PAGES = {"/": "index.html", "/demo": "demo.html", "/faq": "faq.html",
          "/contatti": "contatti.html", "/guida/bot-telegram": "guida-bot.html"}
for route, fname in _PAGES.items():
    def _make(fn: str):
        async def _page() -> FileResponse:
            return FileResponse(STATIC_DIR / fn)
        return _page
    app.get(route, include_in_schema=False)(_make(fname))

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
