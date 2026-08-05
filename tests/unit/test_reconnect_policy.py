"""Test della politica di riconnessione del listener (logica pura)."""

import pytest

from xtrader_bridge import reconnect_policy as rp


# ── backoff ──────────────────────────────────────────────────────────────────

def test_backoff_cresce_esponenziale_dal_base():
    assert rp.backoff_delay(1) == 2.0      # base
    assert rp.backoff_delay(2) == 4.0
    assert rp.backoff_delay(3) == 8.0
    assert rp.backoff_delay(4) == 16.0


def test_backoff_limitato_al_cap():
    # Cresce ma non supera mai il tetto.
    assert rp.backoff_delay(100) == rp.DEFAULT_MAX_DELAY
    assert rp.backoff_delay(1, base=10, cap=25) == 10
    assert rp.backoff_delay(2, base=10, cap=25) == 20
    assert rp.backoff_delay(3, base=10, cap=25) == 25   # 40 → cap 25


def test_backoff_attempt_non_valido_trattato_come_primo():
    assert rp.backoff_delay(0) == 2.0
    assert rp.backoff_delay(-5) == 2.0


def test_backoff_attempt_enorme_non_va_in_overflow():
    # Codex P2: dopo molte ore di tentativi `attempt` diventa grande; 2**(attempt-1)
    # andrebbe in OverflowError. Deve invece restare al cap senza eccezioni.
    assert rp.backoff_delay(10_000) == rp.DEFAULT_MAX_DELAY
    assert rp.backoff_delay(10**9) == rp.DEFAULT_MAX_DELAY


# ── delay effettivo: backoff + retry_after di Telegram (flood control) ────────

def test_effective_delay_senza_retry_after_e_il_backoff():
    # Nessun retry_after (o assente da getattr) → resta il puro backoff.
    assert rp.effective_delay(1) == rp.backoff_delay(1)
    assert rp.effective_delay(3, None) == rp.backoff_delay(3)


def test_effective_delay_retry_after_piu_lungo_vince():
    # Il server chiede di aspettare 50s al primo tentativo (backoff=2): si attende 50.
    assert rp.effective_delay(1, 50) == 50.0
    # retry_after frazionario rispettato (float).
    assert rp.effective_delay(1, 3.5) == 3.5


def test_effective_delay_retry_after_piu_corto_non_riduce_il_backoff():
    # retry_after più breve del backoff non accorcia l'attesa (4° tentativo = 16s).
    assert rp.effective_delay(4, 5) == rp.backoff_delay(4)
    assert rp.effective_delay(4, 5) == 16.0


def test_effective_delay_retry_after_non_numerico_ignorato():
    # Stringa/None/oggetto non numerico → ignorato, resta il backoff.
    assert rp.effective_delay(2, "nope") == rp.backoff_delay(2)
    assert rp.effective_delay(2, object()) == rp.backoff_delay(2)


def test_effective_delay_retry_after_bool_ignorato():
    # True (==1) non è un retry_after valido: rifiutato come bool, resta il backoff.
    assert rp.effective_delay(1, True) == rp.backoff_delay(1)
    assert rp.effective_delay(1, False) == rp.backoff_delay(1)


# ── classificazione errori (whitelist transitori) ────────────────────────────

class NetworkError(Exception):
    pass


class TimedOut(NetworkError):
    pass


class RetryAfter(Exception):
    pass


class InvalidToken(Exception):
    pass


# ── percorso FALLBACK: telegram non importabile → match per nome sull'MRO ──────
# Forziamo la cache a () così il test è deterministico anche se `telegram` fosse
# installato in locale (con isinstance, classi finte omonime non sarebbero transitorie).

def test_fallback_per_nome_errori_di_rete_sono_transitori(monkeypatch):
    monkeypatch.setattr(rp, "_TRANSIENT_TYPES_CACHE", ())   # forza il fallback per nome
    assert rp.is_transient_error(NetworkError("giù")) is True
    assert rp.is_transient_error(TimedOut("timeout")) is True      # via MRO (sottoclasse)
    assert rp.is_transient_error(RetryAfter("flood")) is True


def test_fallback_per_nome_errori_permanenti_non_sono_transitori(monkeypatch):
    monkeypatch.setattr(rp, "_TRANSIENT_TYPES_CACHE", ())
    # Token invalido = configurazione sbagliata: NON deve ciclare a vuoto.
    assert rp.is_transient_error(InvalidToken("token")) is False
    # Un errore inatteso (bug) non è in whitelist → niente retry infinito.
    assert rp.is_transient_error(ValueError("bug")) is False
    assert rp.is_transient_error(RuntimeError("boom")) is False


# ── percorso PRINCIPALE (audit C6): isinstance sui tipi REALI di telegram.error ──

def test_isinstance_sui_tipi_reali_evita_falso_positivo_per_nome(monkeypatch):
    # Quando i tipi reali sono disponibili, la classificazione usa isinstance, NON il nome.
    # Simuliamo "telegram installato" iniettando classi reali nella cache.
    class RealNetworkError(Exception):
        pass

    class RealTimedOut(RealNetworkError):
        pass

    class RealRetryAfter(Exception):
        pass

    monkeypatch.setattr(rp, "_TRANSIENT_TYPES_CACHE",
                        (RealNetworkError, RealTimedOut, RealRetryAfter))

    # Istanze/sottoclassi dei tipi reali → transitorie.
    assert rp.is_transient_error(RealNetworkError("giù")) is True
    assert rp.is_transient_error(RealTimedOut("timeout")) is True
    assert rp.is_transient_error(RealRetryAfter("flood")) is True

    # Un'eccezione che condivide solo il NOME ("NetworkError") ma NON è il tipo reale di
    # telegram → NON transitoria. Col vecchio match per nome era un falso positivo che
    # mandava il supervisor in reconnect infinito (audit C6).
    assert rp.is_transient_error(NetworkError("impostore omonimo")) is False
    assert rp.is_transient_error(ValueError("bug")) is False


def test_real_transient_types_non_solleva_ed_e_cache(monkeypatch):
    """La risoluzione dei tipi reali non deve mai sollevare e va cache-ata (stesso oggetto
    al secondo accesso). Senza `telegram.error` (CI headless) la tupla è vuota → fallback.

    Sonda (#247). La precondizione si misura su **`telegram.error`**, cioè esattamente ciò
    che `_real_transient_types` importa, e NON su `import telegram`. Le due cose divergono:
    `telegram/__init__.py` importa `error` prima di `request`, quindi se manca una dipendenza
    transitiva (`httpx`/`idna` — che vivono nella user-site, cioè in una cartella che dipende
    da `HOME`) il pacchetto non è importabile ma `sys.modules['telegram.error']` resta
    popolato e reale. Con la vecchia sonda questo test pretendeva la tupla vuota mentre la
    funzione restituiva — correttamente — le classi reali: un rosso che dipendeva da `HOME`
    invece che dal codice."""
    monkeypatch.setattr(rp, "_TRANSIENT_TYPES_CACHE", None)   # forza una nuova risoluzione
    first = rp._real_transient_types()
    assert isinstance(first, tuple)
    assert rp._real_transient_types() is first               # cache-ato
    try:
        from telegram.error import NetworkError as _NE, RetryAfter as _RA, TimedOut as _TO
        classi_reali = (_NE, _TO, _RA)
    except Exception:  # noqa: BLE001 — sonda d'ambiente: `telegram.error` non importabile e' UNO DEI DUE CASI ATTESI, non un errore del test — decide quale asserzione applicare
        classi_reali = None
    if classi_reali is None:
        assert first == ()                                   # assenza telegram.error → fallback
    else:
        assert first == classi_reali                         # presenza → classi REALI, non nomi


def test_import_parziale_di_telegram_risolve_comunque_le_classi_reali(monkeypatch):
    """#247: `telegram.error` importabile MA pacchetto `telegram` no → si usano le reali.

    Non è uno scenario di laboratorio, è quello che succede davvero quando manca una
    dipendenza transitiva (`httpx`/`idna`): `telegram/__init__.py` importa `error` prima di
    `request`, l'import del pacchetto fallisce, e `sys.modules['telegram.error']` resta
    popolato. Qui lo si ricrea in modo deterministico — `telegram` RIMOSSO da `sys.modules`,
    `telegram.error` presente — e si pretende che la risoluzione usi comunque le classi reali
    del sottomodulo, perché sono più precise del match per nome.

    Il test fallirebbe se qualcuno "semplificasse" `_real_transient_types` in un
    `import telegram` seguito da `telegram.error`: in quello stato solleverebbe → tupla vuota
    → fallback per nome, cioè proprio il falso positivo che l'audit C6 aveva chiuso."""
    import sys
    import types

    finto = types.ModuleType("telegram.error")
    finto.NetworkError = type("NetworkError", (Exception,), {})
    finto.TimedOut = type("TimedOut", (finto.NetworkError,), {})
    finto.RetryAfter = type("RetryAfter", (Exception,), {})
    monkeypatch.setitem(sys.modules, "telegram.error", finto)
    monkeypatch.delitem(sys.modules, "telegram", raising=False)   # pacchetto NON importato
    monkeypatch.setattr(rp, "_TRANSIENT_TYPES_CACHE", None)

    risolte = rp._real_transient_types()
    assert risolte == (finto.NetworkError, finto.TimedOut, finto.RetryAfter)

    # E la classificazione usa quelle classi: un omonimo dinamico NON è transitorio.
    assert rp.is_transient_error(finto.TimedOut("timeout")) is True
    assert rp.is_transient_error(type("TimedOut", (Exception,), {})("impostore")) is False


# ── decisione finale del supervisor ──────────────────────────────────────────

def test_should_reconnect_solo_se_running_e_transitorio(monkeypatch):
    monkeypatch.setattr(rp, "_TRANSIENT_TYPES_CACHE", ())   # fallback per nome (deterministico)
    # Errore di rete mentre il bridge è attivo → riconnetti.
    assert rp.should_reconnect(True, NetworkError("x")) is True
    # STOP manuale (running=False) → mai, nemmeno su errore di rete.
    assert rp.should_reconnect(False, NetworkError("x")) is False
    # Errore permanente, anche se attivo → no.
    assert rp.should_reconnect(True, InvalidToken("x")) is False


# ── P3-rs3 (#166): un `retry_after` fuori scala non deve uccidere il supervisor ──────────────

def test_effective_delay_rifiuta_un_retry_after_non_finito():
    """`inf`/`-inf`/`nan` non sono richieste del server: sono dati corrotti.

    `getattr(ex, "retry_after", None)` legge un attributo popolato dalla **risposta
    dell'API**. Un valore non finito che arriva fin lì viene trattato come il caso già
    previsto «assente o non numerico»: si resta sul backoff locale. Il motivo per cui non lo
    si può lasciar passare è nel test qui sotto."""
    for guasto in (float("inf"), float("-inf"), float("nan")):
        assert rp.effective_delay(1, guasto) == rp.backoff_delay(1), guasto
        assert rp.effective_delay(5, guasto) == rp.backoff_delay(5), guasto


def test_un_delay_non_finito_ucciderebbe_il_thread_di_riconnessione():
    """La ragione della guardia, eseguita invece che affermata in un commento.

    Il ritardo finisce in `app._reconnect_wait` → `threading.Event.wait(delay)`. Con un
    valore che non entra nel `time_t` della piattaforma, `wait` solleva **OverflowError**:
    un'eccezione non gestita nel supervisor di riconnessione, che muore. Il bridge resta
    «avviato» nella GUI e non riconnette più — il modo peggiore di rompersi, perché è muto.

    `backoff_delay` cappa già l'esponente per questa identica ragione (vedi il commento nel
    sorgente): `effective_delay` aggirava quella protezione.

    Nota sul metodo (rilievo GPT-5.5 #169). Il test **non chiama** `wait` con un valore fuori
    scala, per due ragioni indipendenti:

    1. il tipo di eccezione sarebbe un dettaglio di implementazione su cui non vale la pena
       legare la CI;
    2. soprattutto, una chiamata reale che *non* sollevasse si **bloccherebbe** — e un test che
       si impicca è peggio di uno che fallisce: in CI diventa un timeout opaco invece di un
       messaggio, e brucia minuti runner (Windows al doppio).

    L'ancora è invece `threading.TIMEOUT_MAX`, che è **documentata**: un timeout superiore a
    quel valore solleva `OverflowError`. Varia per piattaforma (su Linux ~292 anni, su Windows
    ~49 giorni), ed è proprio per questo che va **confrontata** e mai ipotizzata."""
    import math
    import threading

    # Il confine documentato oltre il quale `wait` rifiuta il timeout. Un `retry_after` non
    # finito ci finisce sempre oltre, su qualunque piattaforma.
    assert float("inf") > threading.TIMEOUT_MAX

    # La garanzia che conta: qualunque cosa esca da `effective_delay` è attendibile davvero —
    # finita, positiva, sotto il tetto, e sotto il massimo che `wait` accetta QUI.
    assert rp.MAX_RETRY_AFTER <= threading.TIMEOUT_MAX
    for guasto in (float("inf"), float("-inf"), float("nan"), 1e300, 1e9):
        d = rp.effective_delay(1, guasto)
        assert math.isfinite(d) and 0 < d <= rp.MAX_RETRY_AFTER, (guasto, d)
        assert d <= threading.TIMEOUT_MAX, (guasto, d)


def test_effective_delay_limita_un_retry_after_assurdamente_lungo():
    """Secondo modo di rompersi, più insidioso del primo perché **non solleva nulla**.

    Un `retry_after` grande ma finito (es. 1e9 secondi ≈ 31 anni) passa la validazione di
    `Event.wait` e viene **atteso davvero**: nessuna eccezione, nessun log, il supervisor
    dorme e il bridge sembra vivo. Un tetto lo trasforma in un'attesa lunga ma finita, dopo
    la quale si riprova (e se il server è ancora in flood control lo ridirà, in modo
    visibile e ripetibile)."""
    assert rp.effective_delay(1, 1e9) == rp.MAX_RETRY_AFTER
    assert rp.effective_delay(1, rp.MAX_RETRY_AFTER * 10) == rp.MAX_RETRY_AFTER
    # Il tetto è generoso: molto sopra qualunque flood control reale di Telegram.
    assert rp.MAX_RETRY_AFTER >= 600


def test_un_retry_after_legittimo_resta_intatto():
    """Nessuna regressione: la ragion d'essere di `effective_delay` è onorare la richiesta
    del server quando è più lunga del backoff. Un valore plausibile non deve essere toccato
    né dalla guardia sui non-finiti né dal tetto."""
    assert rp.effective_delay(1, 50) == 50.0
    assert rp.effective_delay(1, 3.5) == 3.5
    assert rp.effective_delay(1, 300) == 300.0
    assert rp.effective_delay(1, rp.MAX_RETRY_AFTER) == rp.MAX_RETRY_AFTER
    # e uno più corto del backoff continua a non ridurlo
    assert rp.effective_delay(4, 5) == rp.backoff_delay(4)


@pytest.mark.parametrize("attempt", [1, 3, 6])
@pytest.mark.parametrize("corto", [0, -1, -3600, -1e9, float("-inf")])
def test_un_retry_after_nullo_o_negativo_non_accorcia_mai_il_backoff(attempt, corto):
    """Copertura chiesta da GPT-5.5 (#169). Il verso della guardia conta: `effective_delay`
    può solo ALLUNGARE l'attesa, mai accorciarla.

    Se un valore ≤ 0 riuscisse a passare, la riconnessione partirebbe **subito** a ogni
    tentativo — un loop stretto contro un server che ci sta già rifiutando, cioè il modo più
    veloce per farsi bannare dal flood control. Provato su più tentativi perché il backoff
    cresce e il confronto deve reggere a ogni scalino."""
    assert rp.effective_delay(attempt, corto) == rp.backoff_delay(attempt)
    assert rp.effective_delay(attempt, corto) >= rp.DEFAULT_BASE_DELAY


@pytest.mark.parametrize("esponente", [309, 400, 10000])
def test_un_intero_gigante_non_fa_esplodere_la_guardia_stessa(esponente):
    """Rilievo CodeRabbit (#169), ed era un difetto **della guardia appena aggiunta**.

    `math.isfinite()` converte l'argomento a `float` prima di rispondere. Gli `int` di Python
    sono illimitati, quindi sopra ~1.8e308 quella conversione solleva `OverflowError: int too
    large to convert to float` — la guardia scritta per impedire un `OverflowError` ne
    sollevava uno suo, nello stesso punto e con la stessa conseguenza (supervisor morto).

    È raggiungibile per la stessa via del resto del fix: `retry_after` arriva dal JSON della
    risposta API, e il modulo `json` produce `int` di grandezza arbitraria senza batter ciglio.

    Un `int` è finito per definizione: `isfinite` serve solo sui `float`."""
    gigante = 10 ** esponente
    assert rp.effective_delay(1, gigante) == rp.MAX_RETRY_AFTER
    # e il gemello negativo non deve accorciare il backoff (né esplodere)
    assert rp.effective_delay(3, -gigante) == rp.backoff_delay(3)
