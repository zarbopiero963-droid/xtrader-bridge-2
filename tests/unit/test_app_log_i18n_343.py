"""Test hard #343 slice 4j: localizzazione dei log di ciclo-vita del bridge in `app.py`.

Puro e headless (`app.py` importa customtkinter → non si costruisce la GUI: si legge il
sorgente e si esercita il catalogo i18n reale). Copre il gruppo di log runtime del bridge
localizzato in questa slice — START/STOP/connessione/ascolto/scadenza-segnale/svuotamento
manuale CSV — verificando:
- che ogni riga sia wrappata in `i18n.tr(...)` nel sorgente (niente regressione solo-IT);
- copertura piena EN/ES (niente log misto italiano per l'utente EN/ES);
- conservazione dei segnaposto `{path}`/`{seconds}` nelle traduzioni (un `.format(...)` con
  segnaposto diverso esploderebbe con KeyError a runtime);
- il round-trip reale `tr(template).format(...)`;
- che i log di DOMINIO risaliti dai layer puri (`bridge_mode.start_log_text`,
  `real_mode.*`, `config_store.save_status_message`, `outcome.*_log`, `warning`) NON siano
  wrappati né messi a catalogo: restano IT per contratto (contenuto di dominio).
"""

import os
import string

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
with open(os.path.join(_PKG, "app.py"), encoding="utf-8") as _fh:
    _APP_SRC = _fh.read()

# Gruppo lifecycle localizzato in questa slice (chiavi IT = chiavi del catalogo).
_LIFECYCLE_KEYS = (
    "🚀 Bridge avviato!",
    "📄 CSV: {path}",
    "⏱️  Auto-clear dopo: {seconds}s",
    "👂 In ascolto su Telegram...",
    "🛑 Bridge fermato.",
    "✅ Connesso a Telegram.",
    "⏱️  Scadenza segnale tra ~{seconds}s",
    "🗑️  CSV svuotato manualmente",
)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")     # stato di modulo: mai leak verso altri test


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_lifecycle_logs_wrappati_in_app():
    """Ogni log del gruppo passa da i18n.tr nel sorgente; i vecchi literal/f-string
    hardcoded non sopravvivono (un revert del wrap tornerebbe solo-IT anche in EN/ES)."""
    for key in _LIFECYCLE_KEYS:
        assert f'i18n.tr("{key}")' in _APP_SRC, f"wrap mancante per {key!r}"
    # I vecchi literal/f-string NON devono restare nel sorgente.
    for old in ('self._log("🚀 Bridge avviato!")',
                'self._log("🛑 Bridge fermato.")',
                'self._log("✅ Connesso a Telegram.")',
                'self._log("👂 In ascolto su Telegram...")',
                'self._log("🗑️  CSV svuotato manualmente")',
                'f"📄 CSV:', 'f"⏱️  Auto-clear dopo:', 'f"⏱️  Scadenza segnale tra'):
        assert old not in _APP_SRC, f"stringa non wrappata sopravvissuta: {old}"


def test_dynamic_logs_chiamano_format_in_app():
    """I 3 log DINAMICI devono chiamare `.format(...)` sull'argomento reale nel sorgente,
    non solo essere wrappati in `i18n.tr(...)`. Senza questa guardia, togliere il `.format`
    da un call-site lascerebbe passare la suite ma loggherebbe il template letterale
    `{path}`/`{seconds}` (CodeRabbit #32, Major)."""
    for site in ('i18n.tr("📄 CSV: {path}").format(path=cfg[\'csv_path\'])',
                 'i18n.tr("⏱️  Auto-clear dopo: {seconds}s").format(seconds=cfg[\'clear_delay\'])',
                 'i18n.tr("⏱️  Scadenza segnale tra ~{seconds}s").format(seconds=d)'):
        assert site in _APP_SRC, f"call-site .format mancante/alterato: {site}"


def test_lifecycle_logs_nel_catalogo_en_es():
    """Copertura piena EN/ES: nessun log del gruppo resta in italiano (niente log misto)."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _LIFECYCLE_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """`{path}`/`{seconds}` devono restare identici in EN/ES, altrimenti `.format(...)`
    darebbe KeyError a runtime nel percorso di logging."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _LIFECYCLE_KEYS:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_lifecycle():
    """Flusso reale: tr(template).format(...) → testo tradotto e interpolato, senza
    graffe residue; il marker emoji iniziale (usato da _log per classificare il livello)
    resta conservato in ogni lingua."""
    i18n.set_language("EN")
    assert i18n.tr("🚀 Bridge avviato!") == "🚀 Bridge started!"
    msg = i18n.tr("📄 CSV: {path}").format(path="/x/y.csv")
    assert msg == "📄 CSV: /x/y.csv" and "{" not in msg
    assert i18n.tr("⏱️  Auto-clear dopo: {seconds}s").format(seconds=30) == "⏱️  Auto-clear after: 30s"
    i18n.set_language("ES")
    assert i18n.tr("🛑 Bridge fermato.") == "🛑 Bridge detenido."
    assert i18n.tr("✅ Connesso a Telegram.") == "✅ Conectado a Telegram."
    assert i18n.tr("⏱️  Scadenza segnale tra ~{seconds}s").format(seconds=5) == "⏱️  La señal expira en ~5s"
    # fallback IT: template invariato, interpolazione corretta
    i18n.set_language("IT")
    assert i18n.tr("👂 In ascolto su Telegram...") == "👂 In ascolto su Telegram..."
    assert i18n.tr("📄 CSV: {path}").format(path="C:\\op.csv") == "📄 CSV: C:\\op.csv"
    # il marker che _log usa per il livello resta il primo carattere in ogni lingua
    for lang in ("EN", "ES"):
        i18n.set_language(lang)
        assert i18n.tr("🛑 Bridge fermato.").startswith("🛑"), lang
        assert i18n.tr("✅ Connesso a Telegram.").startswith("✅"), lang


def test_log_di_dominio_restano_it_non_wrappati():
    """I log che risalgono dai layer puri restano IT: NON wrappati, quindi le loro stringhe
    NON entrano nel catalogo. Guardia contro una localizzazione erronea del contenuto di
    dominio (che deve restare uniforme col resto del progetto)."""
    # i percorsi di dominio esistono ancora e restano non wrappati
    assert "self._log(bridge_mode.start_log_text(" in _APP_SRC
    for bad in ('i18n.tr(bridge_mode.start_log_text', 'i18n.tr(real_mode.enabled_message',
                'i18n.tr(warning)', 'i18n.tr(config_store.save_status_message'):
        assert bad not in _APP_SRC, f"contenuto di dominio wrappato per errore: {bad}"
