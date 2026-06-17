"""Test della coda dei segnali attivi (PR-16/#2 residuo): modalità + timeout."""

import pytest

from xtrader_bridge import signal_queue as sq


def _row(name):
    return {"EventName": name, "SelectionName": "Sì", "Price": "1.85", "BetType": "PUNTA"}


# ── modalità ─────────────────────────────────────────────────────────────────

def test_default_mode_overwrite_last():
    q = sq.SignalQueue()              # default OVERWRITE_LAST
    q.add(_row("A"), now=1000)
    q.add(_row("B"), now=1001)
    q.add(_row("C"), now=1002)
    rows = q.active_rows()
    assert len(rows) == 1             # un solo segnale attivo
    assert rows[0]["EventName"] == "C"


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
