"""#343 slice 4a: catalogo i18n minimale della GUI, stile gettext.

L'ITALIANO è la lingua di RIFERIMENTO: le chiavi del catalogo SONO le stringhe
italiane verbatim usate nella GUI, così non si inventano key sintetiche e il
sorgente resta leggibile. `tr(testo)` ritorna la traduzione nella lingua attiva
oppure il testo stesso — fail-safe: mai stringa vuota, mai KeyError, una
traduzione mancante mostra l'italiano (il bridge resta usabile, mai rotto).

La lingua attiva viene impostata all'avvio da `app_language` (#343 slice 3,
selettore al primo avvio) PRIMA di costruire la UI; un cambio lingua a runtime
ha effetto al riavvio (le etichette sono lette in `_build_ui`).

Scope di QUESTO slice: etichette STATICHE della finestra principale (tab,
bottoni, nomi campo). Restano in italiano per ora — slice successivi:
- gli stati dinamici «⬤ ATTIVO/OFFLINE/RICONNESSIONE…»: il pannello 🚦 Salute
  fa il parsing del TESTO di `_status_lbl` (`_refresh_health_inner`), quindi la
  loro localizzazione richiede prima di sostituire il text-parsing con uno stato
  canonico tracciato a parte (fail-closed: meglio IT che un semaforo rotto);
- banner/log/finestre secondarie (Strumenti, Parser, Wizard, …).
"""

import threading

LANGUAGES = ("IT", "EN", "ES")
_DEFAULT = "IT"

_lang = _DEFAULT
_lock = threading.Lock()


def set_language(code) -> str:
    """Imposta la lingua attiva della UI. Fail-safe: valore non supportato o
    vuoto (lingua mai scelta) → italiano, il comportamento storico."""
    global _lang
    lang = code.strip().upper() if isinstance(code, str) else ""
    if lang not in LANGUAGES:
        lang = _DEFAULT
    with _lock:
        _lang = lang
    return lang


def get_language() -> str:
    with _lock:
        return _lang


def tr(text: str) -> str:
    """Traduce `text` nella lingua attiva; senza traduzione ritorna `text`
    (l'italiano è il riferimento: per IT il catalogo non serve affatto)."""
    lang = get_language()
    if lang == _DEFAULT:
        return text
    return _CATALOG.get(lang, {}).get(text, text)


# Cataloghi: SOLO le stringhe che cambiano rispetto all'italiano (una stringa
# identica — «🐞 Debug», «📊 Dashboard», «■  STOP» in EN — si omette: il
# fallback la restituisce già). Le chiavi devono esistere VERBATIM in `app.py`
# (test anti-drift: una label cambiata nel sorgente fa fallire la suite finché
# il catalogo non viene aggiornato).
_CATALOG = {
    "EN": {
        # Tab configurazione + monitoraggio
        "⚙️ Generale": "⚙️ General",
        "🎯 Riconoscimento": "🎯 Recognition",
        "🛡️ Sicurezza": "🛡️ Safety",
        "✅ Conferme XTrader": "✅ XTrader confirmations",
        "📡 Chat ascoltate": "📡 Monitored chats",
        "🚦 Salute": "🚦 Health",
        "📡 Stato": "📡 Status",
        # Bottoni principali
        "📁 Sfoglia…": "📁 Browse…",
        "📄 Crea CSV": "📄 Create CSV",
        "▶  AVVIA": "▶  START",
        "🗑️  Svuota CSV ora": "🗑️  Clear CSV now",
        "💾  Salva Config": "💾  Save Config",
        "🧰  Strumenti": "🧰  Tools",
        "🧙 Wizard prima configurazione": "🧙 First-setup wizard",
        "📋 Copia diagnostica": "📋 Copy diagnostics",
        "📂 Apri cartella log": "📂 Open log folder",
        "🧾 Esporta audit reale": "🧾 Export real-mode audit",
        "🔄 Aggiorna": "🔄 Refresh",
        "🧹 Svuota log": "🧹 Clear log",
        # Campi ed etichette («🔑 Bot Token», «💬 Chat ID», «📄 CSV Path»,
        # «🏷️ Provider», «🐞 Debug», «📊 Dashboard», «📋 Log», «■  STOP» sono
        # già inglese/universali: fallback)
        "Contatori dall'avvio": "Counters since start",
        "Mostra:": "Show:",
        "Conserva:": "Keep:",
        # Impostazioni avanzate (tab Riconoscimento/Sicurezza/Conferme — CodeRabbit
        # #357: i contenuti dei tab tradotti non devono restare in italiano)
        "🎯 Modalità riconoscimento": "🎯 Recognition mode",
        "🚦 Modalità bridge": "🚦 Bridge mode",
        "📅 Limite segnali al giorno": "📅 Daily signal limit",
        "🧮 Modalità coda segnali": "🧮 Signal queue mode",
        "▶️ Avvio automatico all'apertura (in modalità REALE chiede conferma)":
            "▶️ Auto-start on launch (REAL mode asks for confirmation)",
        "🕵️ Logga il testo completo dei messaggi (debug; OFF = solo hash + 1ª riga)":
            "🕵️ Log full message text (debug; OFF = hash + 1st line only)",
        "🔢 Max segnali attivi (modalità coda multi-riga)":
            "🔢 Max active signals (multi-row queue mode)",
        "💬 Chat notifiche XTrader": "💬 XTrader notifications chat",
        "⏳ Timeout conferma (sec)": "⏳ Confirmation timeout (sec)",
        "✅ Parole conferma (separate da virgola)":
            "✅ Confirmation words (comma-separated)",
        "❌ Parole rifiuto (separate da virgola)":
            "❌ Rejection words (comma-separated)",
        # Contatori Dashboard (chiavi in dashboard_stats.COUNTERS)
        "📥 Ricevuti": "📥 Received",
        "✅ Scritti": "✅ Written",
        "⚠️ Scartati": "⚠️ Discarded",
        "♻️ Duplicati": "♻️ Duplicates",
        "🚦 Limitati": "🚦 Limited",
        "🧪 Simulati": "🧪 Simulated",
        "❌ Errori": "❌ Errors",
    },
    "ES": {
        "⚙️ Generale": "⚙️ General",
        "🎯 Riconoscimento": "🎯 Reconocimiento",
        "🛡️ Sicurezza": "🛡️ Seguridad",
        "✅ Conferme XTrader": "✅ Confirmaciones XTrader",
        "📡 Chat ascoltate": "📡 Chats escuchados",
        "🚦 Salute": "🚦 Salud",
        "📡 Stato": "📡 Estado",
        "📁 Sfoglia…": "📁 Examinar…",
        "📄 Crea CSV": "📄 Crear CSV",
        "▶  AVVIA": "▶  INICIAR",
        "■  STOP": "■  DETENER",
        "🗑️  Svuota CSV ora": "🗑️  Vaciar CSV ahora",
        "💾  Salva Config": "💾  Guardar config",
        "🧰  Strumenti": "🧰  Herramientas",
        "🧙 Wizard prima configurazione": "🧙 Asistente de primera configuración",
        "📋 Copia diagnostica": "📋 Copiar diagnóstico",
        "📂 Apri cartella log": "📂 Abrir carpeta de logs",
        "🧾 Esporta audit reale": "🧾 Exportar auditoría real",
        "🔄 Aggiorna": "🔄 Actualizar",
        "🧹 Svuota log": "🧹 Vaciar log",
        "📄 CSV Path": "📄 Ruta CSV",
        "⏱️ Timeout (sec)": "⏱️ Timeout (seg)",
        "🏷️ Provider": "🏷️ Proveedor",
        "Contatori dall'avvio": "Contadores desde el inicio",
        "Mostra:": "Mostrar:",
        "Conserva:": "Conservar:",
        # Impostazioni avanzate (CodeRabbit #357)
        "🎯 Modalità riconoscimento": "🎯 Modo de reconocimiento",
        "🚦 Modalità bridge": "🚦 Modo del bridge",
        "📅 Limite segnali al giorno": "📅 Límite de señales al día",
        "🧮 Modalità coda segnali": "🧮 Modo de cola de señales",
        "▶️ Avvio automatico all'apertura (in modalità REALE chiede conferma)":
            "▶️ Inicio automático al abrir (en modo REAL pide confirmación)",
        "🕵️ Logga il testo completo dei messaggi (debug; OFF = solo hash + 1ª riga)":
            "🕵️ Registrar el texto completo de los mensajes (debug; OFF = solo hash + 1ª línea)",
        "🔢 Max segnali attivi (modalità coda multi-riga)":
            "🔢 Máx. señales activas (modo cola multi-fila)",
        "💬 Chat notifiche XTrader": "💬 Chat de notificaciones XTrader",
        "⏳ Timeout conferma (sec)": "⏳ Timeout de confirmación (seg)",
        "✅ Parole conferma (separate da virgola)":
            "✅ Palabras de confirmación (separadas por comas)",
        "❌ Parole rifiuto (separate da virgola)":
            "❌ Palabras de rechazo (separadas por comas)",
        # Contatori Dashboard (chiavi in dashboard_stats.COUNTERS)
        "📥 Ricevuti": "📥 Recibidos",
        "✅ Scritti": "✅ Escritos",
        "⚠️ Scartati": "⚠️ Descartados",
        "♻️ Duplicati": "♻️ Duplicados",
        "🚦 Limitati": "🚦 Limitados",
        "🧪 Simulati": "🧪 Simulados",
        "❌ Errori": "❌ Errores",
    },
}
