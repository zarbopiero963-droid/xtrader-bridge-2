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


# ── i due rilievi dei reviewer (#171), misurati e pinnati ──────────────────────

def test_un_provider_che_fallisce_DOPO_non_riapre_la_finestra():
    """Rilievo Fugu Ultra (#171), marcato bloccante — e aveva ragione su un angolo che non
    avevo considerato.

    Il fail-safe iniziale degradava a «nessuna redazione» quando il provider sollevava. Ma il
    caso realistico non è «config sempre illeggibile»: è la **finestra di `os.replace`** di una
    scrittura config concorrente su Windows — per esempio l'utente che applica una proposta
    dell'assistente mentre un tool è in volo. In quell'istante il chat_id sarebbe uscito in
    chiaro.

    Ora il provider che fallisce ripiega sull'**ultimo elenco letto con successo**: gli ID
    cambiano di rado, quindi il valore in cache è quasi sempre ancora corretto — e comunque
    più protettivo di niente."""
    stato = {"rotto": False}

    def provider():
        if stato["rotto"]:
            raise OSError("config in scrittura (finestra di os.replace)")
        return (CHAT_SUPERGRUPPO,)

    reg = config_agent.ToolRegistry(chat_ids_provider=provider)
    reg.register(_tool("t", f"chat {CHAT_SUPERGRUPPO}"))

    # Primo giro: provider sano → l'ID viene redatto e memorizzato.
    assert CHAT_SUPERGRUPPO not in reg.dispatch("t", {}).content

    # La config diventa illeggibile a metà sessione.
    stato["rotto"] = True
    uscita = reg.dispatch("t", {}).content
    assert CHAT_SUPERGRUPPO not in uscita, (
        "la finestra di scrittura config non deve far uscire l'ID: si usa l'ultimo noto")


def test_senza_nessuna_lettura_riuscita_resta_ai_soli_segreti():
    """L'altro lato, dichiarato invece che nascosto: se il provider non ha **mai** avuto
    successo la cache è vuota e non c'è nulla da cui redigere. Si resta ai soli segreti — non
    si rifiuta il tool, sarebbe sproporzionato per una seconda rete."""
    reg = config_agent.ToolRegistry(chat_ids_provider=lambda: (_ for _ in ()).throw(OSError("ko")))
    reg.register(_tool("t", "nessun dato sensibile"))
    assert reg.dispatch("t", {}).content == "nessun dato sensibile"


@pytest.mark.parametrize("testo", [
    "99987654321000",             # l'ID corto è CONTENUTO in un numero più lungo
    "9876543210",                 # un numero più lungo che inizia uguale
    "quota 1.85, righe attive 3/5, timeout 90s",
    "MarketId 1.234567890",       # forma tipo Betfair
])
def test_un_id_corto_non_morde_dentro_numeri_piu_lunghi(testo):
    """Rilievo Fable 5 e Fugu Ultra (#171): un chat_id privato **corto** (9 cifre, senza il
    prefisso `-100` dei supergruppi) potrebbe over-redigere numeri legittimi — MarketId
    Betfair, quote, contatori — corrompendo proprio l'output diagnostico che l'assistente
    serve a produrre.

    `redact_chat_ids` usa confini numerici (#164), quindi non morde. Il test lo **pinna**:
    era una proprietà vera ma non verificata, e i reviewer hanno avuto ragione a chiederla."""
    reg = _registry([CHAT_PRIVATA])          # "987654321", 9 cifre, il caso peggiore
    reg.register(_tool("t", testo))
    assert reg.dispatch("t", {}).content == testo


def test_il_perimetro_del_provider_copre_tutte_le_fonti_di_chat(tmp_path):
    """Rilievo GPT-5.5 (#171): «se esistono chat ID in config non inclusi in
    `collect_chat_ids`, restano fuori dal perimetro». Giusto — ed è la forma di difetto che
    questa serie ha incontrato più volte.

    Misurato: le fonti sono cinque, e ci sono tutte. Incluse le **chiavi** dei dict
    `parser_by_chat`/`parser_list_by_chat`, che sono chat ID travestiti da chiavi e sono il
    posto più facile da dimenticare."""
    cfg = {
        "chat_id": "-1001111111111",
        "xtrader_notification_chat_id": "-1002222222222",
        "source_chats": [{"chat_id": "-1003333333333", "name": "A"}],
        "parser_by_chat": {"-1004444444444": "p1"},
        "parser_list_by_chat": {"-1005555555555": ["p1", "p2"]},
    }
    tutti = ["-1001111111111", "-1002222222222", "-1003333333333",
             "-1004444444444", "-1005555555555"]

    raccolti = diagnostics.collect_chat_ids(cfg)
    for atteso in tutti:
        assert atteso in raccolti, f"{atteso} fuori dal perimetro di collect_chat_ids"

    # E la garanzia end-to-end, non solo sulla funzione di raccolta.
    reg = config_agent.build_default_registry(config_loader=lambda *a, **k: dict(cfg),
                                              parsers_dir=str(tmp_path))
    reg.register(_tool("sonda", " ".join(tutti)))
    uscita = reg.dispatch("sonda", {}).content
    for atteso in tutti:
        assert atteso not in uscita, f"{atteso} uscito dal dispatcher"


# ── il contratto «iterabile» va onorato davvero (#171 round 2) ─────────────────

def test_un_provider_generatore_redige_gia_al_primo_giro():
    """Bloccante trovato da Claude Fable 5 e GPT-5.5 (#171), ed era un difetto della
    blindatura del round precedente — non del codice originale.

    Il contratto dichiara «iterabile», quindi un generatore è legittimo. Materializzando la
    cache con `tuple(chat_ids or ())` e poi redigendo con la variabile grezza, si passava a
    `redact_chat_ids` un iteratore **esaurito**: zero sostituzioni, in silenzio.

    Misurato, ed era peggio di come l'avevano descritto: non falliva solo al primo giro, ma a
    **ogni** dispatch — ogni chiamata crea un generatore nuovo, lo consuma nella cache e passa
    alla redazione quello vuoto. Con un provider-generatore la seconda rete non funzionava mai.

    La correzione legge sempre dalla tupla materializzata, in entrambi i percorsi: un solo
    valore, nessuna divergenza possibile."""
    def provider():
        yield CHAT_SUPERGRUPPO

    reg = config_agent.ToolRegistry(chat_ids_provider=provider)
    reg.register(_tool("t", f"chat {CHAT_SUPERGRUPPO}"))

    assert CHAT_SUPERGRUPPO not in reg.dispatch("t", {}).content, "primo giro"
    assert CHAT_SUPERGRUPPO not in reg.dispatch("t", {}).content, "giri successivi"


def test_un_generatore_che_poi_fallisce_continua_a_redigere():
    """La combinazione dei due difetti di questo round, chiesta esplicitamente da GPT-5.5:
    provider-generatore che riesce una volta e poi solleva. Entrambe le dispatch devono
    redigere — la prima dal generatore materializzato, la seconda dalla cache."""
    stato = {"rotto": False}

    def provider():
        if stato["rotto"]:
            raise OSError("config in scrittura")
        yield CHAT_SUPERGRUPPO

    reg = config_agent.ToolRegistry(chat_ids_provider=provider)
    reg.register(_tool("t", f"chat {CHAT_SUPERGRUPPO}"))

    assert CHAT_SUPERGRUPPO not in reg.dispatch("t", {}).content, "provider sano"
    stato["rotto"] = True
    assert CHAT_SUPERGRUPPO not in reg.dispatch("t", {}).content, "provider caduto → cache"


@pytest.mark.parametrize("forma", [
    lambda ids: list(ids), lambda ids: tuple(ids), lambda ids: set(ids),
    lambda ids: (x for x in ids), lambda ids: iter(ids),
])
def test_ogni_forma_di_iterabile_e_accettata(forma):
    """Il contratto è «iterabile»: lista, tupla, set, generatore e iteratore devono comportarsi
    tutti allo stesso modo. Parametrico perché il difetto sopra era invisibile con lista/tupla
    e totale con generatore/iteratore — esattamente il tipo di differenza che un test su una
    sola forma non prende."""
    reg = config_agent.ToolRegistry(chat_ids_provider=lambda: forma([CHAT_SUPERGRUPPO]))
    reg.register(_tool("t", f"chat {CHAT_SUPERGRUPPO}"))
    assert CHAT_SUPERGRUPPO not in reg.dispatch("t", {}).content


def test_nemmeno_una_redazione_che_solleva_rompe_l_assistente(monkeypatch):
    """Rilievo Fable 5 (#171, review sull'intera PR): `redact_chat_ids` era chiamata FUORI dal
    `try`. Se sollevasse, il dispatch crasherebbe — in contraddizione col contratto scritto nel
    docstring di `_safe_out` («la seconda rete non deve poter rompere l'assistente»).

    Oggi `redact_chat_ids` non solleva su nessun input anomalo (verificato con `None`, int,
    list, dict fra gli ID). Ma una garanzia che dipende dalla robustezza *attuale* di un'altra
    funzione non è una garanzia: è una coincidenza. Il test la rende **strutturale** simulando
    una regressione futura in `diagnostics`.

    L'esito atteso non è «nessuna eccezione» e basta: è che il testo torni comunque **con i
    segreti redatti**, cioè che la caduta della seconda rete non porti giù anche la prima."""
    from xtrader_bridge import event_log

    def redazione_rotta(text, chat_ids):
        raise RuntimeError("regressione futura in diagnostics")

    monkeypatch.setattr(config_agent.diagnostics, "redact_chat_ids", redazione_rotta)

    reg = _registry([CHAT_SUPERGRUPPO])
    event_log.register_secret(TOKEN_FINTO)
    try:
        reg.register(_tool("t", f"token {TOKEN_FINTO} e chat {CHAT_SUPERGRUPPO}"))
        uscita = reg.dispatch("t", {}).content          # non deve sollevare
        assert TOKEN_FINTO not in uscita, "la PRIMA rete deve reggere anche se cade la seconda"

        # Il ripiego è fail-CLOSED (rilievo convergente di Fugu Ultra, Fable 5 e GPT-5.5
        # #171): ritornare il testo con i soli segreti redatti lascerebbe l'ID in chiaro
        # PROPRIO nel percorso d'errore — contraddicendo lo scopo di questa rete. Avevo
        # inizialmente dichiarato il fail-open come scelta; avevano ragione loro.
        assert CHAT_SUPERGRUPPO not in uscita, (
            "il ripiego deve mascherare comunque l'ID: fail-closed, non fail-open")
        assert config_agent.MASKED_CHAT_FALLBACK in uscita, (
            "il segnaposto degradato dev'essere distinguibile dall'impronta normale")
    finally:
        event_log.clear_secrets()


# ── il ripiego fail-closed non deve fare danni (#171 round 5) ──────────────────

@pytest.mark.parametrize("ids", [("",), ("   ",), (None,), (None, "  ", "")])
def test_un_id_vuoto_non_inietta_il_segnaposto_ovunque(ids):
    """Rilievo Fugu Ultra (#171): senza la guardia `if valore`, `out.replace("", segnaposto)`
    inietterebbe il segnaposto **fra ogni carattere**, distruggendo l'output proprio nel
    percorso già degradato.

    Qui gli ID sono TUTTI vuoti/nulli, quindi il testo deve uscire identico: se la guardia
    saltasse, questo assert lo prende subito."""
    testo = "segnali 12, quota 1.85, righe 3/5"
    assert config_agent._crude_chat_mask(testo, ids) == testo


def test_un_id_vuoto_in_lista_non_impedisce_di_mascherare_quelli_validi():
    """L'altra metà, che il parametrico sopra NON copre: un ID vuoto **insieme** a uno valido.

    Il test precedente aveva un `if/else` in cui entrambi i rami asserivano la stessa cosa
    (rilievo Fable 5 #171) — quindi non verificava affatto il caso misto. Separato in due test
    che asseriscono cose diverse."""
    out = config_agent._crude_chat_mask(
        f"chat {CHAT_SUPERGRUPPO}", ("", None, "   ", CHAT_SUPERGRUPPO))
    assert CHAT_SUPERGRUPPO not in out
    assert config_agent.MASKED_CHAT_FALLBACK in out


def test_un_iterabile_difettoso_non_propaga_l_eccezione():
    """Rilievo GPT-5.5 e Fable 5 (#171), convergente: l'iterazione stessa era scoperta. Un
    `chat_ids` non iterabile, o un iteratore il cui `__next__` solleva, farebbe propagare
    l'eccezione — violando il contratto «non solleva mai» dell'ultima riga di difesa.

    Le due forme sono diverse e vanno provate entrambe: la prima fallisce sull'`iter()`, la
    seconda a metà ciclo (e lì il testo dev'essere già parzialmente mascherato)."""
    class NonIterabile:
        pass

    assert config_agent._crude_chat_mask("testo", NonIterabile()) == "testo"

    def iteratore_che_esplode():
        yield CHAT_SUPERGRUPPO
        raise RuntimeError("__next__ difettoso")

    out = config_agent._crude_chat_mask(f"chat {CHAT_SUPERGRUPPO}", iteratore_che_esplode())
    assert CHAT_SUPERGRUPPO not in out, "ciò che è stato mascherato prima dell'errore resta mascherato"


def test_un_testo_non_rappresentabile_non_solleva():
    """Terzo punto d'eccezione (GPT-5.5): `str(text)` era fuori da ogni guardia.

    Con un `__str__` difettoso si ritorna la stringa **vuota**, non il testo: fail-closed fino
    in fondo — se non si può nemmeno rappresentare il contenuto, non lo si emette."""
    class TestoVelenoso:
        def __str__(self):
            raise RuntimeError("__str__ difettoso")

    assert config_agent._crude_chat_mask(TestoVelenoso(), (CHAT_SUPERGRUPPO,)) == ""


def test_un_id_difettoso_non_ferma_il_mascheramento_degli_altri():
    """Rilievo Fable 5 (#171): con un solo `try` attorno al CICLO, un `cid` che solleva a metà
    interromperebbe tutto e lascerebbe in chiaro **tutti gli ID successivi** — un fail-open
    residuo dentro il ripiego fail-closed.

    La guardia è per elemento: quello difettoso salta da solo."""
    class CidVelenoso:
        def __str__(self):
            raise RuntimeError("__str__ difettoso")

    out = config_agent._crude_chat_mask(
        f"primo {CHAT_PRIVATA} poi {CHAT_SUPERGRUPPO}",
        (CHAT_PRIVATA, CidVelenoso(), CHAT_SUPERGRUPPO))

    assert CHAT_PRIVATA not in out, "l'ID prima di quello difettoso"
    assert CHAT_SUPERGRUPPO not in out, "l'ID DOPO quello difettoso: è il punto del test"


def test_nel_ripiego_i_segreti_restano_redatti_prima_degli_id():
    """Rilievo Fugu Ultra (#171): «va garantito che i segreti siano già redatti in `out` prima,
    altrimenti il fail-closed copre l'ID ma lascia trapelare segreti».

    L'ordine in `_safe_out` è: prima `redact_secrets`, poi il percorso chat_id (ripiego
    incluso). Il test lo verifica dall'esterno, sul risultato, invece di fidarsi dell'ordine
    delle righe: se un domani venissero invertite, qui diventa rosso."""
    from xtrader_bridge import event_log

    def redazione_rotta(text, chat_ids):
        raise RuntimeError("regressione futura")

    reg = _registry([CHAT_SUPERGRUPPO])
    event_log.register_secret(TOKEN_FINTO)
    try:
        import unittest.mock as mock
        with mock.patch.object(config_agent.diagnostics, "redact_chat_ids", redazione_rotta):
            reg.register(_tool("t", f"token {TOKEN_FINTO} chat {CHAT_SUPERGRUPPO}"))
            uscita = reg.dispatch("t", {}).content
        assert TOKEN_FINTO not in uscita, "i segreti devono essere già fuori quando parte il ripiego"
        assert CHAT_SUPERGRUPPO not in uscita, "e l'ID viene mascherato dal ripiego"
    finally:
        event_log.clear_secrets()
