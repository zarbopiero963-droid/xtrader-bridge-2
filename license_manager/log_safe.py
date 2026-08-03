"""Logger del License Manager con redazione dei segreti **per costruzione** (#215 seguito).

## Il problema che chiude

Il License Manager maneggia il **token GitHub** della pubblicazione revoche. Fino ad ora la sua
unica difesa contro un token finito in un file di log era una **convenzione**: loggare soltanto
`type(exc).__name__`, mai il testo dell'eccezione — ripetuta a mano in **31 punti** del package,
con commenti espliciti lasciati dalle review («solo il tipo», «mai il messaggio»).

La convenzione è corretta e ha retto. Ma è un'abitudine da ricordare a ogni chiamata: basta un
`_log.warning("... %s", exc)` scritto distrattamente — o un `exc_info=True` aggiunto in buona fede
per rendere diagnosticabile un guasto — per perderla **in silenzio**, e il difetto si vede solo
quando il token è già nel file che l'utente ha allegato a una segnalazione.

Qui la difesa diventa un **meccanismo del percorso di log**: il record passa comunque per
`event_log.redact_secrets` prima di raggiungere qualunque handler. La convenzione resta la prima
linea; questa è la rete sotto, per quando qualcuno la dimentica.

## Cosa copre, e cosa no (onestamente)

Copre il **messaggio formattato** (`msg % args`, quindi anche un segreto passato come argomento)
e il **traceback** di `exc_info`, che viene reso in testo, redatto e accodato al messaggio —
altrimenti sfuggirebbe, perché il traceback lo formatta l'handler **dopo** i filtri.

Non copre ciò che `redact_secrets` stesso non riconosce: il limite residuo è documentato lì. Per
questo il token viene anche **registrato** come literal (`publish_store`), che copre le forme che
nessuna regex può conoscere — un vecchio token OAuth a 40 hex è indistinguibile da uno SHA git.

## Nota

Non tocca il logging **globale** dell'applicazione: agisce solo sui logger dei moduli che passano
di qui, quindi non cambia il comportamento del bridge né della configurazione dell'utente.
"""

from __future__ import annotations

import logging
import traceback

from xtrader_bridge import event_log

# Marcatore per non impilare più filtri sullo stesso logger: `get_logger` è chiamato a ogni
# import di modulo, e in un test anche più volte sullo stesso nome.
_MARCATORE = "_xtrader_redazione_installata"


class RedazioneFilter(logging.Filter):
    """Riscrive il record perché il testo che arriva agli handler sia già redatto.

    Riscrive `msg` (e azzera `args`) invece di lasciare la sostituzione al formatter: il
    formatter gira **una volta per handler**, il filtro **una volta per record**, quindi qui la
    redazione è fatta una volta sola e nessun handler può vedere la forma in chiaro.

    Non solleva mai: un filtro che esplode farebbe cadere una chiamata di log, cioè
    trasformerebbe un problema di diagnostica in un guasto dell'applicazione."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            testo = record.getMessage()
        except Exception:       # noqa: BLE001 — args incoerenti: meglio il grezzo che nessun log
            testo = str(getattr(record, "msg", ""))
        if record.exc_info:
            # Il traceback lo renderebbe l'handler DOPO i filtri: se lo lasciassimo lì passerebbe
            # in chiaro. Lo rendiamo qui, lo accodiamo al messaggio e togliamo `exc_info` così
            # non venga stampato una seconda volta non redatto.
            try:
                testo += "\n" + "".join(traceback.format_exception(*record.exc_info))
            except Exception:   # noqa: BLE001 — traceback non formattabile: si dice, non si perde
                testo += "\n[traceback non disponibile]"
            record.exc_info = None
            record.exc_text = None
        try:
            record.msg = event_log.redact_secrets(testo)
        except Exception:       # noqa: BLE001 — mai far cadere una chiamata di log
            record.msg = "[messaggio non redigibile: omesso per sicurezza]"
        record.args = ()
        return True


def get_logger(name: str) -> logging.Logger:
    """Il logger `name` con la redazione dei segreti installata (idempotente).

    Sostituisce `logging.getLogger(__name__)` nei moduli del License Manager. Il filtro va sul
    **logger** e non su un handler perché gli handler qui non li configuriamo noi: sono quelli
    dell'applicazione ospite, e un domani potrebbero essere altri."""
    logger = logging.getLogger(name)
    if not getattr(logger, _MARCATORE, False):
        logger.addFilter(RedazioneFilter())
        setattr(logger, _MARCATORE, True)
    return logger
