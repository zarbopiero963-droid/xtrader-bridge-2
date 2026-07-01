"""Test della deduplica e del limite/minuto del segnale (PR-15/#5)."""

import pytest

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
    # Voci: 2-elem legacy (→ real=True), stringa non-lista, lista troppo corta, timestamp non
    # numerico, 3-elem nuovo formato con flag shadow esplicito.
    t.restore_state([["hashvalido", 1000], "rotta", ["corta"], ["altro", "nan?"],
                     ["shadow", 1002, False]])
    # solo le voci valide vengono ripristinate (formato a 3 elementi [hash, ts, real])
    assert t.state() == [["hashvalido", 1000.0, True], ["shadow", 1002.0, False]]


def test_restore_state_scarta_timestamp_non_finiti():
    # #184 H4: un timestamp NON finito (NaN/inf, da state corrotto/manomesso) deve essere
    # scartato — altrimenti `inf >= cutoff` bloccherebbe l'hash come DUPLICATE per sempre,
    # e `-inf` indebolirebbe il rate-limit. Le voci valide restano.
    t = sd.SignalTracker()
    t.restore_state([
        ["buono", 1000],
        ["inf", float("inf")],
        ["ninf", float("-inf")],
        ["nan", float("nan")],
        ["buono2", 1001.5],
    ])
    assert t.state() == [["buono", 1000.0, True], ["buono2", 1001.5, True]]   # solo i finiti


def test_load_state_con_infinity_non_blocca_il_messaggio_per_sempre(tmp_path):
    # End-to-end: un dedupe_state.json manomesso con Infinity sull'hash di un messaggio
    # NON deve renderlo DUPLICATE per sempre. json.load accetta Infinity di default → la
    # voce arriva a restore_state come float('inf') e va scartata.
    import json
    p = tmp_path / "dedupe_state.json"
    h = sd.message_hash(MSG)
    with open(p, "w", encoding="utf-8") as f:
        json.dump([[h, float("inf")]], f)        # scrive "Infinity" (allow_nan default)
    t = sd.SignalTracker()
    assert sd.load_state(t, str(p)) is True       # file è una lista valida → caricato
    assert t.state() == []                        # la voce inf è stata scartata
    # quindi il messaggio NON è bloccato come duplicato stantio
    assert t.register(MSG, now=1000.0).status == sd.NEW


# ── audit #105 P2: validazione difensiva di parametri e timestamp ─────────────

def test_costruzione_rifiuta_parametri_non_validi():
    # dedupe_window / max_per_minute: bool, <=0, non-finiti, non-interi → ValueError
    # (un parametro malformato renderebbe deduplica/limite inefficaci o sempre bloccanti).
    for bad in (0, -1, True, False, 2.5, float("nan"), float("inf"), "x", None):
        with pytest.raises(ValueError):
            sd.SignalTracker(dedupe_window=bad)
        with pytest.raises(ValueError):
            sd.SignalTracker(max_per_minute=bad)
    # un float INTERO positivo è accettato (coerciti a int).
    t = sd.SignalTracker(dedupe_window=300.0, max_per_minute=20.0)
    assert t.dedupe_window == 300 and t.max_per_minute == 20


def test_register_rifiuta_now_non_finito_o_bool():
    t = sd.SignalTracker()
    for bad in (float("nan"), float("inf"), True, False, "x"):
        with pytest.raises(ValueError):
            t.register(MSG, now=bad)
    # now valido continua a funzionare.
    assert t.register(MSG, now=1000.0).status == sd.NEW


# ── load_state su file corrotto/non valido (audit, issue #106) ─────────────────

def test_load_state_json_malformato_ritorna_false(tmp_path):
    """Un file di stato con JSON malformato non deve crashare: `load_state` → False
    (lo stato resta vuoto, la protezione anti-duplicato riparte pulita)."""
    p = tmp_path / "history.json"
    p.write_text("{questo non e' json valido", encoding="utf-8")
    t = sd.SignalTracker()
    assert sd.load_state(t, str(p)) is False


def test_load_state_contenuto_non_lista_ritorna_false(tmp_path):
    """Stato valido come JSON ma del tipo sbagliato (oggetto/numero invece di lista)
    → `load_state` rifiuta e ritorna False, senza popolare lo stato."""
    for payload in ("{}", "123", '"stringa"', "null"):
        p = tmp_path / "history.json"
        p.write_text(payload, encoding="utf-8")
        t = sd.SignalTracker()
        assert sd.load_state(t, str(p)) is False, f"payload {payload!r} accettato per errore"


def test_load_state_lista_valida_ripristina(tmp_path):
    """Contro-prova: una lista valida salvata da `save_state` viene ricaricata (True)."""
    t1 = sd.SignalTracker()
    t1.register(MSG)
    p = tmp_path / "history.json"
    assert sd.save_state(t1, str(p)) is True
    t2 = sd.SignalTracker()
    assert sd.load_state(t2, str(p)) is True
    # il duplicato è riconosciuto dopo il ricarico
    assert t2.register(MSG).status == sd.DUPLICATE


# ── resilienza (#109 item 9): dedupe robusto al clock all'indietro (NTP step / VM resume) ──
# NB: la validazione di `now` (NaN/inf/bool/non-numerico, #109 item 30) è già coperta da
# `test_register_rifiuta_now_non_finito_o_bool` qui sopra — niente test duplicato.

def test_dedupe_robusto_a_clock_all_indietro():
    """#109 item 9: se il wallclock va INDIETRO (NTP step / VM resume), lo stesso messaggio
    entro la finestra resta DUPLICATO (non ri-piazzato), mentre un messaggio NUOVO passa."""
    t = sd.SignalTracker(dedupe_window=300, max_per_minute=100)
    assert t.register(MSG, now=1000).status == sd.NEW
    # clock indietro di 100s: lo stesso hash NON deve diventare un nuovo segnale
    assert t.register(MSG, now=900).status == sd.DUPLICATE
    # anche un salto indietro grande (oltre la finestra) resta fail-safe: non ri-piazza
    assert t.register(MSG, now=500).status == sd.DUPLICATE
    # un messaggio DIVERSO dopo lo step indietro è invece accettato
    assert t.register("altro segnale", now=900).status == sd.NEW


# ── #184 LOW: clock-skew — voci future preservate, limite forward documentato ──

def test_prune_non_elimina_le_voci_datate_nel_futuro():
    """#184 LOW: una voce con timestamp NEL FUTURO rispetto a `now` (clock saltato
    indietro) NON deve essere eliminata da `_prune`: è valida e protegge dai duplicati.
    Avrebbe i denti — se `_prune` aggiungesse un limite superiore `t <= now`, fallirebbe."""
    t = sd.SignalTracker(dedupe_window=300, max_per_minute=100)
    # voce registrata "nel futuro" (now più piccolo per skew all'indietro)
    t._seen = [("hash_futuro", 5000.0, True)]
    t._prune(now=1000.0)                          # now << timestamp memorizzato
    assert ("hash_futuro", 5000.0, True) in t._seen   # NON pruneata


def test_clock_indietro_voce_futura_blocca_ancora_il_duplicato():
    """Scenario reale: segnale registrato a now=5000, poi l'orologio salta INDIETRO a
    now=1000; la voce (futura rispetto al nuovo now) resta e il duplicato è bloccato —
    nessuna doppia scommessa."""
    t = sd.SignalTracker(dedupe_window=300, max_per_minute=100)
    assert t.register(MSG, now=5000).status == sd.NEW
    # un altro register fa scattare _prune col now più piccolo: la voce futura sopravvive
    assert t.register("altro", now=1000).status == sd.NEW
    assert t.register(MSG, now=1001).status == sd.DUPLICATE      # duplicato ancora bloccato


def test_clock_in_avanti_e_finestra_transitoria_documentata():
    """Caratterizza il LIMITE INERENTE documentato: un salto in AVANTI invecchia di colpo
    le voci, che escono dalla finestra; un duplicato dopo il salto è riaccettato come NEW.
    Non è un fix (inerente alla persistenza wall-clock), ma il comportamento è fissato qui
    così un'eventuale modifica futura è intenzionale e non silenziosa."""
    t = sd.SignalTracker(dedupe_window=300, max_per_minute=100)
    assert t.register(MSG, now=1000).status == sd.NEW
    # salto in avanti molto oltre la finestra (300s): la voce è invecchiata ed esce
    assert t.register(MSG, now=1000 + 10_000).status == sd.NEW


# ── #192 kyW: mark_seen (dedup cross-namespace) ──────────────────────────────

def test_mark_seen_blocca_duplicato_ma_non_conta_verso_il_rate_limit():
    """#192 kyW: `mark_seen` marca una chiave come vista ai soli fini di dedup, SENZA consumare
    capacità del limite/minuto. Con `max_per_minute=2`, un segnale reale + N marcatori shadow non
    devono far scattare RATE_LIMITED su un secondo segnale reale distinto."""
    t = sd.SignalTracker(dedupe_window=300, max_per_minute=2)
    assert t.register("msg-reale-1", now=1000).status == sd.NEW      # 1 reale
    for i in range(5):                                               # 5 shadow: NON contano
        t.mark_seen(f"shadow-{i}", now=1000)
    # secondo segnale reale distinto: reali nell'ultimo minuto = 1 (<2) → NEW, non RATE_LIMITED
    assert t.register("msg-reale-2", now=1001).status == sd.NEW
    # la chiave shadow è però riconosciuta come DUPLICATE (dedup cross-namespace)
    assert t.register("qualsiasi", now=1002, key="shadow-3").status == sd.DUPLICATE


def test_mark_seen_noop_se_gia_visto():
    """`mark_seen` è idempotente e non declassa una registrazione reale a shadow."""
    t = sd.SignalTracker()
    t.register("m", now=1000)                                        # reale
    real_key = sd.message_hash("m")
    t.mark_seen(real_key, now=1001)                                  # già presente (reale) → no-op
    t.mark_seen("nuova", now=1002)
    t.mark_seen("nuova", now=1003)                                   # seconda volta → no-op
    keys = [h for (h, _t, _r) in t._seen]
    assert keys.count(real_key) == 1 and keys.count("nuova") == 1
    # la voce reale resta reale (True), la shadow resta shadow (False)
    flags = {h: r for (h, _t, r) in t._seen}
    assert flags[real_key] is True and flags["nuova"] is False


def test_mark_seen_shadow_sopravvive_al_riavvio():
    """La distinzione reale/shadow è persistita: una shadow ripristinata da stato continua a
    bloccare i duplicati (dedup) ma NON conta verso il rate-limit."""
    t = sd.SignalTracker(dedupe_window=300, max_per_minute=1)
    t.mark_seen("shadow-persistita", now=1000)
    t2 = sd.SignalTracker(dedupe_window=300, max_per_minute=1)
    t2.restore_state(t.state())
    # dedup: la shadow blocca il duplicato…
    assert t2.register("x", now=1001, key="shadow-persistita").status == sd.DUPLICATE
    # …ma non ha consumato il tetto/minuto: un segnale reale distinto passa (reali=0 <1)
    assert t2.register("reale-nuovo", now=1002).status == sd.NEW


def test_mark_seen_rinfresca_marcatore_fuori_finestra():
    """#192 kyW (Codex): con `dedupe_window < 60s` una chiave resta in `_seen` (conservata per il
    rate-limit) anche dopo essere uscita dalla finestra di dedup. Una successiva `mark_seen` sulla
    stessa chiave, ormai FUORI finestra, deve RINFRESCARLA — altrimenti una transizione di modalità
    subito dopo la vedrebbe come NEW e il duplicato che questa patch blocca sfuggirebbe."""
    t = sd.SignalTracker(dedupe_window=30, max_per_minute=100)
    t.mark_seen("S", now=0)                          # primo shadow a t=0
    # a t=40 "S" è fuori dalla finestra dedup (30) ma ancora presente in _seen (prune tiene 60s):
    t.mark_seen("S", now=40)                         # deve RINFRESCARE, non essere un no-op
    # ora "S" è di nuovo in finestra → un retry cross-namespace è DUPLICATE (niente doppia scommessa)
    assert t.register("z", now=41, key="S").status == sd.DUPLICATE


def test_restore_state_scarta_voce_dict_senza_crash():
    """#192 kyW (Codex): una voce OGGETTO in `dedupe_state.json` (es. `[{}]` da manomissione) non
    deve far crashare il ripristino (`item[0]` su un dict → KeyError). Va SCARTATA come le altre
    voci malformate, lasciando il tracker con solo le voci valide — lo START non deve crashare."""
    t = sd.SignalTracker()
    t.restore_state([{}, {"x": 1}, ["buono", 1000], "rotta"])
    assert t.state() == [["buono", 1000.0, True]]
