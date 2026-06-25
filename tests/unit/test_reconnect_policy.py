"""Test della politica di riconnessione del listener (logica pura)."""

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
    # La risoluzione dei tipi reali non deve mai sollevare e va cache-ata (stesso oggetto
    # al secondo accesso). Senza `telegram` (CI headless) la tupla è vuota → fallback.
    monkeypatch.setattr(rp, "_TRANSIENT_TYPES_CACHE", None)   # forza una nuova risoluzione
    first = rp._real_transient_types()
    assert isinstance(first, tuple)
    assert rp._real_transient_types() is first               # cache-ato
    try:
        import telegram  # noqa: F401
        telegram_disponibile = True
    except Exception:
        telegram_disponibile = False
    if not telegram_disponibile:
        assert first == ()                                   # assenza telegram → fallback


# ── decisione finale del supervisor ──────────────────────────────────────────

def test_should_reconnect_solo_se_running_e_transitorio(monkeypatch):
    monkeypatch.setattr(rp, "_TRANSIENT_TYPES_CACHE", ())   # fallback per nome (deterministico)
    # Errore di rete mentre il bridge è attivo → riconnetti.
    assert rp.should_reconnect(True, NetworkError("x")) is True
    # STOP manuale (running=False) → mai, nemmeno su errore di rete.
    assert rp.should_reconnect(False, NetworkError("x")) is False
    # Errore permanente, anche se attivo → no.
    assert rp.should_reconnect(True, InvalidToken("x")) is False
