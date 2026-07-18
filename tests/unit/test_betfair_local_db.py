"""Test hard del dizionario Betfair locale (issue #86 PR-P5).

Esercita la logica reale su un DB SQLite in memoria. Copre i casi richiesti
dall'issue: upsert non duplica; stesso nome squadra in eventi diversi non scartato;
selection_id uguale in market diversi senza conflitto; record non più visti →
active=0. Tutto locale, nessun cloud/export.
"""

import pytest

from xtrader_bridge.betfair.local_db import BetfairLocalDB, _norm_handicap


@pytest.fixture()
def db():
    d = BetfairLocalDB(":memory:")
    yield d
    d.close()


# ── upsert non duplica ────────────────────────────────────────────────────────

def test_upsert_sport_non_duplica(db):
    db.upsert_sport("1", "Calcio", seen_at=1)
    db.upsert_sport("1", "Calcio (agg.)", seen_at=2)   # stesso event_type_id
    rows = db.fetchall("betfair_sports")
    assert len(rows) == 1
    assert rows[0]["name"] == "Calcio (agg.)"          # aggiornato, non duplicato


def test_upsert_market_non_duplica(db):
    db.upsert_market("1.23", "ev1", "1", "Match Odds", "MATCH_ODDS", seen_at=1)
    db.upsert_market("1.23", "ev1", "1", "Esito Finale", "MATCH_ODDS", seen_at=2)
    assert db.count_active("betfair_markets") == 1


# ── stesso nome squadra in eventi diversi NON viene scartato ──────────────────

def test_stesso_nome_in_eventi_diversi_non_scartato(db):
    # Due eventi diversi (event_id diverso) con lo stesso nome: entrambi presenti.
    db.upsert_event("ev1", "1", "compA", "Inter v Milan", seen_at=1)
    db.upsert_event("ev2", "1", "compB", "Inter v Milan", seen_at=1)
    events = db.get_events()
    assert len(events) == 2
    assert {e["event_id"] for e in events} == {"ev1", "ev2"}


# ── selection_id uguale in market diversi: nessun conflitto ───────────────────

def test_selection_id_uguale_in_market_diversi_nessun_conflitto(db):
    # Stesso selection_id (47972) in due market diversi → due righe distinte.
    db.upsert_selection("1.10", "47972", "Inter", seen_at=1)
    db.upsert_selection("1.20", "47972", "Inter", seen_at=1)
    assert db.count_active("betfair_selections") == 2
    assert len(db.get_selections("1.10")) == 1
    assert len(db.get_selections("1.20")) == 1


def test_selezione_chiave_include_handicap(db):
    # Stesso market+selection ma handicap diverso → due selezioni (es. linee Asian).
    db.upsert_selection("1.10", "47972", "Over", handicap=2.5, seen_at=1)
    db.upsert_selection("1.10", "47972", "Over", handicap=3.5, seen_at=1)
    assert db.count_active("betfair_selections") == 2
    # stesso handicap → upsert, non duplica
    db.upsert_selection("1.10", "47972", "Over (agg)", handicap=2.5, seen_at=2)
    assert db.count_active("betfair_selections") == 2


def test_norm_handicap():
    assert _norm_handicap(None) == 0.0
    assert _norm_handicap("") == 0.0
    assert _norm_handicap("2.5") == 2.5
    # P3-21 #76: il non-numerico NON è più coercito a 0.0 (collisione di PK con la
    # selezione legittima a handicap 0) → sentinella None, il chiamante scarta.
    assert _norm_handicap("x") is None


# ── record non più visti diventano inattivi ───────────────────────────────────

def test_deactivate_unseen_marca_inactive_i_non_visti(db):
    db.upsert_event("ev1", "1", "c", "A v B", seen_at=10)
    db.upsert_event("ev2", "1", "c", "C v D", seen_at=10)
    # nuova sync (seen_at=20) rivede solo ev1
    db.upsert_event("ev1", "1", "c", "A v B", seen_at=20)
    n = db.deactivate_unseen("betfair_events", seen_at=20)
    assert n == 1                                   # ev2 disattivato
    assert db.count_active("betfair_events") == 1   # solo ev1 attivo


def test_deactivate_unseen_scope_per_sport(db):
    # Sync del solo Calcio (event_type_id=1) non deve disattivare eventi del Tennis (2).
    db.upsert_event("calcio1", "1", "c", "A v B", seen_at=10)
    db.upsert_event("tennis1", "2", "c", "X v Y", seen_at=10)
    # nuova sync vede solo calcio (nuovo evento), scope sul Calcio
    db.upsert_event("calcio2", "1", "c", "C v D", seen_at=20)
    db.deactivate_unseen("betfair_events", seen_at=20, scope_value="1")
    rows = {e["event_id"]: e["active"] for e in db.get_events()}
    assert rows["calcio1"] == 0     # non rivisto nel suo sport → inattivo
    assert rows["calcio2"] == 1     # rivisto
    assert rows["tennis1"] == 1     # altro sport: intatto


def test_riattivazione_se_ricompare(db):
    db.upsert_event("ev1", "1", "c", "A v B", seen_at=10)
    db.deactivate_unseen("betfair_events", seen_at=20)   # ev1 non rivisto → inactive
    assert db.count_active("betfair_events") == 0
    db.upsert_event("ev1", "1", "c", "A v B", seen_at=30)  # ricompare
    assert db.count_active("betfair_events") == 1          # riattivato


def test_deactivate_unseen_tabella_non_valida(db):
    with pytest.raises(ValueError):
        db.deactivate_unseen("sqlite_master", seen_at=1)


def test_deactivate_sports_scoped_non_tocca_altri_sport(db):
    # Sync del solo Calcio (event_type_id=1) non deve disattivare il Tennis (2).
    db.upsert_sport("1", "Calcio", seen_at=10)
    db.upsert_sport("2", "Tennis", seen_at=10)
    m = db.new_sync_marker()
    db.upsert_sport("1", "Calcio", seen_at=m)          # solo Calcio rivisto
    db.deactivate_unseen("betfair_sports", seen_at=m, scope_value="1")
    rows = {r["event_type_id"]: r["active"] for r in db.fetchall("betfair_sports")}
    assert rows["1"] == 1     # rivisto nello scope → resta attivo
    assert rows["2"] == 1     # altro sport fuori scope → intatto (non disattivato)


def test_deactivate_sports_scoped_disattiva_lo_sport_stantio(db):
    # Se lo sport nello scope NON viene rivisto, va disattivato (solo lui).
    db.upsert_sport("1", "Calcio", seen_at=10)
    db.upsert_sport("2", "Tennis", seen_at=10)
    db.deactivate_unseen("betfair_sports", seen_at=20, scope_value="1")
    rows = {r["event_type_id"]: r["active"] for r in db.fetchall("betfair_sports")}
    assert rows["1"] == 0     # Calcio non rivisto nello scope → inattivo
    assert rows["2"] == 1     # Tennis intatto


# ── sync run + name mapping locali ────────────────────────────────────────────

def test_record_sync_run(db):
    rid = db.record_sync_run(started_at=100, finished_at=200, status="OK",
                             summary="2 eventi")
    assert isinstance(rid, int)
    runs = db.fetchall("betfair_sync_runs")
    assert len(runs) == 1 and runs[0]["status"] == "OK"


# ── marker di sync unico/monotòno (Codex P2) ──────────────────────────────────

def test_new_sync_marker_strettamente_crescente(db):
    m1 = db.new_sync_marker()
    m2 = db.new_sync_marker()
    m3 = db.new_sync_marker()
    assert m1 < m2 < m3


def test_marker_unico_disattiva_run_precedente_anche_stesso_istante(db):
    # Regressione Codex: due run "nello stesso secondo" non devono condividere il
    # marker. Usando new_sync_marker() i marker sono distinti → la deattivazione
    # dei non-rivisti funziona comunque.
    m1 = db.new_sync_marker()
    db.upsert_event("ev1", "1", "c", "A v B", seen_at=m1)
    db.upsert_event("ev2", "1", "c", "C v D", seen_at=m1)
    m2 = db.new_sync_marker()
    assert m2 > m1
    db.upsert_event("ev1", "1", "c", "A v B", seen_at=m2)   # solo ev1 rivisto
    db.deactivate_unseen("betfair_events", seen_at=m2)
    rows = {e["event_id"]: e["active"] for e in db.get_events()}
    assert rows["ev1"] == 1
    assert rows["ev2"] == 0                                   # run precedente disattivata


def test_marker_persiste_dopo_riapertura(tmp_path):
    path = str(tmp_path / "sub" / "betfair.db")   # sub/ non esiste ancora
    d1 = BetfairLocalDB(path)
    m1 = d1.new_sync_marker()
    d1.close()
    d2 = BetfairLocalDB(path)        # riapertura
    m2 = d2.new_sync_marker()
    d2.close()
    assert m2 > m1                   # il contatore è persistito


# ── apertura su cartella AppData inesistente (Codex P2) ───────────────────────

def test_apertura_crea_la_cartella_padre(tmp_path):
    # La cartella padre NON esiste: l'init deve crearla, non sollevare.
    path = str(tmp_path / "non" / "ancora" / "betfair.db")
    d = BetfairLocalDB(path)
    d.upsert_sport("1", "Calcio", seen_at=d.new_sync_marker())
    assert d.count_active("betfair_sports") == 1
    d.close()
    assert (tmp_path / "non" / "ancora" / "betfair.db").exists()


def test_name_mapping_per_sport_non_duplica(db):
    db.upsert_name_mapping("Calcio", "juve", "Juventus", "team", seen_at=1)
    db.upsert_name_mapping("Calcio", "juve", "Juventus FC", "team", seen_at=2)
    # stesso sport+nome → upsert; sport diverso → riga distinta
    db.upsert_name_mapping("Tennis", "juve", "Juve Tennis", "player", seen_at=1)
    rows = db.fetchall("betfair_local_name_mappings")
    assert len(rows) == 2


# ── #184 LOW: busy timeout esteso (no "database is locked" prematuro) ──────────

def test_busy_timeout_impostato_a_30s(db):
    # La connessione deve avere busy_timeout = 30000 ms (non i 5000 di default sqlite):
    # un accesso concorrente aspetta invece di fallire subito con "database is locked".
    from xtrader_bridge.betfair.local_db import _BUSY_TIMEOUT_S
    got = db._conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert got == _BUSY_TIMEOUT_S * 1000 == 30000


def test_busy_timeout_anche_su_db_su_file(tmp_path):
    # Il PRAGMA vale anche per un DB su file reale (il caso d'uso multi-accesso).
    path = str(tmp_path / "betfair.db")
    d = BetfairLocalDB(path)
    try:
        assert d._conn.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
    finally:
        d.close()


def test_scrittura_concorrente_aspetta_il_lock_e_non_fallisce(tmp_path):
    # Un'ALTRA connessione tiene il write-lock del file per un istante: grazie al busy
    # timeout la BetfairLocalDB ASPETTA che si liberi e la scrittura RIESCE, invece di
    # sollevare "database is locked". Esercita il lock reale tra due connessioni su file.
    import sqlite3
    import threading
    import time

    path = str(tmp_path / "betfair.db")
    d = BetfairLocalDB(path)            # crea schema + busy_timeout=30s

    blocker = sqlite3.connect(path)
    blocker.execute("BEGIN IMMEDIATE")  # acquisisce il write-lock del file
    blocker.execute(
        "INSERT INTO betfair_meta(key, value) VALUES('x', 1)")

    done = {"ok": False, "err": None}

    def _writer():
        try:
            # Deve BLOCCARSI sul lock del blocker, poi riuscire quando viene rilasciato.
            d.upsert_sport("1", "Calcio", seen_at=d.new_sync_marker())
            done["ok"] = True
        except Exception as ex:          # noqa: BLE001 — raccolto per l'assert
            done["err"] = ex

    t = threading.Thread(target=_writer)
    t.start()
    time.sleep(0.2)                      # il writer è in attesa sul lock
    blocker.commit()                     # rilascia il write-lock
    blocker.close()
    t.join(timeout=10)

    assert done["err"] is None, f"scrittura concorrente fallita: {done['err']}"
    assert done["ok"] is True
    assert d.count_active("betfair_sports") == 1
    d.close()


# ── #184 LOW: prune di betfair_sync_runs (no crescita illimitata) ─────────────

def test_record_sync_run_pota_le_run_oltre_il_cap(db):
    from xtrader_bridge.betfair.local_db import _SYNC_RUNS_KEEP
    # Inserisce CAP+5 run: la tabella deve restare a CAP, tenendo le più recenti.
    for i in range(_SYNC_RUNS_KEEP + 5):
        db.record_sync_run(started_at=i, finished_at=i, status="OK", summary=f"run{i}")
    rows = db.fetchall("betfair_sync_runs")
    assert len(rows) == _SYNC_RUNS_KEEP                 # tabella limitata
    ids = sorted(r["run_id"] for r in rows)
    # le 5 più vecchie (run_id 1..5) sono state eliminate; restano le più recenti
    assert ids[0] == 6
    assert ids[-1] == _SYNC_RUNS_KEEP + 5


def test_record_sync_run_sotto_il_cap_non_pota(db):
    for i in range(10):
        db.record_sync_run(started_at=i, finished_at=i, status="OK")
    assert len(db.fetchall("betfair_sync_runs")) == 10   # nessuna potatura sotto il cap


def test_prune_sync_runs_tiene_le_piu_recenti(db):
    for i in range(20):
        db.record_sync_run(started_at=i, finished_at=i, status="OK", summary=f"r{i}")
    deleted = db.prune_sync_runs(keep=5)
    assert deleted == 15
    rows = db.fetchall("betfair_sync_runs")
    assert len(rows) == 5
    ids = sorted(r["run_id"] for r in rows)
    assert ids == [16, 17, 18, 19, 20]                   # solo le 5 più recenti


def test_prune_sync_runs_keep_zero_non_svuota(db):
    # Guardia: keep<=0 NON deve svuotare la tabella per errore.
    for i in range(3):
        db.record_sync_run(started_at=i, finished_at=i, status="OK")
    assert db.prune_sync_runs(keep=0) == 0
    assert db.prune_sync_runs(keep=-1) == 0
    assert len(db.fetchall("betfair_sync_runs")) == 3


def test_prune_dentro_transazione_e_atomico(tmp_path):
    # Se la transazione che contiene record_sync_run fa rollback, anche il prune viene
    # annullato: la tabella resta com'era (atomicità insert+prune con la transazione).
    path = str(tmp_path / "betfair.db")
    d = BetfairLocalDB(path)
    for i in range(5):
        d.record_sync_run(started_at=i, finished_at=i, status="OK")
    assert len(d.fetchall("betfair_sync_runs")) == 5
    try:
        with d.transaction():
            d.record_sync_run(started_at=99, finished_at=99, status="OK")
            d.prune_sync_runs(keep=1)             # proverebbe a tenere solo 1 riga
            raise RuntimeError("boom: forza il rollback")
    except RuntimeError:
        pass
    # rollback: né il nuovo insert né il prune sono stati applicati
    assert len(d.fetchall("betfair_sync_runs")) == 5
    d.close()


# ── nomi squadra PERMANENTI (harvest #282) ────────────────────────────────────

def test_known_team_upsert_e_normalizzazione(db):
    # Stesso nome con case/spazi diversi = STESSA chiave normalizzata → nessun duplicato.
    assert db.upsert_known_team("Calcio", "  Inter  ", seen_at=1) is True
    assert db.upsert_known_team("Calcio", "inter", seen_at=2) is True   # dup per norm
    assert db.upsert_known_team("Calcio", "Milan", seen_at=1) is True
    assert db.count_known_teams("Calcio") == 2                          # Inter + Milan
    teams = {t["normalized_name"] for t in db.known_teams("Calcio")}
    assert teams == {"inter", "milan"}


def test_known_team_nome_vuoto_saltato(db):
    # Nome vuoto / solo spazi → non scrive nulla (ritorna False), nessuna riga fantasma.
    assert db.upsert_known_team("Calcio", "   ", seen_at=1) is False
    assert db.upsert_known_team("Calcio", None, seen_at=1) is False
    assert db.count_known_teams() == 0


def test_known_team_first_seen_fisso_last_seen_aggiornato(db):
    # first_seen_at resta la PRIMA volta; last_seen_at e display_name seguono l'ultima vista.
    db.upsert_known_team("Tennis", "Sinner", seen_at=10)
    db.upsert_known_team("Tennis", "SINNER", seen_at=20)     # rivisto (grafia diversa)
    row = db.known_teams("Tennis")[0]
    assert row["first_seen_at"] == 10                        # invariato
    assert row["last_seen_at"] == 20                         # aggiornato
    assert row["display_name"] == "SINNER"                   # ultima grafia


def test_known_team_filtro_per_sport(db):
    db.upsert_known_team("Calcio", "Juventus", seen_at=1)
    db.upsert_known_team("Tennis", "Alcaraz", seen_at=1)
    assert {t["display_name"] for t in db.known_teams("Calcio")} == {"Juventus"}
    assert {t["display_name"] for t in db.known_teams("Tennis")} == {"Alcaraz"}
    assert db.count_known_teams() == 2                        # tutti gli sport


def test_known_teams_permanenti_non_toccati_dal_mark_and_sweep(db):
    # La tabella NON è scopabile da deactivate_unseen: il mark-and-sweep non può
    # disattivarla (permanenza by-construction). Un tentativo esplicito è respinto.
    db.upsert_known_team("Calcio", "Roma", seen_at=1)
    with pytest.raises(ValueError):
        db.deactivate_unseen("betfair_known_teams", 999)
    # e non esiste alcuna colonna active da azzerare: resta consultabile per sempre
    assert db.count_known_teams("Calcio") == 1
    assert db.fetchall("betfair_known_teams")[0]["display_name"] == "Roma"


def test_known_teams_persistono_su_disco_dopo_riapertura(tmp_path):
    # Durata reale: i nomi permanenti sopravvivono a chiusura/riapertura del DB su file
    # (persistenza SQLite), e la tabella viene ricreata da `CREATE TABLE IF NOT EXISTS`
    # anche su un DB già esistente (compatibilità upgrade).
    path = str(tmp_path / "betfair.db")
    d1 = BetfairLocalDB(path)
    d1.upsert_known_team("Calcio", "Juventus", seen_at=1)
    d1.close()
    d2 = BetfairLocalDB(path)                         # riapertura: schema idempotente
    assert d2.count_known_teams("Calcio") == 1
    assert d2.known_teams("Calcio")[0]["display_name"] == "Juventus"
    d2.close()


def test_delete_known_team_per_chiave_esatta(db):
    # Ripulitura manuale (#282 PR 11-bis): elimina SOLO la coppia (sport, normalized_name).
    db.upsert_known_team("Calcio", "Inter", seen_at=1)
    db.upsert_known_team("Calcio", "Milan", seen_at=1)
    db.upsert_known_team("Basket", "Milan", seen_at=1)     # stesso nome, altro sport
    assert db.delete_known_team("Calcio", "inter") == 1     # normalized_name
    assert db.delete_known_team("Calcio", "inter") == 0     # già eliminato → 0
    # "Milan" del Basket NON è toccato eliminando quello del Calcio
    assert db.delete_known_team("Calcio", "milan") == 1
    assert {(t["sport"], t["display_name"]) for t in db.known_teams()} == {("Basket", "Milan")}


def test_delete_known_team_nome_inesistente_no_op(db):
    db.upsert_known_team("Calcio", "Roma", seen_at=1)
    assert db.delete_known_team("Calcio", "lazio") == 0     # non c'è → nessuna riga tolta
    assert db.count_known_teams("Calcio") == 1              # Roma resta


# ── valori permanenti mercato/selezione (#283) ────────────────────────────────

def test_market_term_anchor_e_selezione(db):
    # Riga àncora del solo mercato (MarketType/MarketName) + righe selezione.
    assert db.upsert_market_term("Calcio", "MATCH_ODDS", "Esito Finale", seen_at=1) is True
    assert db.upsert_market_term(
        "Calcio", "OVER_UNDER_25", "Over/Under 2,5", "Over 2,5", seen_at=1) is True
    assert db.upsert_market_term(
        "Calcio", "OVER_UNDER_25", "Over/Under 2,5", "Under 2,5", seen_at=1) is True
    # MarketType/MarketName distinti includono ANCHE il mercato senza selezioni.
    assert db.known_market_types("Calcio") == ["MATCH_ODDS", "OVER_UNDER_25"]
    assert db.known_market_names("Calcio") == ["Esito Finale", "Over/Under 2,5"]
    # SelectionName: solo le due selezioni universali; l'àncora (selezione vuota) è esclusa.
    assert db.known_selection_names("Calcio") == ["Over 2,5", "Under 2,5"]


def test_market_term_market_name_vuoto_saltato(db):
    # MarketName vuoto/None → niente riga (ritorna False), nessun record fantasma.
    assert db.upsert_market_term("Calcio", "MATCH_ODDS", "   ", seen_at=1) is False
    assert db.upsert_market_term("Calcio", "MATCH_ODDS", None, "X", seen_at=1) is False
    assert db.count_market_terms() == 0


def test_market_term_dedup_normalizzato(db):
    # Stesso mercato/selezione con case/spazi diversi = stessa chiave normalizzata.
    db.upsert_market_term("Calcio", "OVER_UNDER_25", "Over/Under 2,5", "Over 2,5", seen_at=1)
    db.upsert_market_term("Calcio", "OVER_UNDER_25", "  over/under 2,5 ", " OVER 2,5 ", seen_at=2)
    assert db.count_market_terms("Calcio") == 1                 # nessun duplicato
    assert db.known_selection_names("Calcio") == ["OVER 2,5"]   # ultima grafia


def test_market_term_first_seen_fisso_last_seen_aggiornato(db):
    # Case-only diff → stessa chiave normalizzata: first_seen resta, last_seen/grafia seguono.
    db.upsert_market_term("Calcio", "OVER_UNDER_25", "Over/Under 2,5", "Over 2,5", seen_at=10)
    db.upsert_market_term("Calcio", "OVER_UNDER_25", "Over/Under 2,5", "OVER 2,5", seen_at=20)
    row = [r for r in db.fetchall("betfair_known_market_terms")
           if r["normalized_selection"]][0]
    assert row["first_seen_at"] == 10          # invariato
    assert row["last_seen_at"] == 20           # aggiornato
    assert row["selection_name"] == "OVER 2,5"  # ultima grafia


def test_market_term_selezioni_coerenti_col_mercato(db):
    # known_selection_names filtrato per mercato: solo le selezioni di QUEL mercato
    # (invariante «selezione appartiene al mercato»).
    db.upsert_market_term("Calcio", "OVER_UNDER_25", "Over/Under 2,5", "Over 2,5", seen_at=1)
    db.upsert_market_term("Calcio", "OVER_UNDER_25", "Over/Under 2,5", "Under 2,5", seen_at=1)
    db.upsert_market_term("Calcio", "BOTH_TEAMS_TO_SCORE", "Gol/NoGol", "Sì", seen_at=1)
    db.upsert_market_term("Calcio", "BOTH_TEAMS_TO_SCORE", "Gol/NoGol", "No", seen_at=1)
    assert db.known_selection_names("Calcio", market="Over/Under 2,5") == ["Over 2,5", "Under 2,5"]
    assert db.known_selection_names("Calcio", market="Gol/NoGol") == ["No", "Sì"]
    assert db.known_selection_names("Calcio") == ["No", "Over 2,5", "Sì", "Under 2,5"]


def test_market_term_filtro_per_sport(db):
    db.upsert_market_term("Calcio", "OVER_UNDER_25", "Over/Under 2,5", "Over 2,5", seen_at=1)
    db.upsert_market_term("Tennis", "OVER_UNDER_205_GAMES", "Over/Under 20,5 games",
                          "Over 20,5", seen_at=1)
    assert db.known_market_names("Calcio") == ["Over/Under 2,5"]
    assert db.known_market_names("Tennis") == ["Over/Under 20,5 games"]
    assert db.known_selection_names("Calcio") == ["Over 2,5"]
    assert db.count_market_terms() == 2                          # tutti gli sport


def test_market_terms_permanenti_non_toccati_dal_mark_and_sweep(db):
    # La tabella NON è scopabile da deactivate_unseen: permanenza by-construction.
    db.upsert_market_term("Calcio", "MATCH_ODDS", "Esito Finale", seen_at=1)
    with pytest.raises(ValueError):
        db.deactivate_unseen("betfair_known_market_terms", 999)
    assert db.count_market_terms("Calcio") == 1
    assert db.known_market_names("Calcio") == ["Esito Finale"]


def test_market_terms_persistono_su_disco_dopo_riapertura(tmp_path):
    path = str(tmp_path / "betfair.db")
    d1 = BetfairLocalDB(path)
    d1.upsert_market_term("Calcio", "OVER_UNDER_25", "Over/Under 2,5", "Over 2,5", seen_at=1)
    d1.close()
    d2 = BetfairLocalDB(path)                         # riapertura: schema idempotente
    assert d2.known_market_names("Calcio") == ["Over/Under 2,5"]
    assert d2.known_selection_names("Calcio") == ["Over 2,5"]
    d2.close()


def test_distinct_market_terms_colonna_non_valida(db):
    # Guardia SQL: la colonna è FISSA dal codice, mai input utente.
    with pytest.raises(ValueError):
        db._distinct_market_terms("selection_name; DROP TABLE x", "Calcio")


def test_market_term_stesso_nome_tipo_diverso_non_collide(db):
    # market_type è PARTE della chiave: due mercati con lo STESSO market_name ma tipo
    # diverso restano righe SEPARATE (niente last-write-wins sul tipo → tupla coerente,
    # Fable/GPT #326).
    db.upsert_market_term("Calcio", "OVER_UNDER_25", "Goals", "Over 2,5", seen_at=1)
    db.upsert_market_term("Calcio", "OVER_UNDER_35", "Goals", "Over 3,5", seen_at=1)
    assert db.known_market_types("Calcio") == ["OVER_UNDER_25", "OVER_UNDER_35"]
    # entrambi i tipi conservati (nessuno sovrascritto), stesso market_name condiviso
    assert db.known_market_names("Calcio") == ["Goals"]
    assert db.count_market_terms("Calcio") == 2
    rows = {(r["market_type"], r["selection_name"])
            for r in db.fetchall("betfair_known_market_terms")}
    assert rows == {("OVER_UNDER_25", "Over 2,5"), ("OVER_UNDER_35", "Over 3,5")}


def test_market_term_type_vuoto_salvato_come_stringa(db):
    # market_type assente → salvato come '' (non NULL: fa parte della PK), escluso dai
    # MarketType distinti ma il mercato resta consultabile via MarketName.
    assert db.upsert_market_term("Calcio", None, "Mercato senza tipo", seen_at=1) is True
    assert db.known_market_types("Calcio") == []          # '' escluso
    assert db.known_market_names("Calcio") == ["Mercato senza tipo"]
    assert db.fetchall("betfair_known_market_terms")[0]["market_type"] == ""


def test_market_terms_migrazione_pk_da_schema_legacy(tmp_path):
    # Upgrade da schema LEGACY (PK a 3 colonne, market_type nullable) → la migrazione
    # ricrea la tabella con la PK a 4 colonne e copia i dati (market_type NULL → '').
    # Fail-first: senza `_migrate_market_terms_pk` l'`ON CONFLICT` a 4 colonne solleverebbe
    # OperationalError su questo DB (Fable/Fugu/GLM/GPT #326).
    import sqlite3
    path = str(tmp_path / "betfair.db")
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE betfair_known_market_terms (
            sport                TEXT NOT NULL,
            market_type          TEXT,
            normalized_market    TEXT NOT NULL,
            market_name          TEXT,
            normalized_selection TEXT NOT NULL DEFAULT '',
            selection_name       TEXT,
            first_seen_at        INTEGER NOT NULL DEFAULT 0,
            last_seen_at         INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (sport, normalized_market, normalized_selection)
        );
        INSERT INTO betfair_known_market_terms
            (sport, market_type, normalized_market, market_name,
             normalized_selection, selection_name, first_seen_at, last_seen_at)
        VALUES ('Calcio', NULL, 'esito finale', 'Esito Finale', '', NULL, 5, 5),
               ('Calcio', 'OVER_UNDER_25', 'over/under 2,5', 'Over/Under 2,5',
                'over 2,5', 'Over 2,5', 5, 5);
        """)
    con.commit()
    con.close()

    db = BetfairLocalDB(path)                    # apertura → migrazione idempotente
    info = db._conn.execute(
        "PRAGMA table_info(betfair_known_market_terms)").fetchall()
    pk_cols = [r["name"] for r in sorted((r for r in info if r["pk"]),
                                         key=lambda r: r["pk"])]
    assert pk_cols == ["sport", "market_type", "normalized_market", "normalized_selection"]
    # dati preservati, market_type NULL migrato a '', first_seen conservato
    assert db.count_market_terms("Calcio") == 2
    assert db.known_market_names("Calcio") == ["Esito Finale", "Over/Under 2,5"]
    assert db.known_selection_names("Calcio") == ["Over 2,5"]
    assert {r["market_type"] for r in db.fetchall("betfair_known_market_terms")} \
        == {"", "OVER_UNDER_25"}
    # e l'ON CONFLICT a 4 colonne ora funziona (niente OperationalError)
    assert db.upsert_market_term("Calcio", "OVER_UNDER_25", "Over/Under 2,5",
                                 "Under 2,5", seen_at=9) is True
    assert db.known_selection_names("Calcio", market="Over/Under 2,5") == \
        ["Over 2,5", "Under 2,5"]
    db.close()

    # riapertura: la migrazione è idempotente (tabella già a 4 colonne → no-op)
    db2 = BetfairLocalDB(path)
    assert db2.count_market_terms("Calcio") == 3
    db2.close()


def test_migrate_market_terms_pk_tabella_assente_no_op(db):
    # Ramo `if not info: return`: se la tabella non esiste, la migrazione non fa nulla e
    # non solleva (GLM/GPT #326). (In apertura normale `_SCHEMA` la crea prima, ma la
    # guardia deve reggere se invocata a vuoto.)
    db._conn.execute("DROP TABLE betfair_known_market_terms")
    db._conn.commit()
    db._migrate_market_terms_pk()                # non solleva
    db._conn.execute(              # ricrea la tabella per non lasciare il db a metà
        """CREATE TABLE betfair_known_market_terms (
               sport TEXT NOT NULL, market_type TEXT NOT NULL DEFAULT '',
               normalized_market TEXT NOT NULL, market_name TEXT,
               normalized_selection TEXT NOT NULL DEFAULT '', selection_name TEXT,
               first_seen_at INTEGER NOT NULL DEFAULT 0, last_seen_at INTEGER NOT NULL DEFAULT 0,
               PRIMARY KEY (sport, market_type, normalized_market, normalized_selection))""")
    db._conn.commit()
    assert db.count_market_terms() == 0


def test_market_terms_migrazione_pk_con_bkmt_old_residuo(tmp_path):
    # Robustezza: se una migrazione precedente si era interrotta lasciando `_bkmt_old`
    # orfana, il `DROP TABLE IF EXISTS _bkmt_old` la ripulisce e la migrazione riesce
    # (niente «table _bkmt_old already exists» sul RENAME) — Fable #326.
    import sqlite3
    path = str(tmp_path / "betfair.db")
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE betfair_known_market_terms (
            sport TEXT NOT NULL, market_type TEXT, normalized_market TEXT NOT NULL,
            market_name TEXT, normalized_selection TEXT NOT NULL DEFAULT '',
            selection_name TEXT, first_seen_at INTEGER NOT NULL DEFAULT 0,
            last_seen_at INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (sport, normalized_market, normalized_selection)
        );
        CREATE TABLE _bkmt_old (x INTEGER);       -- residuo di una migrazione interrotta
        INSERT INTO betfair_known_market_terms
            (sport, market_type, normalized_market, market_name, normalized_selection, selection_name)
        VALUES ('Calcio', 'OVER_UNDER_25', 'over/under 2,5', 'Over/Under 2,5', 'over 2,5', 'Over 2,5');
        """)
    con.commit()
    con.close()
    db = BetfairLocalDB(path)                    # migrazione: droppa _bkmt_old residuo e migra
    info = db._conn.execute("PRAGMA table_info(betfair_known_market_terms)").fetchall()
    assert any(r["name"] == "market_type" and r["pk"] for r in info)   # market_type in PK
    assert db.known_selection_names("Calcio") == ["Over 2,5"]
    # _bkmt_old non deve restare (droppata + ri-droppata a fine migrazione)
    tables = {r[0] for r in db._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "_bkmt_old" not in tables
    db.close()
