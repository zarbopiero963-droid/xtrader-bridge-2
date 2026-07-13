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
# fallback la restituisce già). Le chiavi devono esistere VERBATIM in un sorgente
# GUI (`app.py`, `dashboard_stats.py`, o una finestra secondaria localizzata come
# `provider_gui.py`): il test anti-drift le estrae via AST e fallisce se una chiave
# non è più usata nel codice (mai traduzioni orfane). I messaggi con variabili
# usano il TEMPLATE come chiave (es. «➕ Provider «{name}» salvato.») e il chiamante
# fa `i18n.tr(template).format(...)`; le traduzioni devono conservare gli stessi
# segnaposto (test di parità).
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
        # Stato listener (#343 slice 4b: la logica usa lo stato CANONICO
        # health_check.LISTENER_*, questi sono solo display; «⬤  OFFLINE» è
        # universale → fallback)
        "⬤  ATTIVO": "⬤  ACTIVE",
        "⬤  RICONNESSIONE…": "⬤  RECONNECTING…",
        # Banner di MODALITÀ (#343 slice 4 — residuo banner della #3). Chiavi = costanti
        # `real_mode.BANNER_TEXT` / `bridge_mode.COLLAUDO_BANNER_TEXT` (verbatim, l'anti-drift
        # le lega ai valori reali). Stringhe di SICUREZZA: la traduzione preserva la severità.
        "⚠️ MODALITÀ REALE ATTIVA — i segnali validi vengono scritti nel CSV "
        "operativo e XTrader può piazzare scommesse REALI.":
            "⚠️ REAL MODE ACTIVE — valid signals are written to the operational CSV "
            "and XTrader can place REAL bets.",
        "🔬 MODALITÀ COLLAUDO XTRADER — il CSV operativo VIENE scritto: "
        "XTrader deve essere in Modalità Simulazione "
        "(nessuna scommessa reale).":
            "🔬 XTRADER TEST MODE — the operational CSV IS written: "
            "XTrader must be in Simulation Mode (no real bets).",
        # Contatori Dashboard (chiavi in dashboard_stats.COUNTERS)
        "📥 Ricevuti": "📥 Received",
        "✅ Scritti": "✅ Written",
        "⚠️ Scartati": "⚠️ Discarded",
        "♻️ Duplicati": "♻️ Duplicates",
        "🚦 Limitati": "🚦 Limited",
        "🧪 Simulati": "🧪 Simulated",
        "❌ Errori": "❌ Errors",
        # Finestra Anagrafica Provider (#343 slice 4c; i messaggi con variabili
        # usano il template tradotto + .format(...), chiave = template)
        "📇  Anagrafica Provider": "📇  Provider registry",
        "Nomi Provider riutilizzabili nel Parser Personalizzato "
        "(colonna Provider). Valgono per tutti i parser.":
            "Provider names reusable in the Custom Parser "
            "(Provider column). They apply to all parsers.",
        "Nome del nuovo Provider": "New provider name",
        "➕  Aggiungi": "➕  Add",
        "Provider salvati": "Saved providers",
        "Nessun provider salvato.": "No provider saved.",
        "🗑  Rimuovi": "🗑  Remove",
        "Anagrafica Provider": "Provider registry",
        "⛔ Nome vuoto: provider non aggiunto.": "⛔ Empty name: provider not added.",
        "❌ Config illeggibile: {exc}": "❌ Config unreadable: {exc}",
        "ℹ️ «{name}» è già nell'anagrafica.": "ℹ️ «{name}» is already in the registry.",
        "➕ Provider «{name}» salvato.": "➕ Provider «{name}» saved.",
        "❌ Salvataggio FALLITO: «{name}» non salvato (andrebbe perso al riavvio). "
        "Controlla permessi/spazio del file config.":
            "❌ Save FAILED: «{name}» not saved (would be lost on restart). "
            "Check config file permissions/space.",
        "🗑 Provider «{name}» rimosso.": "🗑 Provider «{name}» removed.",
        "❌ Salvataggio FALLITO: «{name}» non rimosso (ricomparirebbe al riavvio). "
        "Controlla permessi/spazio del file config.":
            "❌ Save FAILED: «{name}» not removed (would reappear on restart). "
            "Check config file permissions/space.",
        # Finestra Profili impostazioni (#343 slice 4d)
        "📁  Profili impostazioni": "📁  Settings profiles",
        "Salva la configurazione corrente come profilo con un nome e "
        "ricaricala quando vuoi. Il token Telegram NON viene salvato nei "
        "profili e resta invariato al caricamento.":
            "Save the current configuration as a named profile and reload it "
            "whenever you like. The Telegram token is NOT saved in profiles and "
            "stays unchanged on load.",
        "Nome profilo (es. Prematch)": "Profile name (e.g. Prematch)",
        "💾  Salva profilo": "💾  Save profile",
        "Profili salvati": "Saved profiles",
        "(impossibile elencare i profili)": "(cannot list profiles)",
        "(nessun profilo salvato)": "(no profile saved)",
        "↺ Carica": "↺ Load",
        "🗑 Elimina": "🗑 Delete",
        "Profili impostazioni": "Settings profiles",
        "❌ Elenco profili non leggibile: {exc}": "❌ Profile list unreadable: {exc}",
        "⚠️ Ferma il bridge (STOP) prima di caricare un profilo: "
        "le impostazioni live cambiano solo al prossimo AVVIA.":
            "⚠️ Stop the bridge (STOP) before loading a profile: live settings "
            "change only on the next START.",
        "❌ Salvataggio profilo fallito: {exc}": "❌ Profile save failed: {exc}",
        "✅ Profilo {name!r} salvato (senza token).":
            "✅ Profile {name!r} saved (without token).",
        "✅ Profilo {name!r} caricato e applicato (token invariato).":
            "✅ Profile {name!r} loaded and applied (token unchanged).",
        "❌ Eliminazione fallita: {exc}": "❌ Delete failed: {exc}",
        "🗑 Profilo {name!r} eliminato.": "🗑 Profile {name!r} deleted.",
        "⚠️ Profilo {name!r} non trovato.": "⚠️ Profile {name!r} not found.",
        # Finestra Chat sorgenti (#343 slice 4e; solo chrome — sentinella
        # «(predefinito)», chip Traduzioni e errori di dominio restano IT)
        "📡  Chat sorgenti (multi-chat)": "📡  Source chats (multi-chat)",
        "Chat sorgenti (multi-chat)": "Source chats (multi-chat)",
        "Ogni sorgente è una chat/canale da cui accettare segnali. "
        "chat_id obbligatorio e univoco; una sorgente disattivata viene ignorata.":
            "Each source is a chat/channel to accept signals from. chat_id is "
            "required and unique; a disabled source is ignored.",
        "Attiva": "Enabled",
        "Nome": "Name",
        "Modalità": "Mode",
        "Traduzioni": "Translations",
        "➕  Aggiungi sorgente": "➕  Add source",
        "Parser della chat (in ordine di priorità)": "Chat parsers (in priority order)",
        "Il messaggio va a ogni parser in ordine; scattano TUTTI quelli le cui condizioni "
        "combaciano (una riga CSV per parser che scatta).":
            "The message is passed to each parser in order; ALL parsers whose conditions match "
            "fire (one CSV row per firing parser).",
        "➕ Aggiungi parser": "➕ Add parser",
        "Nessun parser: la chat usa il parser globale (predefinito).":
            "No parser: the chat uses the global (default) parser.",
        "💾  Salva": "💾  Save",
        "Niente salvato: correggi gli errori.": "Nothing saved: fix the errors.",
        "❌ Salvataggio su disco FALLITO: sorgenti NON salvate (andrebbero "
        "perse al riavvio). Controlla permessi/spazio del file config.":
            "❌ Disk save FAILED: sources NOT saved (would be lost on restart). "
            "Check config file permissions/space.",
        "✅ Salvate {n} sorgenti in config.json.":
            "✅ Saved {n} sources to config.json.",
        # Finestra Diario (#343 slice 4f; «🔄 Aggiorna» riusa la chiave già a catalogo)
        "📒  Diario eventi (locale, sola lettura)":
            "📒  Event journal (local, read-only)",
        "(tutti i tipi)": "(all types)",
        "Tutti": "All",
        "Tipo": "Type",
        "Ultimi": "Last",
        "📂 Apri cartella": "📂 Open folder",
        "Eventi del diario": "Journal events",
        "⚠️ Errore lettura diario: {kind}": "⚠️ Journal read error: {kind}",
        "Diario: {tot} eventi totali (mostrati {shown}).":
            "Journal: {tot} total events (showing {shown}).",
        "Quando": "When",
        "Dati (redatti)": "Data (redacted)",
        # Finestra Parser Personalizzato (#343 slice 4g; SOLO chrome puro). Non tradotti
        # per sicurezza: gli interruttori «MultiMarket (più mercati)»/«MultiSelection (più
        # selezioni)» e i VALORI delle tendine (Modalità/Sport/Mercato/Trasformazione/
        # Value-map) restano IT perché fungono da chiavi di config/confronto, e
        # `title="Provider"` è confrontato come `rule.target`. «Sport:» e «➕ Provider» sono
        # identici in EN → fallback, nessuna entry. «🗑 Elimina», «Attiva», «📋 Copia
        # diagnostica» riusano le chiavi già a catalogo.
        "Parser Personalizzato": "Custom Parser",
        "Nome parser:": "Parser name:",
        "Modalità:": "Mode:",
        "Parser salvati:": "Saved parsers:",
        "Catalogo XTrader:": "XTrader catalog:",
        "➕ Inserisci regole fisse": "➕ Insert fixed rules",
        "🔗 Traduzioni attive per questo parser": "🔗 Active translations for this parser",
        "Nomi squadra · separatore:": "Team names · separator:",
        "🗺️ Dizionario nomi": "🗺️ Names dictionary",
        "Mercati:": "Markets:",
        "🎯 Dizionario mercati": "🎯 Markets dictionary",
        "⚙️ Avanzate (Trasformazione · Value-map)": "⚙️ Advanced (Transform · Value-map)",
        "💾 Salva": "💾 Save",
        "🧪 Prova messaggio": "🧪 Test message",
        "🧪🧪 Prova più messaggi (separati da ---)":
            "🧪🧪 Test multiple messages (separated by ---)",
        "Messaggio di prova:": "Test message:",
        "Anteprima righe generate (#192):": "Preview of generated rows (#192):",
        "Diagnostica (una riga per colonna):": "Diagnostics (one row per column):",
        "Output multi-riga (un messaggio → più righe CSV)":
            "Multi-row output (one message → several CSV rows)",
        "Condizioni di gate (il parser scatta solo se il messaggio le soddisfa)":
            "Gate conditions (the parser fires only if the message satisfies them)",
        "Soddisfa:": "Satisfy:",
        "➕ Aggiungi condizione": "➕ Add condition",
        "testo da cercare nel messaggio": "text to search for in the message",
        "💡 «contiene»/«NON contiene» un testo; confronto senza maiuscole e "
        "tollerante agli spazi. Nessuna condizione = nessun filtro. Righe a "
        "testo vuoto sono ignorate.":
            "💡 «contains»/«does NOT contain» a text; case-insensitive, "
            "space-tolerant match. No condition = no filter. Empty-text rows "
            "are ignored.",
        "➕ Aggiungi mercato": "➕ Add market",
        "➕ Aggiungi selezione": "➕ Add selection",
        "🗑 Rimuovi": "🗑 Remove",
        "🆕 Nuovo": "🆕 New",
        "📂 Carica": "📂 Load",
        "📑 Duplica": "📑 Duplicate",
        "— nessuna": "— none",
        "✓ 1 attiva": "✓ 1 active",
        "✓ {count} attive": "✓ {count} active",
        "Nome del nuovo Provider:": "New provider name:",
        "⛔ Provider non aggiunto (nome vuoto).": "⛔ Provider not added (empty name).",
        "🆕 Nuovo parser (non ancora salvato).": "🆕 New parser (not yet saved).",
        "⛔ Nessun parser selezionato.": "⛔ No parser selected.",
        "Nuovo nome per la copia di {src!r}:": "New name for the copy of {src!r}:",
        "Duplica parser": "Duplicate parser",
        "⛔ Duplica annullata (nome vuoto).": "⛔ Duplication cancelled (empty name).",
        "❌ Non salvato:\n- ": "❌ Not saved:\n- ",
        "⛔ Nessun messaggio: incolla uno o più messaggi separati da una "
        "riga «---».":
            "⛔ No message: paste one or more messages separated by a «---» line.",
        "⛔ Premi prima «Prova messaggio».": "⛔ Press «Test message» first.",
        "❌ Copia non riuscita (appunti non disponibili).":
            "❌ Copy failed (clipboard unavailable).",
        "📋 Diagnostica copiata negli appunti.": "📋 Diagnostics copied to clipboard.",
        # Messaggi di STATO delle azioni Parser (#343 slice 4g; template + .format(...),
        # chiave = template IT). Il DATO interpolato ({exc}/{path}/{name}/…) resta invariato;
        # il testo di dominio bollato in {exc} (ParserBuilder/config) resta IT (slice separato).
        # «➕ Provider «{name}» salvato.» riusa la chiave già a catalogo (Anagrafica Provider).
        "❌ Errore salvataggio provider: {exc}": "❌ Error saving provider: {exc}",
        "⚠️ Provider «{name}» aggiunto solo in memoria (salvataggio fallito).":
            "⚠️ Provider «{name}» added in memory only (save failed).",
        "⛔ Non salvato: profili di mappatura nomi mancanti ({names}). "
        "Ricreali nel «Dizionario nomi» o togli la spunta prima di salvare.":
            "⛔ Not saved: missing name-mapping profiles ({names}). "
            "Recreate them in «Names dictionary» or untick before saving.",
        "⛔ Non salvato: profili di mappatura mercati mancanti ({names}). "
        "Ricreali nel «Dizionario mercati» o togli la spunta prima di salvare.":
            "⛔ Not saved: missing market-mapping profiles ({names}). "
            "Recreate them in «Markets dictionary» or untick before saving.",
        "❌ Errore salvataggio: {exc}": "❌ Save error: {exc}",
        "💾 Salvato in {path}": "💾 Saved to {path}",
        "➕ Regole fisse inserite: {market} · {selection}":
            "➕ Fixed rules inserted: {market} · {selection}",
        "❌ Errore caricamento: {exc}": "❌ Load error: {exc}",
        "📂 Caricato {name!r}.": "📂 Loaded {name!r}.",
        "❌ Errore duplica: {exc}": "❌ Duplicate error: {exc}",
        "📑 Duplicato in {new_name!r}.": "📑 Duplicated to {new_name!r}.",
        "❌ Errore eliminazione: {exc}": "❌ Delete error: {exc}",
        "🗑 Eliminato {name!r}.": "🗑 Deleted {name!r}.",
        "⛔ {name!r} non trovato.": "⛔ {name!r} not found.",
        # Finestra Wizard di prima configurazione (#343 slice 4h; SOLO chrome: titoli step,
        # nav, pulsanti azione, hint e messaggi GUI-composti). I `res.message` di dominio
        # bubblati da `wizard.py` (check_token/chat/parser/csv) restano IT (layer puro, slice
        # a parte). Le label «bottone» citate negli hint sono tradotte coerentemente.
        "🧙 Wizard di prima configurazione": "🧙 First-setup wizard",
        "1/5 · Token del bot": "1/5 · Bot token",
        "2/5 · Chat sorgente": "2/5 · Source chat",
        "3/5 · Parser sul messaggio reale": "3/5 · Parser on the real message",
        "4/5 · Percorso CSV": "4/5 · CSV path",
        "5/5 · Checklist finale": "5/5 · Final checklist",
        "◀ Indietro": "◀ Back",
        "Avanti ▶": "Next ▶",
        "Fine ✔": "Finish ✔",
        "⏳ Verifica in corso…": "⏳ Checking…",
        "⛔ Completa prima la verifica di questo step.":
            "⛔ Complete this step's verification first.",
        "✏️ Valore modificato dopo la verifica: ripeti la verifica.":
            "✏️ Value changed after verification: verify again.",
        "Verifica fallita: errore imprevisto ({kind}).":
            "Check failed: unexpected error ({kind}).",
        "🔌 Prova connessione (getMe)": "🔌 Test connection (getMe)",
        "📡 Controlla ora": "📡 Check now",
        "🧪 Valuta messaggio": "🧪 Evaluate message",
        "🔎 Verifica percorso": "🔎 Verify path",
        "📄 Scrivi CSV di prova": "📄 Write test CSV",
        "Incolla il token del bot creato con @BotFather, "
        "poi premi il test. Il token non compare mai nei log.":
            "Paste the bot token created with @BotFather, then press the test. "
            "The token never appears in the logs.",
        "Aggiungi il bot come ADMIN alla chat/canale, invia "
        "un messaggio di prova, inserisci il Chat ID e premi "
        "«Controlla ora». (Listener fermo: altrimenti consuma "
        "lui gli update.)":
            "Add the bot as ADMIN to the chat/channel, send a test message, enter the "
            "Chat ID and press «Check now». (Listener stopped: otherwise it consumes the "
            "updates itself.)",
        "Incolla un messaggio segnale REALE del canale: lo "
        "valuto col Parser Personalizzato ATTIVO (configuralo "
        "prima nella scheda 🧩 Parser se manca).":
            "Paste a REAL signal message from the channel: it is evaluated with the ACTIVE "
            "Custom Parser (configure it first in the 🧩 Parser tab if missing).",
        "Percorso del CSV letto da XTrader (identico nella "
        "sorgente segnali di XTrader). La scrittura di prova "
        "crea SOLO l'header e non tocca mai un CSV operativo.":
            "Path of the CSV read by XTrader (identical to XTrader's signal source). The "
            "test write creates ONLY the header and never touches an operational CSV.",
        "Nessun Parser Personalizzato attivo: configuralo nella "
        "scheda 🧩 Parser e riapri il wizard.":
            "No active Custom Parser: configure it in the 🧩 Parser tab and reopen the wizard.",
        "La checklist è informativa: il wizard NON attiva la "
        "modalità Reale (si passa dai gate della tab 🛡️ Sicurezza). "
        "Premi «Fine ✔» per salvare token/chat/CSV nella config.":
            "The checklist is informational: the wizard does NOT enable Real mode (that goes "
            "through the 🛡️ Safety tab gates). Press «Finish ✔» to save token/chat/CSV to "
            "the config.",
        # Finestra Mapping — Dizionario nomi + mercati (#343 slice 4i; SOLO chrome:
        # titoli, colonne, pulsanti, hint, messaggi di stato/dialogo. Esclusi (restano IT,
        # value-as-key): sentinelle tendina, valori Sport/Tipo/Lingua/Mercato, tab del container.
        "Country (opz.)": "Country (opt.)",
        "Betfair / XTrader": "Betfair / XTrader",
        "Come lo scrive il canale": "As the channel writes it",
        "Sport": "Sport",
        "Lingua": "Language",
        "Inizia dopo": "Start after",
        "Finisce prima": "End before",
        "Testo mercato": "Market text",
        "Mercato (catalogo)": "Market (catalog)",
        "Selezione (catalogo)": "Selection (catalog)",
        "🗺️  Dizionario nomi squadra": "🗺️  Team names dictionary",
        "🎯  Dizionario mercati": "🎯  Markets dictionary",
        "Dizionario nomi squadra": "Team names dictionary",
        "Dizionario mercati": "Markets dictionary",
        "Traduce i nomi squadra così come li scrive il canale nel nome atteso da Betfair/XTrader. Seleziona i profili nel Parser Personalizzato.": "Translates team names as the channel writes them into the name expected by Betfair/XTrader. Select the profiles in the Custom Parser.",
        "Legge il mercato da una posizione precisa del messaggio: «Inizia dopo» / «Finisce prima» (come nel Parser) ritagliano il campo, e se vi compare il «Testo mercato» imposta Mercato/Selezione dal Catalogo. Es.: Inizia dopo «Quota», Finisce prima «Prematch», Testo «0,5 HT». Seleziona i profili nel Parser Personalizzato.": "Reads the market from a precise position in the message: «Start after» / «End before» (as in the Parser) crop the field, and if the «Market text» appears there it sets Market/Selection from the Catalog. E.g.: Start after «Quota», End before «Prematch», Text «0,5 HT». Select the profiles in the Custom Parser.",
        "Profilo:": "Profile:",
        "✏️ Rinomina": "✏️ Rename",
        "Righe del profilo": "Profile rows",
        "➕ Aggiungi riga": "➕ Add row",
        "📥 Precompila da Betfair": "📥 Prefill from Betfair",
        "💾 Salva profilo": "💾 Save profile",
        "es. Quota": "e.g. Quota",
        "es. Prematch": "e.g. Prematch",
        "es. 0,5 HT": "e.g. 0,5 HT",
        "Nessun profilo. Crea un profilo con «Nuovo».": "No profile. Create one with «New».",
        "Nome del nuovo profilo:": "New profile name:",
        "Nome del nuovo profilo mercati:": "New markets profile name:",
        "Nuovo profilo": "New profile",
        "Nuovo nome per «{name}»:": "New name for «{name}»:",
        "Rinomina profilo": "Rename profile",
        "⛔ Crea prima un profilo con «Nuovo».": "⛔ Create a profile with «New» first.",
        "⛔ Nessun profilo selezionato.": "⛔ No profile selected.",
        "⛔ Profilo non creato (nome vuoto).": "⛔ Profile not created (empty name).",
        "⛔ Rinomina annullata (nome vuoto).": "⛔ Rename cancelled (empty name).",
        "⛔ Dizionario locale vuoto o non disponibile: popola prima il dizionario locale.": "⛔ Local dictionary empty or unavailable: populate the local dictionary first.",
        "⏳ Dizionario occupato: riprova tra poco.": "⏳ Dictionary busy: try again shortly.",
        "❌ Nomi Betfair non leggibili: {kind}": "❌ Betfair names unreadable: {kind}",
        "📥 Aggiunti {added} nomi Betfair (scrivi l'alias del canale in «Come lo scrive il canale»); {skipped} già presenti. Poi salva con 💾.": "📥 Added {added} Betfair names (write the channel alias in «As the channel writes it»); {skipped} already present. Then save with 💾.",
        "ℹ️ Nessun nuovo nome da aggiungere: ": "ℹ️ No new name to add: ",
        "i {skipped} nomi noti sono già in tabella.": "the {skipped} known names are already in the table.",
        "il dizionario locale è vuoto — popolalo prima.": "the local dictionary is empty — populate it first.",
        "💾 Profilo «{name}» salvato ({n} righe valide).": "💾 Profile «{name}» saved ({n} valid rows).",
        "💾 Profilo «{name}» salvato ({n} regole valide).": "💾 Profile «{name}» saved ({n} valid rules).",
        "  ⚠️ {count} riga/e ignorata/e perché incomplete: servono Testo mercato, Mercato e Selezione.": "  ⚠️ {count} row(s) ignored because incomplete: Market text, Market and Selection are required.",
        "  ⚠️ {count} regola/e SENZA delimitatori: salvata/e ma non applicata/e finché non compili «Inizia dopo»/«Finisce prima».": "  ⚠️ {count} rule(s) WITHOUT delimiters: saved but not applied until you fill in «Start after»/«End before».",
        "ℹ️ Il profilo «{name}» esiste già.": "ℹ️ Profile «{name}» already exists.",
        "ℹ️ Il profilo «{new}» esiste già.": "ℹ️ Profile «{new}» already exists.",
        "🆕 Profilo «{name}» creato.": "🆕 Profile «{name}» created.",
        "🗑 Profilo «{name}» eliminato.": "🗑 Profile «{name}» deleted.",
        "✏️ Profilo rinominato «{old}» → «{new}».": "✏️ Profile renamed «{old}» → «{new}».",
        "✏️ Profilo rinominato «{old}» → «{new}» · {count} parser aggiornati.": "✏️ Profile renamed «{old}» → «{new}» · {count} parsers updated.",
        "❌ Salvataggio FALLITO: «{name}» non creato.": "❌ Save FAILED: «{name}» not created.",
        "❌ Salvataggio FALLITO: «{name}» non eliminato.": "❌ Save FAILED: «{name}» not deleted.",
        "❌ Salvataggio FALLITO: rinomina non applicata.": "❌ Save FAILED: rename not applied.",
        "❌ Salvataggio FALLITO: cambio profilo annullato, modifiche mantenute a schermo. Controlla permessi/spazio del file config.": "❌ Save FAILED: profile switch cancelled, changes kept on screen. Check config file permissions/space.",
        "⚠️ Profilo rinominato «{old}» → «{new}», ma {count} parser NON aggiornati ({names}): correggili a mano o quei segnali verranno scartati (MAPPING_MISSING).": "⚠️ Profile renamed «{old}» → «{new}», but {count} parsers NOT updated ({names}): fix them by hand or those signals will be discarded (MAPPING_MISSING).",
        "⚠️ Profilo rinominato «{old}» → «{new}», ma {count} parser NON aggiornati ({names}): correggili a mano o quei segnali verranno scartati (MARKET_MAPPING_MISSING).": "⚠️ Profile renamed «{old}» → «{new}», but {count} parsers NOT updated ({names}): fix them by hand or those signals will be discarded (MARKET_MAPPING_MISSING).",
        "⚠️ «{name}» eliminato, ma è ancora selezionato in {count} parser ({names}): quei segnali verranno scartati (MAPPING_MISSING) finché non togli il profilo da quei parser.": "⚠️ «{name}» deleted, but it is still selected in {count} parsers ({names}): those signals will be discarded (MAPPING_MISSING) until you remove the profile from those parsers.",
        "⚠️ «{name}» eliminato, ma è ancora selezionato in {count} parser ({names}): quei segnali verranno scartati (MARKET_MAPPING_MISSING) finché non togli il profilo da quei parser.": "⚠️ «{name}» deleted, but it is still selected in {count} parsers ({names}): those signals will be discarded (MARKET_MAPPING_MISSING) until you remove the profile from those parsers.",
        # Log di ciclo-vita del bridge (#343 slice 4j): START/STOP/connessione/ascolto/
        # scadenza-segnale/svuotamento manuale CSV. "bridge"/"Telegram" restano verbatim
        # (termini di prodotto, come già nel resto del catalogo). I log di DOMINIO che
        # risalgono dai layer puri (bridge_mode/real_mode/config_store/outcome) restano IT.
        "🚀 Bridge avviato!": "🚀 Bridge started!",
        "📄 CSV: {path}": "📄 CSV: {path}",
        "⏱️  Auto-clear dopo: {seconds}s": "⏱️  Auto-clear after: {seconds}s",
        "👂 In ascolto su Telegram...": "👂 Listening on Telegram...",
        "🛑 Bridge fermato.": "🛑 Bridge stopped.",
        "✅ Connesso a Telegram.": "✅ Connected to Telegram.",
        "⏱️  Scadenza segnale tra ~{seconds}s": "⏱️  Signal expires in ~{seconds}s",
        "🗑️  CSV svuotato manualmente": "🗑️  CSV cleared manually",
        # Log azioni utente CONFIG/CSV (#343 slice 4k): salva config/tema, salva/crea CSV path.
        # «Crea CSV» tradotto come il bottone omonimo. I messaggi di stato del layer puro
        # (config_store.save_status_message) restano IT: qui si wrappa solo il PREFISSO. Il dato
        # interpolato {exc} è contenuto di dominio (resta invariato).
        "💾 Configurazione salvata": "💾 Configuration saved",
        "❌ CSV Path selezionato ma NON salvato: ": "❌ CSV Path selected but NOT saved: ",
        "📄 CSV Path aggiornato e salvato: {path}": "📄 CSV Path updated and saved: {path}",
        "❌ Preferenza tema NON salvata: ": "❌ Theme preference NOT saved: ",
        "🎨 Tema: chiaro": "🎨 Theme: light",
        "🎨 Tema: scuro": "🎨 Theme: dark",
        "⚠️ «Crea CSV» annullato: il bridge è AVVIATO su questo CSV. Fai STOP prima di ricrearlo.": "⚠️ «Create CSV» cancelled: the bridge is STARTED on this CSV. Stop it (STOP) before recreating it.",
        "❌ «Crea CSV» fallito: impossibile creare {path} ({exc}).": "❌ «Create CSV» failed: cannot create {path} ({exc}).",
        "⚠️ «Crea CSV» annullato: {path} esiste e NON è un CSV del bridge (non sovrascritto).": "⚠️ «Create CSV» cancelled: {path} exists and is NOT a bridge CSV (not overwritten).",
        "⚠️ «Crea CSV» annullato: {path} contiene un segnale attivo (non sovrascritto).": "⚠️ «Create CSV» cancelled: {path} contains an active signal (not overwritten).",
        "📄 CSV creato (solo header) e impostato: {path}": "📄 CSV created (header only) and set: {path}",
        "⚠️ «Crea CSV» annullato: bridge avviato su {path} (STOP prima).": "⚠️ «Create CSV» cancelled: bridge started on {path} (STOP first).",
        "⚠️ «Crea CSV» annullato dall'utente: {path} non sovrascritto.": "⚠️ «Create CSV» cancelled by user: {path} not overwritten.",
        # Log AVVIO/VALIDAZIONE START (#343 slice 4l): messaggi che bloccano/annullano lo START.
        # «bridge»/«Bot Token»/«listener»/«Parser Personalizzato» verbatim (termini prodotto).
        # I valori interpolati {err}/{problem}/{exc} sono contenuto di dominio (invariati); i log
        # `f"❌ {err}"`/`f"⚠️ {warn}"` di puro dominio restano IT non wrappati.
        "❌ python-telegram-bot non disponibile: impossibile avviare il listener.": "❌ python-telegram-bot not available: cannot start the listener.",
        "❌ Inserisci il Bot Token prima di avviare!": "❌ Enter the Bot Token before starting!",
        "❌ Impostazioni avanzate non valide (vedi avvisi sopra): correggile prima di avviare. Avvio annullato.": "❌ Invalid advanced settings (see warnings above): fix them before starting. Start cancelled.",
        "❌ Nessuna chat configurata (Chat ID, parser per-chat o sorgente): il bridge accetterebbe segnali da QUALSIASI chat. Configura almeno una chat/sorgente. Avvio annullato.": "❌ No chat configured (Chat ID, per-chat parser or source): the bridge would accept signals from ANY chat. Configure at least one chat/source. Start cancelled.",
        "❌ Nessun Parser Personalizzato configurato (globale o per-chat): il parser automatico è disattivato e il listener ignorerebbe OGNI segnale. Configura almeno un Parser Personalizzato prima di avviare (scheda 🧩 Parser). Avvio annullato.": "❌ No Custom Parser configured (global or per-chat): the automatic parser is disabled and the listener would ignore EVERY signal. Configure at least one Custom Parser before starting (🧩 Parser tab). Start cancelled.",
        "❌ Sorgenti multi-chat: {err}": "❌ Multi-chat sources: {err}",
        "Avvio annullato: correggi le sorgenti.": "Start cancelled: fix the sources.",
        "⏸️ Avvio automatico annullato: nessuna chat sorgente ATTIVA.": "⏸️ Automatic start cancelled: no ACTIVE source chat.",
        "⚠️ Nessuna chat sorgente ATTIVA: il listener parte ma NON processerà alcun segnale finché non attivi almeno una chat.": "⚠️ No ACTIVE source chat: the listener starts but will NOT process any signal until you activate at least one chat.",
        "❌ La Chat notifiche XTrader coincide con una chat sorgente: cambiala (i segnali verrebbero scambiati per conferme). Avvio annullato.": "❌ The XTrader notifications Chat coincides with a source chat: change it (signals would be mistaken for confirmations). Start cancelled.",
        "⏸️ Avvio automatico in modalità reale annullato.": "⏸️ Automatic start in real mode cancelled.",
        "▶️ Avvio automatico del listener (auto_start_listener attivo).": "▶️ Automatic listener start (auto_start_listener enabled).",
        "⏸️ Avvio in modalità reale annullato.": "⏸️ Start in real mode cancelled.",
        "❌ {problem} Avvio annullato.": "❌ {problem} Start cancelled.",
        "❌ Impossibile inizializzare il CSV ({path}): {exc}. Avvio annullato.": "❌ Cannot initialize the CSV ({path}): {exc}. Start cancelled.",
        # Log ESITO elaborazione messaggio/segnale (#343 slice 4m): dispatch ignore + scrittura
        # CSV + conferma/scadenza. «CSV»/«XTrader»/`xtrader_notification_chat_id` verbatim. I valori
        # {source}/{status}/{detail}/{exc}/{decision}/{msg}/{row}/{n} sono dominio (invariati). I log
        # di ESITO CONFERMA veri (outcome.*_log, confirmation_removed/ignored_log) restano IT.
        "⏳ Messaggio ignorato: troppo vecchio (probabile arretrato dopo una disconnessione).": "⏳ Message ignored: too old (probably a backlog after a disconnection).",
        "⚠️ Config live senza filtro chat: messaggio ignorato per sicurezza (configura chat/sorgenti, poi salva).": "⚠️ Live config without chat filter: message ignored for safety (configure chats/sources, then save).",
        "❌ La Chat notifiche XTrader coincide con una sorgente ammessa: config ambigua, messaggio IGNORATO (né segnale né conferma). Correggi xtrader_notification_chat_id (dev'essere una chat separata).": "❌ The XTrader notifications Chat coincides with an allowed source: ambiguous config, message IGNORED (neither signal nor confirmation). Fix xtrader_notification_chat_id (it must be a separate chat).",
        "⚠️ Esito instradamento sconosciuto ({decision}): messaggio ignorato per sicurezza.": "⚠️ Unknown routing outcome ({decision}): message ignored for safety.",
        "⚠️ Segnale scartato ({source}/{status}): {detail}": "⚠️ Signal discarded ({source}/{status}): {detail}",
        "❌ Scrittura CSV fallita: {exc}. Segnale non registrato (riprovabile).": "❌ CSV write failed: {exc}. Signal not recorded (retryable).",
        "🧾 Messaggio→CSV  |  msg: {msg}  |  riga: {row}": "🧾 Message→CSV  |  msg: {msg}  |  row: {row}",
        "❌ Aggiornamento CSV dopo conferma fallito: {exc}. Riprovo a breve.": "❌ CSV update after confirmation failed: {exc}. Retrying shortly.",
        "❌ Aggiornamento CSV alla scadenza fallito: {exc}. Riprovo a breve.": "❌ CSV update on expiry failed: {exc}. Retrying shortly.",
        "🗑️  {n} segnale/i scaduto/i rimosso/i dal CSV": "🗑️  {n} expired signal(s) removed from the CSV",
        # Log RESILIENZA runtime (#343 slice 4n): riconnessione/backoff + recovery CSV.
        # «listener»/«bridge»/«STOP»/«CSV» verbatim. I valori {exc}/{error}/{path}/{count} sono
        # dominio. I log di recovery con {quando} (value-as-key, confrontato == "all'avvio") restano IT.
        "🔄 Riconnesso: i messaggi arrivati durante la disconnessione vengono recuperati (i troppo vecchi restano scartati per freschezza).": "🔄 Reconnected: messages that arrived during the disconnection are recovered (the too-old ones stay discarded for freshness).",
        "❌ Errore non recuperabile del listener: {exc}. Bridge fermato.": "❌ Unrecoverable listener error: {exc}. Bridge stopped.",
        "🔌 Connessione persa ({error}): riconnessione tra {delay}s (tentativo {attempt})…": "🔌 Connection lost ({error}): reconnecting in {delay}s (attempt {attempt})…",
        "🧹 CSV ripulito al retry dopo lo STOP: {path}": "🧹 CSV cleaned on retry after STOP: {path}",
        "🧹 Rimossi {count} file temporanei CSV orfani all'avvio.": "🧹 Removed {count} orphan temporary CSV files at startup.",
        # Log LOG & DIAGNOSTICA (#343 slice 4o): cartella log, export audit, diagnostica, retention,
        # debug, svuota log. «Debug»/«ON»/«OFF» verbatim (stati tecnici). I valori {path}/{exc}/{count}/
        # {days} sono dominio. I suffissi config_store.save_status_message di retention/debug restano IT
        # (si wrappa solo il prefisso).
        "📂 Cartella log: {path}": "📂 Log folder: {path}",
        "❌ Impossibile aprire la cartella log: {exc}": "❌ Cannot open the log folder: {exc}",
        "🧾 Audit modalità reale esportato ({count} eventi): {path}": "🧾 Real-mode audit exported ({count} events): {path}",
        "❌ Esportazione audit reale fallita: {exc}": "❌ Real audit export failed: {exc}",
        "📋 Diagnostica copiata negli appunti.": "📋 Diagnostics copied to the clipboard.",
        "❌ Copia diagnostica fallita: {exc}": "❌ Diagnostics copy failed: {exc}",
        "❌ Retention log NON salvata. ": "❌ Log retention NOT saved. ",
        "🧹 Retention log: {days} giorni · {count} file vecchi rimossi.": "🧹 Log retention: {days} days · {count} old files removed.",
        "🧹 Retention log: conservo tutto (nessuna pulizia automatica).": "🧹 Log retention: keep everything (no automatic cleanup).",
        "🧹 Log svuotati: {count} file su disco rimossi; vista azzerata.": "🧹 Logs cleared: {count} files removed from disk; view reset.",
        "🐞 Modalità Debug log: {state}.": "🐞 Debug log mode: {state}.",
        "⚠️ Impostazione Debug NON salvata. ": "⚠️ Debug setting NOT saved. ",
        "🧹 Retention log ({days}g): {count} file vecchi rimossi.": "🧹 Log retention ({days}d): {count} old files removed.",
        # Log WIZARD + LINGUA-SELECTOR + PROFILO/SORGENTI (#343 slice 4p). «wizard»/«asistente»,
        # «Profilo»/«Perfil», «Sorgenti»/«Fuentes», «Scheda»/«Tab» coerenti col catalogo. I valori
        # {exc}/{lang}/{tab}/{count} sono dominio. Il log SUCCESS «🌐 Lingua del bridge impostata …»
        # (con {extra} computato + nota) è rimandato a una slice dedicata; il suffisso
        # config_store.save_status_message di «Profilo … NON persistito» resta IT (solo prefisso wrappato).
        "❌ Apertura wizard fallita: {exc}": "❌ Failed to open the wizard: {exc}",
        "🧙 Wizard completato: configurazione salvata.": "🧙 Wizard completed: configuration saved.",
        "🌐 Selettore lingua rimandato: auto-start attivo (imposta app_language in config.json, o disattiva l'auto-start).": "🌐 Language selector postponed: auto-start is on (set app_language in config.json, or disable auto-start).",
        "⚠️ Lingua scelta ({lang}) ma salvataggio config FALLITO: nulla è cambiato (la sessione resta nella lingua precedente) e il selettore riapparirà al prossimo avvio — controlla permessi/spazio disco.": "⚠️ Language chosen ({lang}) but config save FAILED: nothing changed (the session stays in the previous language) and the selector will reappear at the next startup — check permissions/disk space.",
        "⚠️ Scheda {tab} non aggiornata dal profilo (mostra ancora i valori precedenti): {exc}": "⚠️ Tab {tab} not updated from the profile (still shows the previous values): {exc}",
        "📁 Profilo caricato e applicato (token invariato).": "📁 Profile loaded and applied (token unchanged).",
        "⚠️ Profilo applicato in memoria (token invariato), ma NON persistito. ": "⚠️ Profile applied in memory (token unchanged), but NOT persisted. ",
        "📡 Sorgenti multi-chat aggiornate ({count}).": "📡 Multi-chat sources updated ({count}).",
        # Log GUARDRAIL RUNTIME (#343 slice 4q): stato anti-duplicato/limite-giornaliero + modalità
        # coda. Termini prodotto («OVERWRITE_LAST», nomi modalità in {mode}) restano invariati; {mode}
        # è valore di dominio da runtime_state.build_guards (display, non usato come chiave). Gli avvisi
        # fail-safe di build_guards (`self._log(warning)`, bolla di dominio da layer puro) restano IT.
        "⚠️ Stato anti-duplicato presente ma illeggibile: protezione dopo riavvio non garantita.": "⚠️ Anti-duplicate state present but unreadable: protection after restart not guaranteed.",
        "🧮 Modalità coda: {mode}": "🧮 Queue mode: {mode}",
        "⚠️ Impossibile salvare lo stato anti-duplicato su disco: protezione dopo riavvio degradata.": "⚠️ Unable to save the anti-duplicate state to disk: protection after restart degraded.",
        "⚠️ Impossibile salvare lo stato del limite giornaliero su disco: protezione anti-overtrading dopo riavvio degradata.": "⚠️ Unable to save the daily-limit state to disk: anti-overtrading protection after restart degraded.",
        # Log MODE-TRANSITION ANNULLATA (#343 slice 4r): annullo delle conferme di transizione
        # pericolosa in _gate_dangerous_transitions. «REALE»→«REAL», «COLLAUDO»→«TEST» coerenti coi
        # banner di modalità; «OVERWRITE_LAST» (termine prodotto) e {old_mode} (valore di dominio da
        # bridge_mode.mode_from_cfg: SIMULAZIONE/COLLAUDO/REALE) restano invariati. Il log di AUDIT
        # «⚠️ » + real_mode.enabled_message() (bolla di dominio da layer puro) resta IT (solo prefisso).
        "↩️ Attivazione modalità REALE ANNULLATA: torno a {old_mode}.": "↩️ REAL mode activation CANCELLED: reverting to {old_mode}.",
        "↩️ Attivazione modalità COLLAUDO ANNULLATA: torno a {old_mode}.": "↩️ TEST mode activation CANCELLED: reverting to {old_mode}.",
        "↩️ Modalità coda multi-segnale ANNULLATA: resto a un solo segnale attivo (OVERWRITE_LAST).": "↩️ Multi-signal queue mode CANCELLED: staying with a single active signal (OVERWRITE_LAST).",
        # NOMI MODALITÀ di trading (#343 slice 4s / Issue #45): nome breve localizzato reso da
        # App._mode_display_name SOLO per i log (presentazione). Coerenti coi banner di modalità
        # (slice 4). Il VALORE di dominio usato dai gate (bridge_mode.mode_from_cfg) resta invariato:
        # qui si traduce solo la resa testuale nel log. La modalità coda ({mode}: OVERWRITE_LAST/FIFO)
        # NON rientra: sono termini tecnici, non parole IT.
        "SIMULAZIONE": "SIMULATION",
        "COLLAUDO": "TEST",
        "REALE": "REAL",
        # Pannello «🧹 Nomi squadra noti» (#343 slice 4t): scheda di ripulitura dei nomi squadra
        # permanenti del dizionario locale. I nomi sport ({sport}) e i nomi squadra sono valori di
        # dominio (restano invariati); {exc}=classe eccezione, {count}=conteggio. «Sport» resta
        # invariato in EN (parola identica). Il sentinel «(tutti gli sport)» è un VALUE-AS-KEY
        # (confronto `s == _SPORT_ALL` in _selected_sport): resta IT e NON è a catalogo.
        "🧹  Nomi squadra noti (permanenti) — ripulitura": "🧹  Known team names (permanent) — cleanup",
        "Nomi squadra del dizionario locale, conservati per sempre. Elimina qui quelli obsoleti/errati (es. squadre retrocesse).": "Team names from the local dictionary, kept forever. Delete obsolete/wrong ones here (e.g. relegated teams).",
        "Sport": "Sport",
        "🔄 Aggiorna": "🔄 Refresh",
        "Nomi noti": "Known names",
        "⛔ Provider del dizionario locale non disponibile.": "⛔ Local dictionary provider not available.",
        "⏳ Dizionario occupato: riprova tra poco.": "⏳ Dictionary busy: try again shortly.",
        "⚠️ Errore lettura nomi: {exc}": "⚠️ Error reading names: {exc}",
        "{count} nomi noti.": "{count} known names.",
        "🗑 Elimina": "🗑 Delete",
        "⛔ Eliminazione non disponibile.": "⛔ Deletion not available.",
        "⚠️ Eliminazione fallita: {exc}": "⚠️ Deletion failed: {exc}",
        "⚠️ Eliminazione non riuscita: dizionario locale non disponibile.": "⚠️ Deletion failed: local dictionary not available.",
        # Pannello «📋 Riepilogo configurazione» (#343 slice 4u): helper puri di presentazione
        # (mode/betfair/traduzioni/pronto/canali) + testi inline del render. {ready}/{total}=conteggi,
        # {exc}=eccezione. RESTANO IT: la riga «Parser: …» (termine prodotto + nomi parser di dominio,
        # niente da tradurre), il MOTIVO di «⚠ <motivo>» (testo di dominio da config_summary), e i
        # nomi canale/chat_id (valori di dominio).
        "🔴 MODALITÀ REALE": "🔴 REAL MODE",
        "🧪 Simulazione (DRY_RUN)": "🧪 Simulation (DRY_RUN)",
        "Dizionario locale: presente": "Local dictionary: present",
        "Dizionario locale: vuoto": "Local dictionary: empty",
        "Nomi": "Names",
        "Mercati": "Markets",
        "✅ Pronto": "✅ Ready",
        "(canale senza chat_id)": "(channel without chat_id)",
        "Canali pronti: {ready}/{total}": "Ready channels: {ready}/{total}",
        "Nessun canale configurato (nessuna sorgente / chat).": "No channel configured (no source / chat).",
        "📋 Riepilogo configurazione": "📋 Configuration summary",
        "Nessun dato di configurazione.": "No configuration data.",
        "⚠️ Impossibile leggere la configurazione:\n{exc}": "⚠️ Unable to read the configuration:\n{exc}",
        # Pannello «🌳 Mapping guidato» — CHROME (#343 slice 4v): titolo/descrizione, label di riga
        # (Profilo/Sport/Competizione già a catalogo), filtro, intestazioni colonne, bottoni,
        # placeholder e dialog «Nuovo profilo». «Betfair» è termine prodotto (invariato). RESTANO IT
        # (value-as-key, NON a catalogo): i segnaposto «(nessun profilo)»/«(scegli lo sport)». I nomi
        # sport/competizione/squadra sono valori di dominio. I MESSAGGI DI STATO dinamici → slice 4w.
        "🌳  Mapping guidato (Betfair → nome canale)": "🌳  Guided mapping (Betfair → channel name)",
        "Scegli Sport → Competizione: compaiono le squadre dai dati Betfair presenti nel dizionario. Accanto a ogni squadra scrivi «come la chiama il canale» e salva nel profilo. Serve un dizionario locale popolato.": "Choose Sport → Competition: the teams from the Betfair data in the dictionary appear. Next to each team write «how the channel calls it» and save to the profile. A populated local dictionary is required.",
        "Competizione:": "Competition:",
        "Filtra squadre:": "Filter teams:",
        "parte del nome squadra…": "part of the team name…",
        "Pulisci": "Clear",
        "Squadra Betfair": "Betfair team",
        "Come la chiama il canale": "How the channel calls it",
        "Squadre": "Teams",
        "💾 Salva nel profilo": "💾 Save to profile",
        "Scegli Sport e Competizione per vedere le squadre.": "Choose Sport and Competition to see the teams.",
        "come la chiama il canale…": "how the channel calls it…",
        # Pannello «🌳 Mapping guidato» — MESSAGGI DI STATO (#343 slice 4w): esiti dinamici di
        # profilo/competizioni/squadre/salvataggio. {exc}=eccezione, {name}/{profile}=nome profilo,
        # {sport}=nome sport, {count}/{shown}/{total}/{written}=conteggi — valori di dominio nei
        # segnaposto. «⏳ Dizionario occupato: riprova tra poco.» è già a catalogo (slice 4t).
        "❌ Config illeggibile: {exc}": "❌ Config unreadable: {exc}",
        "⛔ Profilo non creato (nome vuoto).": "⛔ Profile not created (empty name).",
        "ℹ️ Il profilo «{name}» esiste già.": "ℹ️ The profile «{name}» already exists.",
        "🆕 Profilo «{name}» creato.": "🆕 Profile «{name}» created.",
        "❌ Salvataggio FALLITO: «{name}» non creato.": "❌ Save FAILED: «{name}» not created.",
        "ℹ️ Nessuna competizione per «{sport}». Popola il dizionario locale, poi riprova.": "ℹ️ No competition for «{sport}». Populate the local dictionary, then try again.",
        "ℹ️ Nessuna squadra per questa competizione (nessun evento nel dizionario). Popola il dizionario locale, poi riprova.": "ℹ️ No team for this competition (no event in the dictionary). Populate the local dictionary, then try again.",
        "{count} squadre. Scrivi l'alias del canale e premi «Salva nel profilo».": "{count} teams. Type the channel alias and press «Save to profile».",
        "… mostrate {shown} di {total} squadre: usa «Filtra» per restringere (gli alias già scritti restano salvati anche se non visibili).": "… showing {shown} of {total} teams: use «Filter» to narrow down (aliases already typed stay saved even if not visible).",
        "⛔ Nessun profilo selezionato: crea o scegli un profilo di destinazione.": "⛔ No profile selected: create or choose a destination profile.",
        "⛔ Nessuna squadra caricata da salvare.": "⛔ No team loaded to save.",
        "💾 Salvato nel profilo «{profile}»: {written} squadre mappate in questa competizione ({total} righe totali nel profilo).": "💾 Saved to profile «{profile}»: {written} teams mapped in this competition ({total} total rows in the profile).",
        "❌ Salvataggio FALLITO: «{profile}» non salvato (andrebbe perso al riavvio). Controlla permessi/spazio del file config.": "❌ Save FAILED: «{profile}» not saved (would be lost on restart). Check permissions/space of the config file.",
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
        # Stato listener (#343 slice 4b)
        "⬤  ATTIVO": "⬤  ACTIVO",
        "⬤  RICONNESSIONE…": "⬤  RECONEXIÓN…",
        # Banner di MODALITÀ (#343 slice 4 — residuo banner della #3). Stringhe di SICUREZZA.
        "⚠️ MODALITÀ REALE ATTIVA — i segnali validi vengono scritti nel CSV "
        "operativo e XTrader può piazzare scommesse REALI.":
            "⚠️ MODO REAL ACTIVO — las señales válidas se escriben en el CSV "
            "operativo y XTrader puede realizar apuestas REALES.",
        "🔬 MODALITÀ COLLAUDO XTRADER — il CSV operativo VIENE scritto: "
        "XTrader deve essere in Modalità Simulazione "
        "(nessuna scommessa reale).":
            "🔬 MODO DE PRUEBA XTRADER — el CSV operativo SE escribe: "
            "XTrader debe estar en Modo Simulación (sin apuestas reales).",
        # Contatori Dashboard (chiavi in dashboard_stats.COUNTERS)
        "📥 Ricevuti": "📥 Recibidos",
        "✅ Scritti": "✅ Escritos",
        "⚠️ Scartati": "⚠️ Descartados",
        "♻️ Duplicati": "♻️ Duplicados",
        "🚦 Limitati": "🚦 Limitados",
        "🧪 Simulati": "🧪 Simulados",
        "❌ Errori": "❌ Errores",
        # Finestra Anagrafica Provider (#343 slice 4c)
        "📇  Anagrafica Provider": "📇  Registro de proveedores",
        "Nomi Provider riutilizzabili nel Parser Personalizzato "
        "(colonna Provider). Valgono per tutti i parser.":
            "Nombres de proveedor reutilizables en el Parser Personalizado "
            "(columna Provider). Valen para todos los parsers.",
        "Nome del nuovo Provider": "Nombre del nuevo proveedor",
        "➕  Aggiungi": "➕  Añadir",
        "Provider salvati": "Proveedores guardados",
        "Nessun provider salvato.": "Ningún proveedor guardado.",
        "🗑  Rimuovi": "🗑  Eliminar",
        "Anagrafica Provider": "Registro de proveedores",
        "⛔ Nome vuoto: provider non aggiunto.":
            "⛔ Nombre vacío: proveedor no añadido.",
        "❌ Config illeggibile: {exc}": "❌ Config ilegible: {exc}",
        "ℹ️ «{name}» è già nell'anagrafica.": "ℹ️ «{name}» ya está en el registro.",
        "➕ Provider «{name}» salvato.": "➕ Proveedor «{name}» guardado.",
        "❌ Salvataggio FALLITO: «{name}» non salvato (andrebbe perso al riavvio). "
        "Controlla permessi/spazio del file config.":
            "❌ Guardado FALLIDO: «{name}» no guardado (se perdería al reiniciar). "
            "Comprueba permisos/espacio del archivo config.",
        "🗑 Provider «{name}» rimosso.": "🗑 Proveedor «{name}» eliminado.",
        "❌ Salvataggio FALLITO: «{name}» non rimosso (ricomparirebbe al riavvio). "
        "Controlla permessi/spazio del file config.":
            "❌ Guardado FALLIDO: «{name}» no eliminado (reaparecería al reiniciar). "
            "Comprueba permisos/espacio del archivo config.",
        # Finestra Profili impostazioni (#343 slice 4d)
        "📁  Profili impostazioni": "📁  Perfiles de configuración",
        "Salva la configurazione corrente come profilo con un nome e "
        "ricaricala quando vuoi. Il token Telegram NON viene salvato nei "
        "profili e resta invariato al caricamento.":
            "Guarda la configuración actual como un perfil con un nombre y "
            "recárgala cuando quieras. El token de Telegram NO se guarda en los "
            "perfiles y permanece sin cambios al cargar.",
        "Nome profilo (es. Prematch)": "Nombre del perfil (p. ej. Prematch)",
        "💾  Salva profilo": "💾  Guardar perfil",
        "Profili salvati": "Perfiles guardados",
        "(impossibile elencare i profili)": "(no se pueden listar los perfiles)",
        "(nessun profilo salvato)": "(ningún perfil guardado)",
        "↺ Carica": "↺ Cargar",
        "🗑 Elimina": "🗑 Eliminar",
        "Profili impostazioni": "Perfiles de configuración",
        "❌ Elenco profili non leggibile: {exc}":
            "❌ Lista de perfiles ilegible: {exc}",
        "⚠️ Ferma il bridge (STOP) prima di caricare un profilo: "
        "le impostazioni live cambiano solo al prossimo AVVIA.":
            "⚠️ Detén el bridge (STOP) antes de cargar un perfil: los ajustes en "
            "vivo cambian solo en el próximo INICIAR.",
        "❌ Salvataggio profilo fallito: {exc}": "❌ Guardado del perfil fallido: {exc}",
        "✅ Profilo {name!r} salvato (senza token).":
            "✅ Perfil {name!r} guardado (sin token).",
        "✅ Profilo {name!r} caricato e applicato (token invariato).":
            "✅ Perfil {name!r} cargado y aplicado (token sin cambios).",
        "❌ Eliminazione fallita: {exc}": "❌ Eliminación fallida: {exc}",
        "🗑 Profilo {name!r} eliminato.": "🗑 Perfil {name!r} eliminado.",
        "⚠️ Profilo {name!r} non trovato.": "⚠️ Perfil {name!r} no encontrado.",
        # Finestra Chat sorgenti (#343 slice 4e)
        "📡  Chat sorgenti (multi-chat)": "📡  Chats de origen (multi-chat)",
        "Chat sorgenti (multi-chat)": "Chats de origen (multi-chat)",
        "Ogni sorgente è una chat/canale da cui accettare segnali. "
        "chat_id obbligatorio e univoco; una sorgente disattivata viene ignorata.":
            "Cada origen es un chat/canal del que aceptar señales. chat_id es "
            "obligatorio y único; un origen desactivado se ignora.",
        "Attiva": "Activa",
        "Nome": "Nombre",
        "Modalità": "Modo",
        "Provider": "Proveedor",
        "Traduzioni": "Traducciones",
        "➕  Aggiungi sorgente": "➕  Añadir origen",
        "Parser della chat (in ordine di priorità)": "Parsers del chat (en orden de prioridad)",
        "Il messaggio va a ogni parser in ordine; scattano TUTTI quelli le cui condizioni "
        "combaciano (una riga CSV per parser che scatta).":
            "El mensaje se pasa a cada parser en orden; se activan TODOS los que cumplen sus "
            "condiciones (una fila CSV por parser activado).",
        "➕ Aggiungi parser": "➕ Añadir parser",
        "Nessun parser: la chat usa il parser globale (predefinito).":
            "Sin parser: el chat usa el parser global (predeterminado).",
        "💾  Salva": "💾  Guardar",
        "Niente salvato: correggi gli errori.": "Nada guardado: corrige los errores.",
        "❌ Salvataggio su disco FALLITO: sorgenti NON salvate (andrebbero "
        "perse al riavvio). Controlla permessi/spazio del file config.":
            "❌ Guardado en disco FALLIDO: orígenes NO guardados (se perderían al "
            "reiniciar). Comprueba permisos/espacio del archivo config.",
        "✅ Salvate {n} sorgenti in config.json.":
            "✅ Guardados {n} orígenes en config.json.",
        # Finestra Diario (#343 slice 4f)
        "📒  Diario eventi (locale, sola lettura)":
            "📒  Diario de eventos (local, solo lectura)",
        "(tutti i tipi)": "(todos los tipos)",
        "Tutti": "Todos",
        "Tipo": "Tipo",
        "Ultimi": "Últimos",
        "📂 Apri cartella": "📂 Abrir carpeta",
        "Eventi del diario": "Eventos del diario",
        "⚠️ Errore lettura diario: {kind}": "⚠️ Error de lectura del diario: {kind}",
        "Diario: {tot} eventi totali (mostrati {shown}).":
            "Diario: {tot} eventos en total (mostrados {shown}).",
        "Quando": "Cuándo",
        "Dati (redatti)": "Datos (redactados)",
        # Finestra Parser Personalizzato (#343 slice 4g; SOLO chrome puro). Come per EN,
        # gli interruttori MultiMarket/MultiSelection, i VALORI delle tendine e
        # `title="Provider"` restano IT (config/confronto). «🗑 Elimina», «Attiva»,
        # «📋 Copia diagnostica» riusano le chiavi già a catalogo. In ES «Sport:»/«➕ Provider»
        # differiscono, quindi hanno una entry.
        "Parser Personalizzato": "Parser Personalizado",
        "Nome parser:": "Nombre del parser:",
        "Modalità:": "Modo:",
        "Sport:": "Deporte:",
        "Parser salvati:": "Parsers guardados:",
        "Catalogo XTrader:": "Catálogo XTrader:",
        "➕ Provider": "➕ Proveedor",
        "➕ Inserisci regole fisse": "➕ Insertar reglas fijas",
        "🔗 Traduzioni attive per questo parser": "🔗 Traducciones activas para este parser",
        "Nomi squadra · separatore:": "Nombres de equipo · separador:",
        "🗺️ Dizionario nomi": "🗺️ Diccionario de nombres",
        "Mercati:": "Mercados:",
        "🎯 Dizionario mercati": "🎯 Diccionario de mercados",
        "⚙️ Avanzate (Trasformazione · Value-map)": "⚙️ Avanzadas (Transformación · Value-map)",
        "💾 Salva": "💾 Guardar",
        "🧪 Prova messaggio": "🧪 Probar mensaje",
        "🧪🧪 Prova più messaggi (separati da ---)":
            "🧪🧪 Probar varios mensajes (separados por ---)",
        "Messaggio di prova:": "Mensaje de prueba:",
        "Anteprima righe generate (#192):": "Vista previa de filas generadas (#192):",
        "Diagnostica (una riga per colonna):": "Diagnóstico (una fila por columna):",
        "Output multi-riga (un messaggio → più righe CSV)":
            "Salida multifila (un mensaje → varias filas CSV)",
        "Condizioni di gate (il parser scatta solo se il messaggio le soddisfa)":
            "Condiciones de activación (el parser se dispara solo si el mensaje las cumple)",
        "Soddisfa:": "Cumple:",
        "➕ Aggiungi condizione": "➕ Añadir condición",
        "testo da cercare nel messaggio": "texto a buscar en el mensaje",
        "💡 «contiene»/«NON contiene» un testo; confronto senza maiuscole e "
        "tollerante agli spazi. Nessuna condizione = nessun filtro. Righe a "
        "testo vuoto sono ignorate.":
            "💡 «contiene»/«NO contiene» un texto; comparación sin mayúsculas y "
            "tolerante a espacios. Sin condiciones = sin filtro. Las filas con "
            "texto vacío se ignoran.",
        "➕ Aggiungi mercato": "➕ Añadir mercado",
        "➕ Aggiungi selezione": "➕ Añadir selección",
        "🗑 Rimuovi": "🗑 Eliminar",
        "🆕 Nuovo": "🆕 Nuevo",
        "📂 Carica": "📂 Cargar",
        "📑 Duplica": "📑 Duplicar",
        "— nessuna": "— ninguna",
        "✓ 1 attiva": "✓ 1 activa",
        "✓ {count} attive": "✓ {count} activas",
        "Nome del nuovo Provider:": "Nombre del nuevo proveedor:",
        "⛔ Provider non aggiunto (nome vuoto).": "⛔ Proveedor no añadido (nombre vacío).",
        "🆕 Nuovo parser (non ancora salvato).": "🆕 Nuevo parser (aún no guardado).",
        "⛔ Nessun parser selezionato.": "⛔ Ningún parser seleccionado.",
        "Nuovo nome per la copia di {src!r}:": "Nuevo nombre para la copia de {src!r}:",
        "Duplica parser": "Duplicar parser",
        "⛔ Duplica annullata (nome vuoto).": "⛔ Duplicación cancelada (nombre vacío).",
        "❌ Non salvato:\n- ": "❌ No guardado:\n- ",
        "⛔ Nessun messaggio: incolla uno o più messaggi separati da una "
        "riga «---».":
            "⛔ Ningún mensaje: pega uno o más mensajes separados por una línea «---».",
        "⛔ Premi prima «Prova messaggio».": "⛔ Pulsa «Probar mensaje» primero.",
        "❌ Copia non riuscita (appunti non disponibili).":
            "❌ Copia fallida (portapapeles no disponible).",
        "📋 Diagnostica copiata negli appunti.": "📋 Diagnóstico copiado al portapapeles.",
        # Messaggi di STATO delle azioni Parser (#343 slice 4g). Come EN: DATO interpolato
        # invariato e testo di dominio in {exc} resta IT. «➕ Provider «{name}» salvato.»
        # riusa la chiave già a catalogo.
        "❌ Errore salvataggio provider: {exc}": "❌ Error al guardar el proveedor: {exc}",
        "⚠️ Provider «{name}» aggiunto solo in memoria (salvataggio fallito).":
            "⚠️ Proveedor «{name}» añadido solo en memoria (guardado fallido).",
        "⛔ Non salvato: profili di mappatura nomi mancanti ({names}). "
        "Ricreali nel «Dizionario nomi» o togli la spunta prima di salvare.":
            "⛔ No guardado: faltan perfiles de mapeo de nombres ({names}). "
            "Vuelve a crearlos en «Diccionario de nombres» o desmárcalos antes de guardar.",
        "⛔ Non salvato: profili di mappatura mercati mancanti ({names}). "
        "Ricreali nel «Dizionario mercati» o togli la spunta prima di salvare.":
            "⛔ No guardado: faltan perfiles de mapeo de mercados ({names}). "
            "Vuelve a crearlos en «Diccionario de mercados» o desmárcalos antes de guardar.",
        "❌ Errore salvataggio: {exc}": "❌ Error al guardar: {exc}",
        "💾 Salvato in {path}": "💾 Guardado en {path}",
        "➕ Regole fisse inserite: {market} · {selection}":
            "➕ Reglas fijas insertadas: {market} · {selection}",
        "❌ Errore caricamento: {exc}": "❌ Error al cargar: {exc}",
        "📂 Caricato {name!r}.": "📂 Cargado {name!r}.",
        "❌ Errore duplica: {exc}": "❌ Error al duplicar: {exc}",
        "📑 Duplicato in {new_name!r}.": "📑 Duplicado en {new_name!r}.",
        "❌ Errore eliminazione: {exc}": "❌ Error al eliminar: {exc}",
        "🗑 Eliminato {name!r}.": "🗑 Eliminado {name!r}.",
        "⛔ {name!r} non trovato.": "⛔ {name!r} no encontrado.",
        # Finestra Wizard di prima configurazione (#343 slice 4h; SOLO chrome). I `res.message`
        # di dominio da `wizard.py` restano IT (layer puro). Label «bottone» negli hint coerenti.
        "🧙 Wizard di prima configurazione": "🧙 Asistente de primera configuración",
        "1/5 · Token del bot": "1/5 · Token del bot",
        "2/5 · Chat sorgente": "2/5 · Chat de origen",
        "3/5 · Parser sul messaggio reale": "3/5 · Parser sobre el mensaje real",
        "4/5 · Percorso CSV": "4/5 · Ruta CSV",
        "5/5 · Checklist finale": "5/5 · Checklist final",
        "◀ Indietro": "◀ Atrás",
        "Avanti ▶": "Siguiente ▶",
        "Fine ✔": "Finalizar ✔",
        "⏳ Verifica in corso…": "⏳ Comprobando…",
        "⛔ Completa prima la verifica di questo step.":
            "⛔ Completa primero la verificación de este paso.",
        "✏️ Valore modificato dopo la verifica: ripeti la verifica.":
            "✏️ Valor modificado tras la verificación: vuelve a verificar.",
        "Verifica fallita: errore imprevisto ({kind}).":
            "Comprobación fallida: error inesperado ({kind}).",
        "🔌 Prova connessione (getMe)": "🔌 Probar conexión (getMe)",
        "📡 Controlla ora": "📡 Comprobar ahora",
        "🧪 Valuta messaggio": "🧪 Evaluar mensaje",
        "🔎 Verifica percorso": "🔎 Verificar ruta",
        "📄 Scrivi CSV di prova": "📄 Escribir CSV de prueba",
        "Incolla il token del bot creato con @BotFather, "
        "poi premi il test. Il token non compare mai nei log.":
            "Pega el token del bot creado con @BotFather, luego pulsa la prueba. "
            "El token nunca aparece en los logs.",
        "Aggiungi il bot come ADMIN alla chat/canale, invia "
        "un messaggio di prova, inserisci il Chat ID e premi "
        "«Controlla ora». (Listener fermo: altrimenti consuma "
        "lui gli update.)":
            "Añade el bot como ADMIN al chat/canal, envía un mensaje de prueba, introduce "
            "el Chat ID y pulsa «Comprobar ahora». (Listener detenido: de lo contrario "
            "consume él las actualizaciones.)",
        "Incolla un messaggio segnale REALE del canale: lo "
        "valuto col Parser Personalizzato ATTIVO (configuralo "
        "prima nella scheda 🧩 Parser se manca).":
            "Pega un mensaje de señal REAL del canal: se evalúa con el Parser Personalizado "
            "ACTIVO (configúralo primero en la pestaña 🧩 Parser si falta).",
        "Percorso del CSV letto da XTrader (identico nella "
        "sorgente segnali di XTrader). La scrittura di prova "
        "crea SOLO l'header e non tocca mai un CSV operativo.":
            "Ruta del CSV leído por XTrader (idéntica a la fuente de señales de XTrader). "
            "La escritura de prueba crea SOLO el encabezado y nunca toca un CSV operativo.",
        "Nessun Parser Personalizzato attivo: configuralo nella "
        "scheda 🧩 Parser e riapri il wizard.":
            "Ningún Parser Personalizado activo: configúralo en la pestaña 🧩 Parser y "
            "reabre el asistente.",
        "La checklist è informativa: il wizard NON attiva la "
        "modalità Reale (si passa dai gate della tab 🛡️ Sicurezza). "
        "Premi «Fine ✔» per salvare token/chat/CSV nella config.":
            "La checklist es informativa: el asistente NO activa el modo Real (eso pasa por "
            "los gates de la pestaña 🛡️ Seguridad). Pulsa «Finalizar ✔» para guardar "
            "token/chat/CSV en la config.",
        # Finestra Mapping — Dizionario nomi + mercati (#343 slice 4i; SOLO chrome:
        # titoli, colonne, pulsanti, hint, messaggi di stato/dialogo. Esclusi (restano IT,
        # value-as-key): sentinelle tendina, valori Sport/Tipo/Lingua/Mercato, tab del container.
        "Country (opz.)": "País (opc.)",
        "Betfair / XTrader": "Betfair / XTrader",
        "Come lo scrive il canale": "Como lo escribe el canal",
        "Sport": "Deporte",
        "Lingua": "Idioma",
        "Inizia dopo": "Empieza tras",
        "Finisce prima": "Termina antes",
        "Testo mercato": "Texto de mercado",
        "Mercato (catalogo)": "Mercado (catálogo)",
        "Selezione (catalogo)": "Selección (catálogo)",
        "🗺️  Dizionario nomi squadra": "🗺️  Diccionario de nombres de equipo",
        "🎯  Dizionario mercati": "🎯  Diccionario de mercados",
        "Dizionario nomi squadra": "Diccionario de nombres de equipo",
        "Dizionario mercati": "Diccionario de mercados",
        "Traduce i nomi squadra così come li scrive il canale nel nome atteso da Betfair/XTrader. Seleziona i profili nel Parser Personalizzato.": "Traduce los nombres de equipo tal como los escribe el canal al nombre esperado por Betfair/XTrader. Selecciona los perfiles en el Parser Personalizado.",
        "Legge il mercato da una posizione precisa del messaggio: «Inizia dopo» / «Finisce prima» (come nel Parser) ritagliano il campo, e se vi compare il «Testo mercato» imposta Mercato/Selezione dal Catalogo. Es.: Inizia dopo «Quota», Finisce prima «Prematch», Testo «0,5 HT». Seleziona i profili nel Parser Personalizzato.": "Lee el mercado desde una posición precisa del mensaje: «Empieza tras» / «Termina antes» (como en el Parser) recortan el campo, y si aparece el «Texto de mercado» fija Mercado/Selección del Catálogo. Ej.: Empieza tras «Quota», Termina antes «Prematch», Texto «0,5 HT». Selecciona los perfiles en el Parser Personalizado.",
        "Profilo:": "Perfil:",
        "✏️ Rinomina": "✏️ Renombrar",
        "Righe del profilo": "Filas del perfil",
        "➕ Aggiungi riga": "➕ Añadir fila",
        "📥 Precompila da Betfair": "📥 Rellenar desde Betfair",
        "💾 Salva profilo": "💾 Guardar perfil",
        "es. Quota": "ej. Quota",
        "es. Prematch": "ej. Prematch",
        "es. 0,5 HT": "ej. 0,5 HT",
        "Nessun profilo. Crea un profilo con «Nuovo».": "Ningún perfil. Crea uno con «Nuevo».",
        "Nome del nuovo profilo:": "Nombre del nuevo perfil:",
        "Nome del nuovo profilo mercati:": "Nombre del nuevo perfil de mercados:",
        "Nuovo profilo": "Nuevo perfil",
        "Nuovo nome per «{name}»:": "Nuevo nombre para «{name}»:",
        "Rinomina profilo": "Renombrar perfil",
        "⛔ Crea prima un profilo con «Nuovo».": "⛔ Crea primero un perfil con «Nuevo».",
        "⛔ Nessun profilo selezionato.": "⛔ Ningún perfil seleccionado.",
        "⛔ Profilo non creato (nome vuoto).": "⛔ Perfil no creado (nombre vacío).",
        "⛔ Rinomina annullata (nome vuoto).": "⛔ Renombrado cancelado (nombre vacío).",
        "⛔ Dizionario locale vuoto o non disponibile: popola prima il dizionario locale.": "⛔ Diccionario local vacío o no disponible: puebla primero el diccionario local.",
        "⏳ Dizionario occupato: riprova tra poco.": "⏳ Diccionario ocupado: reinténtalo en breve.",
        "❌ Nomi Betfair non leggibili: {kind}": "❌ Nombres de Betfair ilegibles: {kind}",
        "📥 Aggiunti {added} nomi Betfair (scrivi l'alias del canale in «Come lo scrive il canale»); {skipped} già presenti. Poi salva con 💾.": "📥 Añadidos {added} nombres de Betfair (escribe el alias del canal en «Como lo escribe el canal»); {skipped} ya presentes. Luego guarda con 💾.",
        "ℹ️ Nessun nuovo nome da aggiungere: ": "ℹ️ Ningún nombre nuevo que añadir: ",
        "i {skipped} nomi noti sono già in tabella.": "los {skipped} nombres conocidos ya están en la tabla.",
        "il dizionario locale è vuoto — popolalo prima.": "el diccionario local está vacío — puéblalo primero.",
        "💾 Profilo «{name}» salvato ({n} righe valide).": "💾 Perfil «{name}» guardado ({n} filas válidas).",
        "💾 Profilo «{name}» salvato ({n} regole valide).": "💾 Perfil «{name}» guardado ({n} reglas válidas).",
        "  ⚠️ {count} riga/e ignorata/e perché incomplete: servono Testo mercato, Mercato e Selezione.": "  ⚠️ {count} fila(s) ignorada(s) por incompletas: se necesitan Texto de mercado, Mercado y Selección.",
        "  ⚠️ {count} regola/e SENZA delimitatori: salvata/e ma non applicata/e finché non compili «Inizia dopo»/«Finisce prima».": "  ⚠️ {count} regla(s) SIN delimitadores: guardada(s) pero no aplicada(s) hasta que rellenes «Empieza tras»/«Termina antes».",
        "ℹ️ Il profilo «{name}» esiste già.": "ℹ️ El perfil «{name}» ya existe.",
        "ℹ️ Il profilo «{new}» esiste già.": "ℹ️ El perfil «{new}» ya existe.",
        "🆕 Profilo «{name}» creato.": "🆕 Perfil «{name}» creado.",
        "🗑 Profilo «{name}» eliminato.": "🗑 Perfil «{name}» eliminado.",
        "✏️ Profilo rinominato «{old}» → «{new}».": "✏️ Perfil renombrado «{old}» → «{new}».",
        "✏️ Profilo rinominato «{old}» → «{new}» · {count} parser aggiornati.": "✏️ Perfil renombrado «{old}» → «{new}» · {count} parsers actualizados.",
        "❌ Salvataggio FALLITO: «{name}» non creato.": "❌ Guardado FALLIDO: «{name}» no creado.",
        "❌ Salvataggio FALLITO: «{name}» non eliminato.": "❌ Guardado FALLIDO: «{name}» no eliminado.",
        "❌ Salvataggio FALLITO: rinomina non applicata.": "❌ Guardado FALLIDO: renombrado no aplicado.",
        "❌ Salvataggio FALLITO: cambio profilo annullato, modifiche mantenute a schermo. Controlla permessi/spazio del file config.": "❌ Guardado FALLIDO: cambio de perfil cancelado, cambios mantenidos en pantalla. Comprueba permisos/espacio del archivo config.",
        "⚠️ Profilo rinominato «{old}» → «{new}», ma {count} parser NON aggiornati ({names}): correggili a mano o quei segnali verranno scartati (MAPPING_MISSING).": "⚠️ Perfil renombrado «{old}» → «{new}», pero {count} parsers NO actualizados ({names}): corrígelos a mano o esas señales se descartarán (MAPPING_MISSING).",
        "⚠️ Profilo rinominato «{old}» → «{new}», ma {count} parser NON aggiornati ({names}): correggili a mano o quei segnali verranno scartati (MARKET_MAPPING_MISSING).": "⚠️ Perfil renombrado «{old}» → «{new}», pero {count} parsers NO actualizados ({names}): corrígelos a mano o esas señales se descartarán (MARKET_MAPPING_MISSING).",
        "⚠️ «{name}» eliminato, ma è ancora selezionato in {count} parser ({names}): quei segnali verranno scartati (MAPPING_MISSING) finché non togli il profilo da quei parser.": "⚠️ «{name}» eliminado, pero sigue seleccionado en {count} parsers ({names}): esas señales se descartarán (MAPPING_MISSING) hasta que quites el perfil de esos parsers.",
        "⚠️ «{name}» eliminato, ma è ancora selezionato in {count} parser ({names}): quei segnali verranno scartati (MARKET_MAPPING_MISSING) finché non togli il profilo da quei parser.": "⚠️ «{name}» eliminado, pero sigue seleccionado en {count} parsers ({names}): esas señales se descartarán (MARKET_MAPPING_MISSING) hasta que quites el perfil de esos parsers.",
        # Log di ciclo-vita del bridge (#343 slice 4j) — vedi nota nel blocco EN.
        "🚀 Bridge avviato!": "🚀 ¡Bridge iniciado!",
        "📄 CSV: {path}": "📄 CSV: {path}",
        "⏱️  Auto-clear dopo: {seconds}s": "⏱️  Auto-borrado tras: {seconds}s",
        "👂 In ascolto su Telegram...": "👂 Escuchando en Telegram...",
        "🛑 Bridge fermato.": "🛑 Bridge detenido.",
        "✅ Connesso a Telegram.": "✅ Conectado a Telegram.",
        "⏱️  Scadenza segnale tra ~{seconds}s": "⏱️  La señal expira en ~{seconds}s",
        "🗑️  CSV svuotato manualmente": "🗑️  CSV vaciado manualmente",
        # Log azioni utente CONFIG/CSV (#343 slice 4k) — vedi nota nel blocco EN.
        "💾 Configurazione salvata": "💾 Configuración guardada",
        "❌ CSV Path selezionato ma NON salvato: ": "❌ Ruta CSV seleccionada pero NO guardada: ",
        "📄 CSV Path aggiornato e salvato: {path}": "📄 Ruta CSV actualizada y guardada: {path}",
        "❌ Preferenza tema NON salvata: ": "❌ Preferencia de tema NO guardada: ",
        "🎨 Tema: chiaro": "🎨 Tema: claro",
        "🎨 Tema: scuro": "🎨 Tema: oscuro",
        "⚠️ «Crea CSV» annullato: il bridge è AVVIATO su questo CSV. Fai STOP prima di ricrearlo.": "⚠️ «Crear CSV» cancelado: el bridge está INICIADO en este CSV. Detén (STOP) antes de recrearlo.",
        "❌ «Crea CSV» fallito: impossibile creare {path} ({exc}).": "❌ «Crear CSV» fallido: no se puede crear {path} ({exc}).",
        "⚠️ «Crea CSV» annullato: {path} esiste e NON è un CSV del bridge (non sovrascritto).": "⚠️ «Crear CSV» cancelado: {path} existe y NO es un CSV del bridge (no sobrescrito).",
        "⚠️ «Crea CSV» annullato: {path} contiene un segnale attivo (non sovrascritto).": "⚠️ «Crear CSV» cancelado: {path} contiene una señal activa (no sobrescrito).",
        "📄 CSV creato (solo header) e impostato: {path}": "📄 CSV creado (solo cabecera) y establecido: {path}",
        "⚠️ «Crea CSV» annullato: bridge avviato su {path} (STOP prima).": "⚠️ «Crear CSV» cancelado: bridge iniciado en {path} (STOP antes).",
        "⚠️ «Crea CSV» annullato dall'utente: {path} non sovrascritto.": "⚠️ «Crear CSV» cancelado por el usuario: {path} no sobrescrito.",
        # Log AVVIO/VALIDAZIONE START (#343 slice 4l) — vedi nota nel blocco EN.
        "❌ python-telegram-bot non disponibile: impossibile avviare il listener.": "❌ python-telegram-bot no disponible: no se puede iniciar el listener.",
        "❌ Inserisci il Bot Token prima di avviare!": "❌ ¡Introduce el Bot Token antes de iniciar!",
        "❌ Impostazioni avanzate non valide (vedi avvisi sopra): correggile prima di avviare. Avvio annullato.": "❌ Ajustes avanzados no válidos (ver avisos arriba): corrígelos antes de iniciar. Inicio cancelado.",
        "❌ Nessuna chat configurata (Chat ID, parser per-chat o sorgente): il bridge accetterebbe segnali da QUALSIASI chat. Configura almeno una chat/sorgente. Avvio annullato.": "❌ Ninguna chat configurada (Chat ID, parser por chat o fuente): el bridge aceptaría señales de CUALQUIER chat. Configura al menos una chat/fuente. Inicio cancelado.",
        "❌ Nessun Parser Personalizzato configurato (globale o per-chat): il parser automatico è disattivato e il listener ignorerebbe OGNI segnale. Configura almeno un Parser Personalizzato prima di avviare (scheda 🧩 Parser). Avvio annullato.": "❌ Ningún Parser Personalizado configurado (global o por chat): el parser automático está desactivado y el listener ignoraría CADA señal. Configura al menos un Parser Personalizado antes de iniciar (pestaña 🧩 Parser). Inicio cancelado.",
        "❌ Sorgenti multi-chat: {err}": "❌ Fuentes multi-chat: {err}",
        "Avvio annullato: correggi le sorgenti.": "Inicio cancelado: corrige las fuentes.",
        "⏸️ Avvio automatico annullato: nessuna chat sorgente ATTIVA.": "⏸️ Inicio automático cancelado: ninguna chat fuente ACTIVA.",
        "⚠️ Nessuna chat sorgente ATTIVA: il listener parte ma NON processerà alcun segnale finché non attivi almeno una chat.": "⚠️ Ninguna chat fuente ACTIVA: el listener se inicia pero NO procesará ninguna señal hasta que actives al menos una chat.",
        "❌ La Chat notifiche XTrader coincide con una chat sorgente: cambiala (i segnali verrebbero scambiati per conferme). Avvio annullato.": "❌ La Chat de notificaciones XTrader coincide con una chat fuente: cámbiala (las señales se confundirían con confirmaciones). Inicio cancelado.",
        "⏸️ Avvio automatico in modalità reale annullato.": "⏸️ Inicio automático en modo real cancelado.",
        "▶️ Avvio automatico del listener (auto_start_listener attivo).": "▶️ Inicio automático del listener (auto_start_listener activo).",
        "⏸️ Avvio in modalità reale annullato.": "⏸️ Inicio en modo real cancelado.",
        "❌ {problem} Avvio annullato.": "❌ {problem} Inicio cancelado.",
        "❌ Impossibile inizializzare il CSV ({path}): {exc}. Avvio annullato.": "❌ No se puede inicializar el CSV ({path}): {exc}. Inicio cancelado.",
        # Log ESITO elaborazione messaggio/segnale (#343 slice 4m) — vedi nota nel blocco EN.
        "⏳ Messaggio ignorato: troppo vecchio (probabile arretrato dopo una disconnessione).": "⏳ Mensaje ignorado: demasiado antiguo (probablemente atrasado tras una desconexión).",
        "⚠️ Config live senza filtro chat: messaggio ignorato per sicurezza (configura chat/sorgenti, poi salva).": "⚠️ Config en vivo sin filtro de chat: mensaje ignorado por seguridad (configura chats/fuentes y luego guarda).",
        "❌ La Chat notifiche XTrader coincide con una sorgente ammessa: config ambigua, messaggio IGNORATO (né segnale né conferma). Correggi xtrader_notification_chat_id (dev'essere una chat separata).": "❌ La Chat de notificaciones XTrader coincide con una fuente permitida: config ambigua, mensaje IGNORADO (ni señal ni confirmación). Corrige xtrader_notification_chat_id (debe ser una chat separada).",
        "⚠️ Esito instradamento sconosciuto ({decision}): messaggio ignorato per sicurezza.": "⚠️ Resultado de enrutamiento desconocido ({decision}): mensaje ignorado por seguridad.",
        "⚠️ Segnale scartato ({source}/{status}): {detail}": "⚠️ Señal descartada ({source}/{status}): {detail}",
        "❌ Scrittura CSV fallita: {exc}. Segnale non registrato (riprovabile).": "❌ Escritura CSV fallida: {exc}. Señal no registrada (reintentable).",
        "🧾 Messaggio→CSV  |  msg: {msg}  |  riga: {row}": "🧾 Mensaje→CSV  |  msg: {msg}  |  fila: {row}",
        "❌ Aggiornamento CSV dopo conferma fallito: {exc}. Riprovo a breve.": "❌ Actualización del CSV tras confirmación fallida: {exc}. Reintento en breve.",
        "❌ Aggiornamento CSV alla scadenza fallito: {exc}. Riprovo a breve.": "❌ Actualización del CSV al vencimiento fallida: {exc}. Reintento en breve.",
        "🗑️  {n} segnale/i scaduto/i rimosso/i dal CSV": "🗑️  {n} señal(es) vencida(s) eliminada(s) del CSV",
        # Log RESILIENZA runtime (#343 slice 4n) — vedi nota nel blocco EN.
        "🔄 Riconnesso: i messaggi arrivati durante la disconnessione vengono recuperati (i troppo vecchi restano scartati per freschezza).": "🔄 Reconectado: los mensajes llegados durante la desconexión se recuperan (los demasiado antiguos se descartan por frescura).",
        "❌ Errore non recuperabile del listener: {exc}. Bridge fermato.": "❌ Error irrecuperable del listener: {exc}. Bridge detenido.",
        "🔌 Connessione persa ({error}): riconnessione tra {delay}s (tentativo {attempt})…": "🔌 Conexión perdida ({error}): reconexión en {delay}s (intento {attempt})…",
        "🧹 CSV ripulito al retry dopo lo STOP: {path}": "🧹 CSV limpiado en el reintento tras STOP: {path}",
        "🧹 Rimossi {count} file temporanei CSV orfani all'avvio.": "🧹 Eliminados {count} archivos temporales CSV huérfanos al inicio.",
        # Log LOG & DIAGNOSTICA (#343 slice 4o) — vedi nota nel blocco EN.
        "📂 Cartella log: {path}": "📂 Carpeta de logs: {path}",
        "❌ Impossibile aprire la cartella log: {exc}": "❌ No se puede abrir la carpeta de logs: {exc}",
        "🧾 Audit modalità reale esportato ({count} eventi): {path}": "🧾 Auditoría de modo real exportada ({count} eventos): {path}",
        "❌ Esportazione audit reale fallita: {exc}": "❌ Exportación de auditoría real fallida: {exc}",
        "📋 Diagnostica copiata negli appunti.": "📋 Diagnóstico copiado al portapapeles.",
        "❌ Copia diagnostica fallita: {exc}": "❌ Copia del diagnóstico fallida: {exc}",
        "❌ Retention log NON salvata. ": "❌ Retención de logs NO guardada. ",
        "🧹 Retention log: {days} giorni · {count} file vecchi rimossi.": "🧹 Retención de logs: {days} días · {count} archivos antiguos eliminados.",
        "🧹 Retention log: conservo tutto (nessuna pulizia automatica).": "🧹 Retención de logs: conservar todo (sin limpieza automática).",
        "🧹 Log svuotati: {count} file su disco rimossi; vista azzerata.": "🧹 Logs vaciados: {count} archivos eliminados del disco; vista restablecida.",
        "🐞 Modalità Debug log: {state}.": "🐞 Modo Debug del log: {state}.",
        "⚠️ Impostazione Debug NON salvata. ": "⚠️ Ajuste Debug NO guardado. ",
        "🧹 Retention log ({days}g): {count} file vecchi rimossi.": "🧹 Retención de logs ({days}d): {count} archivos antiguos eliminados.",
        # Log WIZARD + LINGUA-SELECTOR + PROFILO/SORGENTI (#343 slice 4p) — vedi nota nel blocco EN.
        "❌ Apertura wizard fallita: {exc}": "❌ Error al abrir el asistente: {exc}",
        "🧙 Wizard completato: configurazione salvata.": "🧙 Asistente completado: configuración guardada.",
        "🌐 Selettore lingua rimandato: auto-start attivo (imposta app_language in config.json, o disattiva l'auto-start).": "🌐 Selector de idioma pospuesto: auto-inicio activo (configura app_language en config.json, o desactiva el auto-inicio).",
        "⚠️ Lingua scelta ({lang}) ma salvataggio config FALLITO: nulla è cambiato (la sessione resta nella lingua precedente) e il selettore riapparirà al prossimo avvio — controlla permessi/spazio disco.": "⚠️ Idioma elegido ({lang}) pero guardado de config FALLIDO: no ha cambiado nada (la sesión permanece en el idioma anterior) y el selector reaparecerá en el próximo inicio — comprueba permisos/espacio en disco.",
        "⚠️ Scheda {tab} non aggiornata dal profilo (mostra ancora i valori precedenti): {exc}": "⚠️ Pestaña {tab} no actualizada desde el perfil (aún muestra los valores anteriores): {exc}",
        "📁 Profilo caricato e applicato (token invariato).": "📁 Perfil cargado y aplicado (token sin cambios).",
        "⚠️ Profilo applicato in memoria (token invariato), ma NON persistito. ": "⚠️ Perfil aplicado en memoria (token sin cambios), pero NO persistido. ",
        "📡 Sorgenti multi-chat aggiornate ({count}).": "📡 Fuentes multi-chat actualizadas ({count}).",
        # Log GUARDRAIL RUNTIME (#343 slice 4q) — vedi nota nel blocco EN.
        "⚠️ Stato anti-duplicato presente ma illeggibile: protezione dopo riavvio non garantita.": "⚠️ Estado anti-duplicados presente pero ilegible: protección tras reinicio no garantizada.",
        "🧮 Modalità coda: {mode}": "🧮 Modo de cola: {mode}",
        "⚠️ Impossibile salvare lo stato anti-duplicato su disco: protezione dopo riavvio degradata.": "⚠️ No se puede guardar el estado anti-duplicados en disco: protección tras reinicio degradada.",
        "⚠️ Impossibile salvare lo stato del limite giornaliero su disco: protezione anti-overtrading dopo riavvio degradata.": "⚠️ No se puede guardar el estado del límite diario en disco: protección anti-overtrading tras reinicio degradada.",
        # Log MODE-TRANSITION ANNULLATA (#343 slice 4r) — vedi nota nel blocco EN.
        "↩️ Attivazione modalità REALE ANNULLATA: torno a {old_mode}.": "↩️ Activación del modo REAL CANCELADA: vuelvo a {old_mode}.",
        "↩️ Attivazione modalità COLLAUDO ANNULLATA: torno a {old_mode}.": "↩️ Activación del modo PRUEBA CANCELADA: vuelvo a {old_mode}.",
        "↩️ Modalità coda multi-segnale ANNULLATA: resto a un solo segnale attivo (OVERWRITE_LAST).": "↩️ Modo de cola multi-señal CANCELADO: permanezco con una sola señal activa (OVERWRITE_LAST).",
        # NOMI MODALITÀ di trading (#343 slice 4s / Issue #45) — vedi nota nel blocco EN.
        "SIMULAZIONE": "SIMULACIÓN",
        "COLLAUDO": "PRUEBA",
        "REALE": "REAL",
        # Pannello «🧹 Nomi squadra noti» (#343 slice 4t) — vedi nota nel blocco EN.
        "🧹  Nomi squadra noti (permanenti) — ripulitura": "🧹  Nombres de equipo conocidos (permanentes) — limpieza",
        "Nomi squadra del dizionario locale, conservati per sempre. Elimina qui quelli obsoleti/errati (es. squadre retrocesse).": "Nombres de equipo del diccionario local, conservados para siempre. Elimina aquí los obsoletos/erróneos (p. ej. equipos descendidos).",
        "Sport": "Deporte",
        "🔄 Aggiorna": "🔄 Actualizar",
        "Nomi noti": "Nombres conocidos",
        "⛔ Provider del dizionario locale non disponibile.": "⛔ Proveedor del diccionario local no disponible.",
        "⏳ Dizionario occupato: riprova tra poco.": "⏳ Diccionario ocupado: reinténtalo en breve.",
        "⚠️ Errore lettura nomi: {exc}": "⚠️ Error al leer los nombres: {exc}",
        "{count} nomi noti.": "{count} nombres conocidos.",
        "🗑 Elimina": "🗑 Eliminar",
        "⛔ Eliminazione non disponibile.": "⛔ Eliminación no disponible.",
        "⚠️ Eliminazione fallita: {exc}": "⚠️ Eliminación fallida: {exc}",
        "⚠️ Eliminazione non riuscita: dizionario locale non disponibile.": "⚠️ Eliminación fallida: diccionario local no disponible.",
        # Pannello «📋 Riepilogo configurazione» (#343 slice 4u) — vedi nota nel blocco EN.
        "🔴 MODALITÀ REALE": "🔴 MODO REAL",
        "🧪 Simulazione (DRY_RUN)": "🧪 Simulación (DRY_RUN)",
        "Dizionario locale: presente": "Diccionario local: presente",
        "Dizionario locale: vuoto": "Diccionario local: vacío",
        "Nomi": "Nombres",
        "Mercati": "Mercados",
        "✅ Pronto": "✅ Listo",
        "(canale senza chat_id)": "(canal sin chat_id)",
        "Canali pronti: {ready}/{total}": "Canales listos: {ready}/{total}",
        "Nessun canale configurato (nessuna sorgente / chat).": "Ningún canal configurado (sin fuente / chat).",
        "📋 Riepilogo configurazione": "📋 Resumen de configuración",
        "Nessun dato di configurazione.": "Sin datos de configuración.",
        "⚠️ Impossibile leggere la configurazione:\n{exc}": "⚠️ No se puede leer la configuración:\n{exc}",
        # Pannello «🌳 Mapping guidato» — CHROME (#343 slice 4v) — vedi nota nel blocco EN.
        "🌳  Mapping guidato (Betfair → nome canale)": "🌳  Mapeo guiado (Betfair → nombre del canal)",
        "Scegli Sport → Competizione: compaiono le squadre dai dati Betfair presenti nel dizionario. Accanto a ogni squadra scrivi «come la chiama il canale» e salva nel profilo. Serve un dizionario locale popolato.": "Elige Deporte → Competición: aparecen los equipos de los datos Betfair presentes en el diccionario. Junto a cada equipo escribe «cómo lo llama el canal» y guarda en el perfil. Se necesita un diccionario local poblado.",
        "Competizione:": "Competición:",
        "Filtra squadre:": "Filtrar equipos:",
        "parte del nome squadra…": "parte del nombre del equipo…",
        "Pulisci": "Limpiar",
        "Squadra Betfair": "Equipo Betfair",
        "Come la chiama il canale": "Cómo lo llama el canal",
        "Squadre": "Equipos",
        "💾 Salva nel profilo": "💾 Guardar en el perfil",
        "Scegli Sport e Competizione per vedere le squadre.": "Elige Deporte y Competición para ver los equipos.",
        "come la chiama il canale…": "cómo lo llama el canal…",
        # Pannello «🌳 Mapping guidato» — MESSAGGI DI STATO (#343 slice 4w) — vedi nota nel blocco EN.
        "❌ Config illeggibile: {exc}": "❌ Config ilegible: {exc}",
        "⛔ Profilo non creato (nome vuoto).": "⛔ Perfil no creado (nombre vacío).",
        "ℹ️ Il profilo «{name}» esiste già.": "ℹ️ El perfil «{name}» ya existe.",
        "🆕 Profilo «{name}» creato.": "🆕 Perfil «{name}» creado.",
        "❌ Salvataggio FALLITO: «{name}» non creato.": "❌ Guardado FALLIDO: «{name}» no creado.",
        "ℹ️ Nessuna competizione per «{sport}». Popola il dizionario locale, poi riprova.": "ℹ️ Ninguna competición para «{sport}». Puebla el diccionario local y reinténtalo.",
        "ℹ️ Nessuna squadra per questa competizione (nessun evento nel dizionario). Popola il dizionario locale, poi riprova.": "ℹ️ Ningún equipo para esta competición (ningún evento en el diccionario). Puebla el diccionario local y reinténtalo.",
        "{count} squadre. Scrivi l'alias del canale e premi «Salva nel profilo».": "{count} equipos. Escribe el alias del canal y pulsa «Guardar en el perfil».",
        "… mostrate {shown} di {total} squadre: usa «Filtra» per restringere (gli alias già scritti restano salvati anche se non visibili).": "… mostrando {shown} de {total} equipos: usa «Filtrar» para acotar (los alias ya escritos permanecen guardados aunque no se vean).",
        "⛔ Nessun profilo selezionato: crea o scegli un profilo di destinazione.": "⛔ Ningún perfil seleccionado: crea o elige un perfil de destino.",
        "⛔ Nessuna squadra caricata da salvare.": "⛔ Ningún equipo cargado para guardar.",
        "💾 Salvato nel profilo «{profile}»: {written} squadre mappate in questa competizione ({total} righe totali nel profilo).": "💾 Guardado en el perfil «{profile}»: {written} equipos mapeados en esta competición ({total} filas totales en el perfil).",
        "❌ Salvataggio FALLITO: «{profile}» non salvato (andrebbe perso al riavvio). Controlla permessi/spazio del file config.": "❌ Guardado FALLIDO: «{profile}» no guardado (se perdería al reiniciar). Comprueba permisos/espacio del archivo config.",
    },
}
