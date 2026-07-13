"""Test hard #343 slice 4k: localizzazione dei log CONFIG/CSV user-action di `app.py`.

Puro e headless (`app.py` importa customtkinter → si legge il sorgente e si esercita il
catalogo i18n reale). Copre il gruppo di log delle azioni utente su configurazione e CSV —
salva config, tema chiaro/scuro, salva/crea/aggiorna il percorso CSV — verificando:
- wrapping in `i18n.tr(...)` nel sorgente (niente regressione solo-IT);
- che i log DINAMICI chiamino davvero `.format(...)` sull'argomento reale (togliere `.format`
  loggherebbe il template letterale `{path}`/`{exc}` — guardia esplicita);
- copertura piena EN/ES (niente log misto italiano);
- conservazione dei segnaposto `{path}`/`{exc}` nelle traduzioni;
- il round-trip reale `tr(template).format(...)`;
- le ESCLUSIONI: i messaggi di stato del layer puro (`config_store.save_status_message`) restano
  IT — qui si wrappa solo il PREFISSO; i log di recovery con `{quando}` (slice a parte) e i
  `on_mismatch` di dominio NON sono wrappati.
"""

import ast
import os
import string

import pytest

from xtrader_bridge import i18n

_PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "xtrader_bridge")
with open(os.path.join(_PKG, "app.py"), encoding="utf-8") as _fh:
    _APP_SRC = _fh.read()

# Costanti passate a `i18n.tr(...)` in app.py, estratte via AST: l'AST unisce le costanti
# multi-riga concatenate (`i18n.tr("… " "…")`) in UNA stringa, così i messaggi «Crea CSV»
# spezzati su più righe restano confrontabili verbatim col catalogo.
_APP_TR = set()
for _n in ast.walk(ast.parse(_APP_SRC)):
    if (isinstance(_n, ast.Call) and isinstance(_n.func, ast.Attribute)
            and _n.func.attr == "tr" and _n.args
            and isinstance(_n.args[0], ast.Constant) and isinstance(_n.args[0].value, str)):
        _APP_TR.add(_n.args[0].value)

# Gruppo CONFIG/CSV localizzato in questa slice (chiavi IT = chiavi del catalogo).
_CFG_CSV_KEYS = (
    "💾 Configurazione salvata",
    "❌ CSV Path selezionato ma NON salvato: ",
    "📄 CSV Path aggiornato e salvato: {path}",
    "❌ Preferenza tema NON salvata: ",
    "🎨 Tema: chiaro",
    "🎨 Tema: scuro",
    "⚠️ «Crea CSV» annullato: il bridge è AVVIATO su questo CSV. Fai STOP prima di ricrearlo.",
    "❌ «Crea CSV» fallito: impossibile creare {path} ({exc}).",
    "⚠️ «Crea CSV» annullato: {path} esiste e NON è un CSV del bridge (non sovrascritto).",
    "⚠️ «Crea CSV» annullato: {path} contiene un segnale attivo (non sovrascritto).",
    "📄 CSV creato (solo header) e impostato: {path}",
    "⚠️ «Crea CSV» annullato: bridge avviato su {path} (STOP prima).",
    "⚠️ «Crea CSV» annullato dall'utente: {path} non sovrascritto.",
)


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    yield
    i18n.set_language("IT")


def _placeholders(text) -> set:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def test_config_csv_logs_wrappati_in_app():
    """Ogni chiave del gruppo compare come costante di `i18n.tr(...)` nel sorgente (via AST,
    così le costanti multi-riga concatenate sono confrontate verbatim sulla stringa finale)."""
    for key in _CFG_CSV_KEYS:
        assert key in _APP_TR, f"chiave non wrappata in i18n.tr in app.py: {key!r}"
    # sanity: i marker di wrap chiave-per-chiave presenti come stringhe singole
    for probe in ('i18n.tr("💾 Configurazione salvata")',
                  'i18n.tr("🎨 Tema: chiaro")', 'i18n.tr("🎨 Tema: scuro")',
                  'i18n.tr("📄 CSV Path aggiornato e salvato: {path}")',
                  'i18n.tr("❌ CSV Path selezionato ma NON salvato: ")',
                  'i18n.tr("❌ Preferenza tema NON salvata: ")'):
        assert probe in _APP_SRC, f"wrap mancante: {probe}"
    # i vecchi literal/%-format/f-string NON devono sopravvivere
    for old in ('self._log("💾 Configurazione salvata")',
                'self._log(f"📄 CSV Path aggiornato e salvato:',
                '"📄 CSV creato (solo header) e impostato: %s"',
                '"⚠️ «Crea CSV» annullato dall\'utente: %s non sovrascritto."',
                '"🎨 Tema: " + ('):
        assert old not in _APP_SRC, f"stringa non wrappata sopravvissuta: {old}"


def test_dynamic_config_csv_logs_chiamano_format():
    """I log dinamici del gruppo devono chiamare `.format(...)` sull'argomento reale nel
    sorgente: togliere `.format` loggherebbe `{path}`/`{exc}` letterali (mutation-guard)."""
    for site in ('.format(path=dest)', '.format(path=path)',
                 '.format(path=path, exc=e)'):
        assert site in _APP_SRC, f"call-site .format mancante: {site}"
    # il messaggio con path+exc deve formattare ENTRAMBI i segnaposto
    assert 'i18n.tr("❌ «Crea CSV» fallito: impossibile creare {path} ({exc}).")' in _APP_SRC


def test_config_csv_logs_nel_catalogo_en_es():
    """Copertura piena EN/ES: nessun log del gruppo resta in italiano."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _CFG_CSV_KEYS:
            assert key in table, f"{lang}: manca la traduzione per {key!r}"
            assert table[key].strip(), f"{lang}: traduzione vuota per {key!r}"


def test_placeholder_conservati_nelle_traduzioni():
    """`{path}`/`{exc}` identici in EN/ES, altrimenti `.format(...)` darebbe KeyError."""
    for lang in ("EN", "ES"):
        table = i18n._CATALOG[lang]
        for key in _CFG_CSV_KEYS:
            attesi = _placeholders(key)
            if attesi:
                assert _placeholders(table[key]) == attesi, (
                    f"{lang}: segnaposto diversi in {key!r} → {table[key]!r}")


def test_format_round_trip_config_csv():
    """Flusso reale: tr(template).format(...) → testo tradotto e interpolato, senza graffe
    residue; marker emoji iniziale conservato (classificazione livello di `_log` invariata)."""
    i18n.set_language("EN")
    assert i18n.tr("💾 Configurazione salvata") == "💾 Configuration saved"
    assert i18n.tr("🎨 Tema: chiaro") == "🎨 Theme: light"
    msg = i18n.tr("📄 CSV creato (solo header) e impostato: {path}").format(path="/x/out.csv")
    assert msg == "📄 CSV created (header only) and set: /x/out.csv" and "{" not in msg
    msg = i18n.tr("❌ «Crea CSV» fallito: impossibile creare {path} ({exc}).").format(
        path="C:\\out.csv", exc="PermissionError")
    assert msg == "❌ «Create CSV» failed: cannot create C:\\out.csv (PermissionError)."
    i18n.set_language("ES")
    assert i18n.tr("🎨 Tema: scuro") == "🎨 Tema: oscuro"
    msg = i18n.tr("⚠️ «Crea CSV» annullato dall'utente: {path} non sovrascritto.").format(path="a.csv")
    assert msg == "⚠️ «Crear CSV» cancelado por el usuario: a.csv no sobrescrito."
    # fallback IT: template invariato
    i18n.set_language("IT")
    assert i18n.tr("💾 Configurazione salvata") == "💾 Configurazione salvata"
    # marker iniziale conservato in ogni lingua
    for lang in ("EN", "ES"):
        i18n.set_language(lang)
        assert i18n.tr("💾 Configurazione salvata").startswith("💾"), lang
        assert i18n.tr("❌ Preferenza tema NON salvata: ").startswith("❌"), lang


def test_esclusioni_dominio_e_quando_restano_it():
    """I messaggi di stato del layer puro e i log di recovery con `{quando}`/`on_mismatch`
    restano IT: il domain-content NON è wrappato (guardia contro over-localization)."""
    # solo il PREFISSO è wrappato; save_status_message resta concatenato fuori da i18n.tr
    assert 'i18n.tr("❌ CSV Path selezionato ma NON salvato: ")\n                      + config_store.save_status_message' in _APP_SRC
    for bad in ('i18n.tr("❌ " + config_store', 'i18n.tr(config_store.save_status_message',
                'i18n.tr(f"⚠️ {m}")', 'i18n.tr(f"🧹 CSV riportato a solo header',
                'i18n.tr(f"⚠️ Impossibile ripulire il CSV'):
        assert bad not in _APP_SRC, f"dominio/quando wrappato per errore: {bad}"
    # i log di recovery con {quando} restano f-string IT non wrappate
    assert 'f"🧹 CSV riportato a solo header {quando}: {path}"' in _APP_SRC
