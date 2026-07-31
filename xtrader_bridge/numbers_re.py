"""Frammenti regex condivisi per i numeri decimali (fonte unica — anti-drift, audit L4).

Quattro moduli (`parser`, `validator`, `custom_pipeline`, `csv_writer`) ripetevano lo
stesso frammento ``[0-9]+(?:[.,][0-9]+)?``: una modifica in uno e non negli altri avrebbe
fatto divergere il riconoscimento dei numeri (quota/Handicap/Price). Qui sta una sola volta;
ogni modulo compone àncore (``^…$``) e segno come gli serve. Modulo foglia: importa solo
``math`` dalla stdlib, nessun modulo del progetto → nessun rischio di ciclo.

Oltre ai frammenti, qui vive `valore_finito`: la **conversione** sicura di un decimale che
ha già superato una di queste regex (B5, #194). Regex e conversione stanno insieme perché
sono due metà della stessa domanda, e separarle è esattamente come è nato B5.

Le cifre sono ASCII ``[0-9]`` e NON ``\\d`` (vedi `DECIMAL`): `\\d` matcherebbe le cifre
Unicode, aprendo il fail-open #318 L2-1.
"""

import math

# Numero decimale "puro": cifre con AL PIÙ una parte decimale separata da `.` o `,`
# (niente "1.2.3"/esponenti). Senza segno.
#
# Cifre ASCII SOLTANTO (`[0-9]`, NON `\d`): #318 L2-1 (fail-OPEN). In Python `\d` matcha
# TUTTE le cifre Unicode (arabo-indiane «١٩», devanagari «१९», fullwidth «１９»); poiché
# `float("١٩") == 19.0`, un Price/Handicap/Points scritto con cifre non-ASCII superava la
# validazione ed entrava nel CSV letto da XTrader (raggiungibile da un vero messaggio
# Telegram via parser custom). `[0-9]` chiude il buco fail-closed su TUTTI i consumer
# (validator/custom_pipeline/csv_writer/parser) da questa fonte unica.
#
# I frammenti sono RACCHIUSI in un gruppo non catturante `(?:…)` (rilievo Fable 5 + GPT-5.5 su
# #198). Cinque siti li compongono con le ancore — `signal_dedupe._HANDICAP_NUM`,
# `validator._SIGNED_DECIMAL_RE`, `validator._DECIMAL_PRICE` — scrivendo `r"^" + FRAMMENTO + r"$"`.
# Finché il frammento non ha alternanze di primo livello quella composizione è corretta, ma il
# giorno in cui qualcuno aggiungesse un ramo `|` le ancore si legherebbero a UN SOLO ramo e
# `^[+-]?[0-9]+…|INF$` accetterebbe «12abc»: un Price/Handicap spurio superarebbe la validazione
# ed entrerebbe nel CSV letto da XTrader. Fail-OPEN silenzioso, la stessa famiglia di #318 L2-1.
# Il gruppo qui rende la composizione sicura PER COSTRUZIONE in tutti i consumer, presenti e
# futuri, invece di ripetere `(?:…)` in ogni sito (che sarebbe la stessa duplicazione che questo
# modulo esiste per eliminare). Non cattura nulla: nessuna numerazione di gruppi cambia.
DECIMAL = r"(?:[0-9]+(?:[.,][0-9]+)?)"

# Come `DECIMAL` ma con segno opzionale (es. Handicap "-1"/"+1,5", Price "1.85").
# COMPOSTO da `DECIMAL` (non riscritto a mano) così un futuro cambio a `DECIMAL` non può
# divergere qui — l'anti-drift vale anche dentro il modulo (review Fable 5 su #318).
SIGNED_DECIMAL = r"(?:[+-]?" + DECIMAL + r")"


def valore_finito(testo):
    """Il `float` di un decimale che ha GIÀ superato `DECIMAL`/`SIGNED_DECIMAL`, oppure
    ``None`` se non è finito. Fonte unica della conversione (B5, #194).

    **Perché serve, se la regex ha già filtrato.** La regex accetta solo cifre ASCII e al
    più un separatore: per via *testuale* `inf`/`nan` non possono passare (niente «inf»,
    niente esponenti «1e400»). Ma una stringa di **sole cifre** abbastanza lunga sì —
    ``float("9" * 400)`` è ``inf``. Superata la regex, il valore entrava nei confronti di
    soglia, e lì l'infinito passa **nel verso sbagliato**: ``inf <= 0.0`` è ``False``,
    quindi un tetto scritto come «rifiuta se ≤ 0» diceva VALID all'infinito. È B5, e la
    correzione non è un confronto in più ma un controllo di **finitezza esplicito**.

    La virgola è normalizzata a punto perché le regex di questo modulo accettano
    entrambi i separatori mentre `float()` capisce solo il punto (la stessa asimmetria
    che aveva già morso `signal_dedupe._canonical_handicap` su #198).

    Restituisce ``None`` anche per un testo non convertibile, così un chiamante che
    saltasse la regex resta comunque fail-closed invece di sollevare.
    """
    try:
        numero = float(str(testo).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return numero if math.isfinite(numero) else None
