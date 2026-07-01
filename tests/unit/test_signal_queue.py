"""Test della coda dei segnali attivi (PR-16/#2 residuo): modalità + timeout."""

import pytest

from xtrader_bridge import signal_queue as sq


def _row(name):
    return {"EventName": name, "SelectionName": "Sì", "Price": "1.85", "BetType": "PUNTA"}


def test_default_now_usa_monotonic():
    # audit A3: la scadenza coda è una decisione su TEMPO TRASCORSO e la coda è in-memory
    # (non persistita): il default `now` deve venire da time.monotonic(), NON dal wallclock,
    # così un salto NTP/VM-pause non fa scadere in anticipo un segnale ancora valido.
    import time
    q = sq.SignalQueue(default_timeout=60)
    q.add(_row("x"))
    added = q._active[0].added_at
    # monotonic (uptime, ~<10^7s) è enormemente più piccolo dell'epoch wallclock (~1.7e9).
    assert added < time.time() - 1_000_000
    assert abs(added - time.monotonic()) < 5


# ── modalità ─────────────────────────────────────────────────────────────────

def test_default_mode_overwrite_last():
    q = sq.SignalQueue()              # default OVERWRITE_LAST
    q.add(_row("A"), now=1000)
    q.add(_row("B"), now=1001)
    q.add(_row("C"), now=1002)
    rows = q.active_rows()
    assert len(rows) == 1             # un solo segnale attivo
    assert rows[0]["EventName"] == "C"


def test_active_rows_now_esclude_scaduti():
    # #30 (Codex): active_rows(now=...) NON deve esporre righe già oltre il loro timeout, così
    # una scrittura che non ha chiamato expire() subito prima (es. il flusso conferme) non
    # riscrive nel CSV un segnale scaduto. Lettura PURA: la coda NON viene mutata.
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE, default_timeout=10)
    q.add(_row("A"), signal_id="A", now=0)                 # scade a 10
    q.add(_row("B"), signal_id="B", now=5, timeout=100)    # scade a 105
    # now=15: A è scaduto, B ancora valido → solo B esposto
    assert [r["EventName"] for r in q.active_rows(now=15)] == ["B"]
    # back-compat: senza `now` ritorna TUTTE le attive (anche la scaduta non ancora rimossa)
    assert [r["EventName"] for r in q.active_rows()] == ["A", "B"]
    # active_rows(now=...) è una lettura pura: non muta la coda (la rimozione resta a expire())
    assert q.active_ids() == ["A", "B"]
    # un `now` non finito è rifiutato come altrove nella coda (fail-fast)
    with pytest.raises(ValueError):
        q.active_rows(now=float("nan"))


def test_append_active_tre_segnali_tre_righe():
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE)
    q.add(_row("A"), now=1000)
    q.add(_row("B"), now=1001)
    q.add(_row("C"), now=1002)
    rows = q.active_rows()
    assert [r["EventName"] for r in rows] == ["A", "B", "C"]    # 3 righe, in ordine


def test_mode_ignota_usa_default():
    assert sq.SignalQueue(mode="boh").mode == sq.OVERWRITE_LAST
    assert sq.normalize_mode("append_active") == sq.APPEND_ACTIVE


# ── timeout per singolo segnale ──────────────────────────────────────────────

def test_timeout_rimuove_solo_il_segnale_scaduto():
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE, default_timeout=90)
    id1 = q.add(_row("A"), now=1000)            # scade a 1090
    q.add(_row("B"), now=1050)                  # scade a 1140
    expired = q.expire(now=1100)                # solo A è scaduto
    assert expired == [id1]
    assert [r["EventName"] for r in q.active_rows()] == ["B"]


def test_timeout_per_segnale_personalizzato():
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE)
    q.add(_row("A"), now=1000, timeout=10)      # scade a 1010
    q.add(_row("B"), now=1000, timeout=300)     # scade a 1300
    assert q.expire(now=1011) and [r["EventName"] for r in q.active_rows()] == ["B"]


def test_nessun_segnale_scaduto_resta_attivo_per_sempre():
    # Anche QUEUE_UNTIL_CONFIRMED, se mai confermato, scade per timeout.
    q = sq.SignalQueue(mode=sq.QUEUE_UNTIL_CONFIRMED, default_timeout=90)
    q.add(_row("A"), now=1000)
    assert q.expire(now=1091) != []
    assert q.is_empty() is True


# ── conferma / rimozione ─────────────────────────────────────────────────────

def test_confirm_rimuove_solo_quel_segnale():
    q = sq.SignalQueue(mode=sq.QUEUE_UNTIL_CONFIRMED)
    id1 = q.add(_row("A"), now=1000)
    q.add(_row("B"), now=1001)
    assert q.confirm(id1) is True
    assert [r["EventName"] for r in q.active_rows()] == ["B"]
    assert q.confirm("inesistente") is False


def test_add_stesso_id_aggiorna_non_duplica():
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE)
    q.add(_row("A"), signal_id="x", now=1000)
    q.add(_row("A2"), signal_id="x", now=1001)   # stesso id → aggiorna
    rows = q.active_rows()
    assert len(rows) == 1
    assert rows[0]["EventName"] == "A2"


# ── sicurezza: copie difensive ───────────────────────────────────────────────

def test_id_generato_non_collide_con_id_esplicito():
    # Un id esplicito "s1" non deve essere sovrascritto dal primo id auto-generato.
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE)
    q.add(_row("A"), signal_id="s1", now=1000)
    gen = q.add(_row("B"), now=1001)              # auto-generato: deve evitare "s1"
    assert gen != "s1"
    assert [r["EventName"] for r in q.active_rows()] == ["A", "B"]


# ── validazione timeout (no segnali "immortali") ─────────────────────────────

def test_timeout_invalido_rifiutato():
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE)
    for bad in (0, -5, float("nan"), float("inf"), "abc", None):
        if bad is None:
            continue  # None significa "usa default", non è invalido
        with pytest.raises(ValueError):
            q.add(_row("A"), now=1000, timeout=bad)


def test_default_timeout_invalido_rifiutato_alla_costruzione():
    for bad in (0, -1, float("nan")):
        with pytest.raises(ValueError):
            sq.SignalQueue(default_timeout=bad)


def test_now_non_finito_rifiutato():
    # Un now NaN/inf salvato in added_at renderebbe il segnale "immortale".
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE)
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            q.add(_row("A"), now=bad)
    with pytest.raises(ValueError):
        q.expire(now=float("nan"))


def test_active_rows_sono_copie():
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE)
    q.add(_row("A"), now=1000)
    q.active_rows()[0]["EventName"] = "HACK"
    assert q.active_rows()[0]["EventName"] == "A"   # interno non mutato


# ── next_expiry / state / restore_state (PR-22 wiring) ───────────────────────

def test_next_expiry_e_la_scadenza_piu_vicina():
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE, default_timeout=90)
    assert q.next_expiry() is None                  # vuota → default None
    q.add(_row("A"), now=1000)                       # scade a 1090
    q.add(_row("B"), now=1080)                       # scade a 1170
    assert q.next_expiry() == 1090                   # la più vicina, non l'ultima


def test_delay_until_futuro_passato_e_adesso():
    # scadenza nel futuro → ritardo positivo
    assert sq.delay_until(1090, 1000) == 90
    assert sq.delay_until(1000.5, 1000) == 0.5
    # scadenza esatta o già passata → 0.0 (mai negativo: niente busy-loop / tick nel passato)
    assert sq.delay_until(1000, 1000) == 0.0
    assert sq.delay_until(990, 1000) == 0.0


def test_delay_until_si_compone_con_next_expiry():
    # uso reale: ritardo del prossimo tick = delay_until(next_expiry, now)
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE, default_timeout=90)
    q.add(_row("A"), now=1000)                       # scade a 1090
    assert sq.delay_until(q.next_expiry(), 1030) == 60


def test_state_restore_roundtrip_e_scadenza_preservata():
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE, default_timeout=90)
    q.add(_row("A"), now=1000)
    q.add(_row("B"), now=1010)
    snap = q.state()
    q2 = sq.SignalQueue(mode=sq.APPEND_ACTIVE, default_timeout=90)
    q2.restore_state(snap)
    assert [r["EventName"] for r in q2.active_rows()] == ["A", "B"]
    assert q2.next_expiry() == 1090
    assert q2.expire(now=1095) and [r["EventName"] for r in q2.active_rows()] == ["B"]


def test_restore_state_rollback_overwrite_last():
    # Caso reale (Codex #4): in OVERWRITE_LAST un add sostituisce il precedente; se la
    # scrittura fallisce, ripristinare lo snapshot riporta il segnale precedente.
    q = sq.SignalQueue(mode=sq.OVERWRITE_LAST, default_timeout=90)
    q.add(_row("VECCHIO"), now=1000)
    snap = q.state()
    q.add(_row("NUOVO"), now=1005)
    assert [r["EventName"] for r in q.active_rows()] == ["NUOVO"]
    q.restore_state(snap)
    assert [r["EventName"] for r in q.active_rows()] == ["VECCHIO"]
    assert q.next_expiry() == 1090                   # scadenza del precedente preservata


def test_restore_state_malformato_ignorato():
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE)
    for bad in (None, [{}], [{"signal_id": "x"}], [{"row": {}, "added_at": "n"}]):
        q.restore_state(bad)                         # non deve sollevare
    assert q.is_empty()


def test_pending_formato_per_confirmation_reader():
    # PR-23: pending() espone signal_id + i campi della riga, copie difensive.
    q = sq.SignalQueue(mode=sq.APPEND_ACTIVE)
    sid = q.add(_row("Inter v Milan"), now=1000)
    pend = q.pending()
    assert pend[0]["signal_id"] == sid
    assert pend[0]["EventName"] == "Inter v Milan"
    pend[0]["EventName"] = "HACK"                    # mutazione esterna
    assert q.active_rows()[0]["EventName"] == "Inter v Milan"   # interno intatto


def test_timeout_from_config_queue_until_confirmed_usa_confirmation_timeout():
    # PR-17b: solo in QUEUE_UNTIL_CONFIRMED il timeout per-segnale è confirmation_timeout.
    cfg = {"queue_mode": "QUEUE_UNTIL_CONFIRMED", "clear_delay": 90, "confirmation_timeout": 120}
    assert sq.timeout_from_config(cfg) == 120


def test_timeout_from_config_altre_modalita_usano_clear_delay():
    for mode in ("OVERWRITE_LAST", "APPEND_ACTIVE", "", "PINCO"):
        cfg = {"queue_mode": mode, "clear_delay": 75, "confirmation_timeout": 120}
        assert sq.timeout_from_config(cfg) == 75, mode


def test_timeout_from_config_valore_invalido_ricade_su_default():
    # Fail-safe: un timeout mancante/non valido NON deve rendere il segnale immortale.
    base = {"queue_mode": "QUEUE_UNTIL_CONFIRMED"}
    # True/False inclusi: float(True)==1.0 bypasserebbe il fail-safe (finding Codex P2).
    for bad in (None, "abc", 0, -5, float("inf"), float("nan"), True, False):
        cfg = dict(base, confirmation_timeout=bad)
        assert sq.timeout_from_config(cfg) == sq.DEFAULT_TIMEOUT, bad
    # Stessa cosa per clear_delay nelle altre modalità.
    assert sq.timeout_from_config({"queue_mode": "OVERWRITE_LAST", "clear_delay": "x"}) == sq.DEFAULT_TIMEOUT
    # Config vuota / non-dict → default.
    assert sq.timeout_from_config({}) == sq.DEFAULT_TIMEOUT
    assert sq.timeout_from_config(None) == sq.DEFAULT_TIMEOUT


def test_timeout_from_config_accetta_stringhe_numeriche():
    cfg = {"queue_mode": "QUEUE_UNTIL_CONFIRMED", "confirmation_timeout": "150"}
    assert sq.timeout_from_config(cfg) == 150


# ── Tetto righe attive simultanee (#136 punto 5) ──────────────────────────────

def test_max_active_blocca_il_nuovo_segnale_oltre_il_tetto():
    # APPEND con tetto 2: i primi due passano, il terzo NUOVO è bloccato (add → None).
    q = sq.SignalQueue(mode="APPEND_ACTIVE", default_timeout=60, max_active=2)
    assert q.add(_row("a"), now=1000) is not None
    assert q.add(_row("b"), now=1000) is not None
    assert q.add(_row("c"), now=1000) is None          # bloccato dal tetto
    assert len(q.active_rows()) == 2                    # coda invariata, solo 2 attivi


def test_max_active_non_blocca_l_aggiornamento_di_un_segnale_attivo():
    # Aggiornare un signal_id GIÀ attivo non conta come nuovo: non viene bloccato.
    q = sq.SignalQueue(mode="APPEND_ACTIVE", default_timeout=60, max_active=2)
    q.add(_row("a"), signal_id="s1", now=1000)
    q.add(_row("b"), signal_id="s2", now=1000)          # ora pieno (2/2)
    assert q.add(_row("a2"), signal_id="s1", now=1000) == "s1"   # update, non bloccato
    names = [r["EventName"] for r in q.active_rows()]
    assert len(names) == 2 and "a2" in names and "b" in names    # s1 aggiornato ad "a2"
    assert "a" not in names                                      # vecchio valore sostituito


def test_max_active_si_libera_dopo_expire():
    q = sq.SignalQueue(mode="APPEND_ACTIVE", default_timeout=60, max_active=1)
    assert q.add(_row("a"), now=1000) is not None
    assert q.add(_row("b"), now=1000) is None           # pieno (1/1)
    q.expire(now=1100)                                  # 'a' scade (1000+60 < 1100)
    assert q.add(_row("c"), now=1100) is not None       # slot liberato → passa
    assert len(q.active_rows()) == 1


def test_max_active_ininfluente_in_overwrite_last():
    # OVERWRITE_LAST tiene sempre 1 riga: il tetto non blocca mai (sostituisce).
    q = sq.SignalQueue(mode="OVERWRITE_LAST", default_timeout=60, max_active=1)
    assert q.add(_row("a"), now=1000) is not None
    assert q.add(_row("b"), now=1000) is not None       # sostituisce, non bloccato
    assert len(q.active_rows()) == 1
    assert q.active_rows()[0]["EventName"] == "b"


def test_max_active_zero_e_malformato_significano_illimitato():
    q0 = sq.SignalQueue(mode="APPEND_ACTIVE", default_timeout=60, max_active=0)
    for i in range(5):
        assert q0.add(_row(f"s{i}"), now=1000) is not None   # 0 = nessun tetto
    assert len(q0.active_rows()) == 5
    # Valori malformati → 0 (illimitato, fail-safe: non blocca per sbaglio).
    for bad in (-1, 1.5, float("nan"), float("inf"), True, "x", None):
        q = sq.SignalQueue(mode="APPEND_ACTIVE", default_timeout=60, max_active=bad)
        assert q.max_active == 0


def test_add_force_bypassa_il_tetto():
    # #192 (auto-raise, decisione proprietario): `force=True` accoda anche oltre il tetto
    # `max_active`, così il blocco coerente di un singolo messaggio multi non viene mai spezzato.
    q = sq.SignalQueue(mode="APPEND_ACTIVE", default_timeout=60, max_active=1)
    assert q.add(_row("a"), now=1000) is not None
    assert q.add(_row("b"), now=1000) is None                # senza force: bloccato dal tetto (1/1)
    assert q.add(_row("b"), now=1000, force=True) is not None  # con force: entra comunque
    assert q.add(_row("c"), now=1000, force=True) is not None
    names = [r["EventName"] for r in q.active_rows()]
    assert names == ["a", "b", "c"]                          # tutte attive (tetto scavalcato)


def test_add_force_in_overwrite_last_resta_una_sola_riga():
    # In OVERWRITE_LAST il tetto è già ininfluente: `force` non cambia la semantica (sostituisce).
    q = sq.SignalQueue(mode="OVERWRITE_LAST", default_timeout=60, max_active=1)
    q.add(_row("a"), now=1000)
    assert q.add(_row("b"), now=1000, force=True) is not None
    assert [r["EventName"] for r in q.active_rows()] == ["b"]
