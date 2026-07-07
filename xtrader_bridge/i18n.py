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
        "💾  Salva": "💾  Save",
        "Niente salvato: correggi gli errori.": "Nothing saved: fix the errors.",
        "❌ Salvataggio su disco FALLITO: sorgenti NON salvate (andrebbero "
        "perse al riavvio). Controlla permessi/spazio del file config.":
            "❌ Disk save FAILED: sources NOT saved (would be lost on restart). "
            "Check config file permissions/space.",
        "✅ Salvate {n} sorgenti in config.json.":
            "✅ Saved {n} sources to config.json.",
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
        "💾  Salva": "💾  Guardar",
        "Niente salvato: correggi gli errori.": "Nada guardado: corrige los errores.",
        "❌ Salvataggio su disco FALLITO: sorgenti NON salvate (andrebbero "
        "perse al riavvio). Controlla permessi/spazio del file config.":
            "❌ Guardado en disco FALLIDO: orígenes NO guardados (se perderían al "
            "reiniciar). Comprueba permisos/espacio del archivo config.",
        "✅ Salvate {n} sorgenti in config.json.":
            "✅ Guardados {n} orígenes en config.json.",
    },
}
