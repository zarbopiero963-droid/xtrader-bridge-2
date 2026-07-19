"""PR-13: validazione delle impostazioni (logica pura, testabile in CI).

Il cuore di #10 (validazione GUI) vive qui, fuori dalla GUI, così è testabile
headless e la vista (a tab) resta sottile. La GUI usa queste funzioni per:

- non crashare su un timeout non numerico (prima `int(...)` sollevava ValueError);
- bloccare START quando manca il token o un'impostazione critica è invalida;
- mostrare messaggi d'errore chiari invece di fallire in silenzio.

Nessuna dipendenza da customtkinter/Telegram/CSV: solo dict di stringhe grezze.
"""

DEFAULT_TIMEOUT = 90

# Tetto massimo del timeout di auto-clear (B2 audit #114): 86400 s = 24 h. Senza tetto,
# `parse_timeout` accettava QUALUNQUE int > 0: un valore enorme (es. 999999999 ≈ 31 anni)
# incollato per sbaglio avrebbe di fatto DISATTIVATO lo svuotamento del CSV, lasciando un
# segnale stantio attivo a vita → rischio scommessa-fantasma (invariante n.5 del repo: «il
# CSV viene svuotato dopo il timeout configurato»). Oltre questo tetto → errore fail-closed.
MAX_TIMEOUT = 86400


def parse_timeout(raw, default: int = DEFAULT_TIMEOUT):
    """Interpreta il timeout di auto-clear (secondi).

    Ritorna ``(valore, errore)``: con `errore=None` `valore` è un int valido;
    altrimenti `valore` è ``None`` ed `errore` è un messaggio. Vuoto → `default`
    (comodo all'avvio). Non numerico o ``<= 0`` → errore (un timeout nullo o
    negativo svuoterebbe il CSV in modo imprevedibile). Oltre ``MAX_TIMEOUT``
    (24 h) → errore (B2 audit #114): un timeout enorme disattiverebbe di fatto lo
    svuotamento, lasciando un segnale stantio a vita.

    SICUREZZA LOG: i messaggi d'errore sono SEMPRE generici e NON includono mai il valore
    grezzo — la GUI li scrive nel log, e l'utente potrebbe aver incollato per sbaglio nel
    campo un bot token (caso non numerico) o un chat ID negativo (caso ``<= 0``), che non
    devono finire in chiaro nei log (Codex #27)."""
    s = str(raw if raw is not None else "").strip()
    if s == "":
        return default, None
    try:
        value = int(s)
    except (TypeError, ValueError):
        # NON includere il valore grezzo nel messaggio: se l'utente incolla per
        # sbaglio un bot token nel campo timeout, finirebbe nel log GUI (invariante:
        # mai token nei log). Messaggio generico.
        return None, "Timeout non valido: inserisci un numero intero di secondi."
    if value <= 0:
        # NON includere il valore nel messaggio: un chat ID NEGATIVO (forma comune di
        # gruppi/canali Telegram, es. -1001234567890) incollato per sbaglio nel campo
        # timeout è numerico, supera `int(...)`, e finirebbe nel log GUI tramite questo
        # ramo. Messaggio generico come per il caso non numerico (invariante: mai
        # identificatori/segreti nei log) — Codex #27.
        return None, "Timeout deve essere un numero intero maggiore di 0 (secondi)."
    if value > MAX_TIMEOUT:
        # Tetto massimo (B2 audit #114): un timeout enorme disattiverebbe di fatto lo
        # svuotamento del CSV (segnale stantio a vita). Messaggio generico e SENZA il
        # valore grezzo, come i rami sopra (stessa invariante: mai valori/segreti nei log).
        # Limite E glossa-ore DERIVATI da `MAX_TIMEOUT` (review Fable/Fugu/GLM/Sourcery
        # PR #116, convergenti): niente «86400» né «24 ore» hardcodati che possano driftare
        # se il tetto cambia.
        return None, (f"Timeout troppo grande: max {MAX_TIMEOUT} secondi "
                      f"({MAX_TIMEOUT // 3600} ore).")
    return value, None


def validate_settings(raw: dict) -> list:
    """Errori **bloccanti** su un dict di impostazioni grezze (come dalla GUI):

    - `csv_path` mancante (senza non si sa dove scrivere i segnali);
    - `clear_delay` non numerico o non positivo.

    Lista vuota = impostazioni avviabili. NON valida il token qui: la presenza
    del token è gestita da `can_start` (un token vuoto disabilita START ma non è
    un "errore" da mostrare in rosso mentre l'utente compila il form)."""
    errors = []
    if not str(raw.get("csv_path", "") or "").strip():
        errors.append("CSV Path mancante: indica il file dove scrivere i segnali.")
    _, timeout_err = parse_timeout(raw.get("clear_delay"))
    if timeout_err:
        errors.append(timeout_err)
    return errors


def can_start(raw: dict) -> bool:
    """True se il bridge può partire: token presente E nessun errore bloccante.
    La GUI la usa per abilitare/disabilitare il pulsante START."""
    if not str(raw.get("bot_token", "") or "").strip():
        return False
    return not validate_settings(raw)
