"""#137 — la redazione dei chat_id deve stare nel DISPATCHER, non nei singoli tool.

Il finding dell'audit read-only pre-go-live: `ToolRegistry.dispatch` applica
`event_log.redact_secrets` a ogni contenuto uscente — quindi i **token** sono coperti — ma il
**chat_id** era redatto solo da `_redact_config`, chiamato da **un solo tool**
(`get_config_state`). Un tool futuro che se ne dimentica espone l'ID al modello.

Misurato prima di correggere, con un tool registrato apposta:

    "chat: -1001234567890 — token: [REDACTED_TOKEN]"
      token redatto?   True
      chat_id redatto? False   ← il buco

La correzione NON toglie `_redact_config`: resta la difesa di primo livello (redazione
strutturata del JSON di config). Il dispatcher è la **seconda rete**, quella che prende ciò
che il primo livello si è dimenticato.

Funzioni reali del progetto, nessuna chiamata live, nessun segreto vero."""

import pytest

from xtrader_bridge import config_agent, diagnostics

# ID di forma realistica ma inventati (supergruppo + chat privata).
CHAT_SUPERGRUPPO = "-1001234567890"
CHAT_PRIVATA = "987654321"
# Token dalla forma giusta, costruito a runtime così non esiste come letterale nel repo.
TOKEN_FINTO = "123456:" + "A" * 35


def _registry(chat_ids=()):
    """Registry con il provider iniettato, come lo costruisce l'app reale."""
    return config_agent.ToolRegistry(chat_ids_provider=lambda: tuple(chat_ids))


def _tool(nome, testo):
    return config_agent.AgentTool(
        name=nome, description="tool di prova", input_schema={},
        handler=lambda _inp: testo, permission=config_agent.READ_ONLY)


# ── il buco ────────────────────────────────────────────────────────────────────

def test_un_tool_distratto_non_puo_far_uscire_un_chat_id():
    """Il cuore del finding: un tool che NON chiama `_redact_config` non deve poter esporre
    l'ID. È la seconda rete — serve proprio perché il primo livello è per-tool e dimenticabile."""
    reg = _registry([CHAT_SUPERGRUPPO])
    reg.register(_tool("distratto", f"la chat configurata è {CHAT_SUPERGRUPPO}"))

    uscita = reg.dispatch("distratto", {}).content

    assert CHAT_SUPERGRUPPO not in uscita, uscita
    assert "chat:sha256:" in uscita, "l'ID va sostituito con l'impronta stabile, non cancellato"


def test_la_redazione_dei_segreti_non_regredisce():
    """Nessuna regressione sul livello che già funzionava: i token restano coperti, e lo
    restano ANCHE quando c'è un chat_id nello stesso testo (i due passaggi non si annullano)."""
    reg = _registry([CHAT_SUPERGRUPPO])
    from xtrader_bridge import event_log
    event_log.register_secret(TOKEN_FINTO)
    try:
        reg.register(_tool("misto", f"token {TOKEN_FINTO} e chat {CHAT_SUPERGRUPPO}"))
        uscita = reg.dispatch("misto", {}).content
        assert TOKEN_FINTO not in uscita, uscita
        assert CHAT_SUPERGRUPPO not in uscita, uscita
    finally:
        event_log.clear_secrets()


@pytest.mark.parametrize("chat", [CHAT_SUPERGRUPPO, CHAT_PRIVATA])
def test_vale_per_ogni_chat_configurata_non_solo_la_principale(chat):
    """Il provider deve coprire **tutte** le fonti (chat principale, notifiche XTrader,
    `source_chats`, chiavi di `parser_by_chat`…), non solo quella primaria — altrimenti il
    perimetro sarebbe incompleto, che è il modo tipico in cui una guardia sembra funzionare."""
    reg = _registry([CHAT_SUPERGRUPPO, CHAT_PRIVATA])
    reg.register(_tool("t", f"sorgente {chat}"))
    assert chat not in reg.dispatch("t", {}).content


# ── robustezza: la seconda rete non deve rompere l'assistente ──────────────────

def test_un_provider_che_solleva_non_rompe_l_assistente():
    """`dispatch` è l'unico punto da cui un tool viene eseguito: se il provider dei chat_id
    fallisce (config illeggibile, disco occupato) l'assistente deve continuare a funzionare
    con la redazione dei segreti, non crashare.

    È una degradazione **dichiarata**: la seconda rete cade, la prima (`_redact_config` nei
    tool che espongono config) regge. Per questo la riga sotto asserisce che il token resta
    comunque coperto — se cadesse anche quello sarebbe un fail-open vero."""
    def provider_rotto():
        raise OSError("config illeggibile")

    reg = config_agent.ToolRegistry(chat_ids_provider=provider_rotto)
    from xtrader_bridge import event_log
    event_log.register_secret(TOKEN_FINTO)
    try:
        reg.register(_tool("t", f"token {TOKEN_FINTO}"))
        uscita = reg.dispatch("t", {}).content
        assert TOKEN_FINTO not in uscita
    finally:
        event_log.clear_secrets()


def test_senza_provider_il_comportamento_resta_quello_di_prima():
    """Retrocompatibilità: `chat_ids_provider` è opzionale. Un registry costruito senza (test
    esistenti, usi di terze parti) non cambia comportamento e non solleva."""
    reg = config_agent.ToolRegistry()
    reg.register(_tool("t", "nessun dato sensibile"))
    assert reg.dispatch("t", {}).content == "nessun dato sensibile"


def test_un_output_legittimo_non_viene_storpiato():
    """La cautela che rende la redazione usabile: sostituisce solo gli ID **realmente
    configurati**, mai «i numeri che sembrano un id». Un output con contatori e quote deve
    restare leggibile, altrimenti l'assistente diventa inutile per diagnosticare."""
    reg = _registry([CHAT_SUPERGRUPPO])
    testo = "segnali oggi: 12, quota media 1.85, righe attive 3/5, timeout 90s"
    reg.register(_tool("t", testo))
    assert reg.dispatch("t", {}).content == testo


# ── il perimetro: anche i rifiuti passano dalla stessa uscita ──────────────────

def test_anche_i_messaggi_di_rifiuto_sono_redatti():
    """I messaggi di rifiuto interpolano il `name`, che è **controllato dal modello**. Passano
    già da `redact_secrets` (#62); devono passare dalla stessa uscita anche per i chat_id,
    altrimenti resta una porta laterale."""
    reg = _registry([CHAT_SUPERGRUPPO])
    uscita = reg.dispatch(f"tool_inesistente_{CHAT_SUPERGRUPPO}", {}).content
    assert CHAT_SUPERGRUPPO not in uscita, uscita


# ── il guard che conta: l'APP reale deve wirare il provider ────────────────────

def test_il_registry_dell_app_reale_wira_il_provider(tmp_path):
    """Il test più importante del file. La classe può essere corretta e l'app non usarla: è
    esattamente il modo in cui una guardia passa senza proteggere nulla.

    Qui si costruisce il registry **come fa l'app** (`build_default_registry`) con una config
    finta iniettata, e si verifica che un tool registrato a mano non riesca comunque a far
    uscire un ID presente in quella config."""
    cfg = {"chat_id": CHAT_SUPERGRUPPO, "xtrader_notification_chat_id": CHAT_PRIVATA}
    reg = config_agent.build_default_registry(config_loader=lambda *a, **k: dict(cfg),
                                              parsers_dir=str(tmp_path))
    reg.register(_tool("sonda", f"chat {CHAT_SUPERGRUPPO} e notifiche {CHAT_PRIVATA}"))

    uscita = reg.dispatch("sonda", {}).content
    assert CHAT_SUPERGRUPPO not in uscita, uscita
    assert CHAT_PRIVATA not in uscita, uscita


def test_collect_chat_ids_e_la_fonte_del_provider(tmp_path):
    """Ancoraggio alla fonte unica: il provider deve raccogliere gli ID con
    `diagnostics.collect_chat_ids`, la stessa funzione usata dal report diagnostico (#164) —
    non una lista scritta a mano che diverge alla prossima chiave di config aggiunta."""
    cfg = {"chat_id": CHAT_SUPERGRUPPO,
           "source_chats": [{"chat_id": CHAT_PRIVATA, "name": "Canale"}]}
    raccolti = diagnostics.collect_chat_ids(cfg)
    assert CHAT_SUPERGRUPPO in raccolti and CHAT_PRIVATA in raccolti

    reg = config_agent.build_default_registry(config_loader=lambda *a, **k: dict(cfg),
                                              parsers_dir=str(tmp_path))
    reg.register(_tool("sonda", f"{CHAT_SUPERGRUPPO} / {CHAT_PRIVATA}"))
    uscita = reg.dispatch("sonda", {}).content
    assert CHAT_SUPERGRUPPO not in uscita and CHAT_PRIVATA not in uscita, uscita
