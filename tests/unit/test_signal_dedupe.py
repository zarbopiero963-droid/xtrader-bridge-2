"""Test della deduplica e del limite/minuto del segnale (PR-15/#5)."""

from xtrader_bridge import signal_dedupe as sd


MSG = "🔔 P.Bet.\nInter v Milan\nMercato: GG\nQuota 1,85"


# ── message_hash ─────────────────────────────────────────────────────────────

def test_hash_stabile_e_normalizzato():
    # Stesso messaggio (anche con spaziatura diversa) → stesso hash.
    assert sd.message_hash("Inter v Milan") == sd.message_hash("  Inter   v  Milan  ")
    # Messaggi diversi → hash diversi.
    assert sd.message_hash("Inter v Milan") != sd.message_hash("Milan v Inter")


# ── deduplica ────────────────────────────────────────────────────────────────

def test_stesso_messaggio_due_volte_e_duplicato():
    t = sd.SignalTracker()
    assert t.register(MSG, now=1000).status == sd.NEW
    assert t.register(MSG, now=1001).status == sd.DUPLICATE


def test_due_segnali_diversi_stessa_partita_ammessi():
    # Stessa partita ma mercato/esito diversi → testo diverso → entrambi NEW.
    t = sd.SignalTracker()
    a = "Inter v Milan\nMercato: GG\nQuota 1,85"
    b = "Inter v Milan\nMercato: Over 2,5\nQuota 1,90"
    assert t.register(a, now=1000).status == sd.NEW
    assert t.register(b, now=1001).status == sd.NEW


def test_duplicato_scade_dopo_la_finestra():
    t = sd.SignalTracker(dedupe_window=300)
    assert t.register(MSG, now=1000).status == sd.NEW
    # oltre la finestra (300s) lo stesso messaggio è di nuovo NEW
    assert t.register(MSG, now=1000 + 301).status == sd.NEW


# ── limite al minuto ─────────────────────────────────────────────────────────

def test_limite_al_minuto():
    t = sd.SignalTracker(max_per_minute=20, dedupe_window=300)
    # 20 messaggi distinti nello stesso minuto → tutti NEW
    for i in range(20):
        assert t.register(f"segnale numero {i}", now=1000 + i).status == sd.NEW
    # il 21esimo nello stesso minuto → RATE_LIMITED
    assert t.register("segnale numero 20", now=1019).status == sd.RATE_LIMITED


def test_limite_non_aggirabile_con_finestra_dedup_corta():
    # Anche con dedupe_window < 60s il limite/minuto deve reggere: la storia per
    # il conteggio si conserva per 60s (max tra finestra e minuto).
    t = sd.SignalTracker(max_per_minute=20, dedupe_window=10)
    for i in range(20):
        assert t.register(f"segnale {i}", now=1000 + i).status == sd.NEW
    # il 21esimo entro il minuto è limitato, non NEW (niente bypass)
    assert t.register("segnale 20", now=1020).status == sd.RATE_LIMITED


def test_limite_si_libera_dopo_un_minuto():
    t = sd.SignalTracker(max_per_minute=2, dedupe_window=600)
    assert t.register("a", now=1000).status == sd.NEW
    assert t.register("b", now=1001).status == sd.NEW
    assert t.register("c", now=1002).status == sd.RATE_LIMITED   # 2/min raggiunto
    # passato un minuto dai primi, c'è di nuovo spazio
    assert t.register("d", now=1062).status == sd.NEW


def test_rate_limited_non_memorizzato_non_diventa_duplicato():
    t = sd.SignalTracker(max_per_minute=1, dedupe_window=600)
    assert t.register("a", now=1000).status == sd.NEW
    assert t.register("b", now=1001).status == sd.RATE_LIMITED
    # "b" non è stato memorizzato: dopo che si libera il minuto, è NEW (non duplicato)
    assert t.register("b", now=1062).status == sd.NEW


# ── persistenza: riconoscimento duplicati dopo un riavvio ────────────────────

def test_restart_riconosce_duplicati_recenti(tmp_path):
    path = str(tmp_path / "history.json")
    t1 = sd.SignalTracker()
    assert t1.register(MSG, now=1000).status == sd.NEW
    assert sd.save_state(t1, path) is True
    # "riavvio": nuovo tracker che ricarica lo stato
    t2 = sd.SignalTracker()
    assert sd.load_state(t2, path) is True
    assert t2.register(MSG, now=1002).status == sd.DUPLICATE


def test_save_state_atomico_non_lascia_tmp(tmp_path):
    path = str(tmp_path / "history.json")
    t = sd.SignalTracker()
    t.register(MSG, now=1000)
    assert sd.save_state(t, path) is True
    # scrittura atomica: nessun file .tmp residuo, history leggibile
    assert not (tmp_path / "history.json.tmp").exists()
    t2 = sd.SignalTracker()
    assert sd.load_state(t2, path) is True
    assert t2.register(MSG, now=1001).status == sd.DUPLICATE


def test_save_state_fallito_non_distrugge_history_esistente(tmp_path):
    # Una save riuscita crea la history; una save successiva verso un path non
    # scrivibile (dir inesistente trattata come file) fallisce ma non tocca il file ok.
    path = str(tmp_path / "history.json")
    t = sd.SignalTracker()
    t.register(MSG, now=1000)
    assert sd.save_state(t, path) is True
    before = (tmp_path / "history.json").read_text(encoding="utf-8")
    # path il cui "genitore" è un file → makedirs/replace falliscono → False
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    assert sd.save_state(t, str(blocker / "sub" / "history.json")) is False
    # la history originale è intatta
    assert (tmp_path / "history.json").read_text(encoding="utf-8") == before


def test_load_state_file_assente_lascia_invariato(tmp_path):
    t = sd.SignalTracker()
    assert sd.load_state(t, str(tmp_path / "manca.json")) is False
    assert t.register(MSG, now=1000).status == sd.NEW


def test_restore_state_tollera_voci_malformate():
    t = sd.SignalTracker()
    t.restore_state([["hashvalido", 1000], "rotta", [1, 2, 3], ["altro", "nan?"]])
    # solo la voce valida viene ripristinata
    assert t.state() == [["hashvalido", 1000.0]]
