"""#258 — stato dei dizionari per il semaforo della tab 🚦 Salute.

Le #253, #255 e #257 hanno reso il bridge capace di **dire** che un dizionario ha conflitti, ma
lo dice solo nel log eventi allo START. Chi non guarda il log continua a vedere segnali che
spariscono senza spiegazione: un conflitto non è un errore di configurazione qualunque, è un
segnale che il bridge **scarta invece di piazzare** (fail-closed — meglio perso che sbagliato).

Questo modulo porta quell'informazione dove l'utente guarda davvero, con due regole che ne
determinano l'onestà.

**1. Conta solo ciò che costa segnali.** Un conflitto in un profilo che nessun parser usa non fa
perdere nulla. Perciò la gravità si calcola sui **profili in uso**, non sul totale: un profilo
orfano con cinquanta conflitti resta un avviso giallo di igiene, non un allarme rosso.

**2. «Non controllato» non è «pulito».** Il controllo delle frasi ambigue può saltare interi
profili (tetto per profilo, budget globale — vedi `market_mapping_store`), per ottime ragioni di
costo. Su quei profili l'assenza di conflitti elencati **non** significa che siano sani: nessuno
ha guardato. Derivare il verde dal solo conteggio dei conflitti sarebbe una rassicurazione senza
copertura, cioè il difetto stesso che questa diagnostica esiste per togliere. Quel caso ha un
colore proprio, e lo dice.

Niente logica di detection riscritta: le quattro funzioni di avviso sono quelle che il bridge usa
allo START. Se il bridge tacesse su un conflitto, tacerebbe anche qui — e sarebbe un difetto del
bridge, non una divergenza fra i due.
"""

import logging
import os

from xtrader_bridge import health_check
from xtrader_bridge import market_mapping_store as mms
from xtrader_bridge import name_mapping_store as nms

_LOG = logging.getLogger(__name__)

# Quanti conflitti elencare nel pannello. Il resto si dichiara («…e altri N»), mai si tronca in
# silenzio: la stessa convenzione che `market_mapping_store` già applica ai suoi avvisi. Un cap
# muto si legge come «non ce ne sono altri».
MAX_DETTAGLI = 8


def _sotto_config(cfg: dict, chiave: str, profili) -> dict:
    """`cfg` ridotta ai soli `profili` sotto `chiave`, per interrogare le funzioni di avviso.

    Serve perché gli avvisi sono **stringhe formattate**: dedurre da esse a quale profilo
    appartiene un conflitto vorrebbe dire fare il parsing di un messaggio di interfaccia, e
    quel messaggio cambia (in questa serie di PR è cambiato tre volte). Restringere l'ingresso
    è invece esatto per costruzione.
    """
    store = cfg.get(chiave) if isinstance(cfg, dict) else None
    if not isinstance(store, dict):
        return {chiave: {}}
    voluti = {str(p or "").strip() for p in profili}
    return {chiave: {k: v for k, v in store.items() if str(k or "").strip() in voluti}}


def profili_usati(cartella: "str | None" = None, *, elenca=None, carica=None) -> dict:
    """I profili nomi/mercati che i parser su disco dichiarano davvero di usare.

    Ritorna ``{"nomi": set, "mercati": set, "illeggibili": [nomi file]}``.

    **`list_parser_files` + `load_parser`, non `load_all_parsers`**: quest'ultima risolve il
    parser *attivo per chat* e darebbe una vista parziale — un profilo usato solo da un parser
    non attivo risulterebbe orfano, e i suoi conflitti verrebbero declassati a gialli mentre
    costano segnali davvero.

    Fail-safe a due livelli, perché il pannello Salute la chiama all'apertura della finestra:
    una cartella illeggibile dà insiemi vuoti, e un singolo parser corrotto (`ValueError`) o
    inaccessibile (`OSError`) viene **contato fra gli illeggibili** invece di far cadere tutto.
    Gli illeggibili non si nascondono: un parser che non si riesce a leggere è un parser di cui
    non si sa quali profili usi, e chi legge il semaforo deve saperlo.
    """
    from xtrader_bridge import custom_parser as cp

    elenca = elenca or cp.list_parser_files
    carica = carica or cp.load_parser
    nomi, mercati, illeggibili = set(), set(), []
    # **Non si cattura l'OSError** (bloccante Fable 5 sulla PR #276). Una prima stesura tornava
    # una vista vuota «per non far cadere il pannello»: senza profili in uso non c'erano
    # conflitti da attribuire, e il semaforo mostrava 🟢 «nessun conflitto sui profili in uso»
    # con la cartella dei parser **illeggibile**. Verde dedotto da un errore, e per giunta in
    # contraddizione col design handoff di questa stessa PR, che promette 🟡 «non calcolabile».
    #
    # Ora l'errore sale al confine unico (`App._dizionari_cached`) che mostra il giallo. Nota:
    # una cartella *inesistente* non solleva — `list_parser_files` torna `[]` di proposito, ed è
    # corretto: nessun parser configurato è uno stato noto, non un'incognita.
    percorsi = elenca(cartella) if cartella else elenca()

    for percorso in percorsi or []:
        try:
            definizione = carica(percorso)
        except (ValueError, OSError) as exc:    # contratto di `load_parser` (B9): corrotto | accesso
            _LOG.warning("Parser non leggibile [%s]", type(exc).__name__)
            illeggibili.append(os.path.basename(str(percorso)))
            continue
        nomi.update(str(p or "").strip()
                    for p in (getattr(definizione, "name_mapping_profiles", None) or []))
        mercati.update(str(p or "").strip()
                       for p in (getattr(definizione, "market_mapping_profiles", None) or []))
    nomi.discard("")
    mercati.discard("")
    return {"nomi": nomi, "mercati": mercati, "illeggibili": illeggibili}


def _conflitti(cfg: dict, chiave: str, funzioni) -> list:
    """Gli avvisi delle `funzioni` sulla `cfg` data.

    **Non cattura nulla** (rilievo CodeRabbit sulla PR #276). Una prima stesura avvolgeva ogni
    chiamata in un blind-except «per non bloccare il pannello», ma il pannello ha già il suo
    confine fail-safe — `App._dizionari_cached`, che su errore mostra il giallo «stato non
    calcolabile». Tre catture silenziose a monte di quell'unico confine non aggiungevano
    protezione: toglievano informazione, perché un guasto in una delle quattro funzioni sarebbe
    diventato un risultato **parziale spacciato per completo** invece di un «non lo so» onesto.
    """
    fuori = []
    for f in funzioni:
        fuori.extend(f(cfg) or [])
    return fuori


def stato_dizionari(cfg: dict, usati: "dict | None" = None) -> dict:
    """Stato del semaforo Dizionari. Ritorna ``{"stato", "titolo", "dettagli", "nascosti"}``.

    `stato` è uno di `health_check.GREEN/YELLOW/RED`. Il criterio, in ordine di precedenza:

    - **🔴** almeno un conflitto su un profilo che un parser usa davvero → stai perdendo segnali
      adesso, ogni volta che quel nome o quella frase compare;
    - **🟡 controllo incompleto** — un profilo in uso non è stato esaminato (tetto/budget): non
      si sa, e dirlo è l'unica risposta onesta. **Non** è verde: l'assenza di conflitti elencati
      su un profilo mai guardato non è una promessa;
    - **🟡 conflitti solo su profili orfani** — nessun parser li usa, nessun segnale perso, ma il
      dizionario è sporco e domani quel profilo potrebbe essere collegato a un parser;
    - **🟡 parser illeggibili** — non si sa quali profili usino, quindi non si può escludere che
      un conflitto li tocchi;
    - **🟢** controllo completo, nessun conflitto sui profili in uso.

    Non c'è soglia numerica, e non è una semplificazione: la gravità di un conflitto non dipende
    da quanti sono ma da **se un parser usa quel profilo**. Una soglia tarata a mano sarebbe da
    ritarare a ogni dizionario, e nel frattempo direbbe una cosa diversa da quella che succede.
    """
    if not isinstance(cfg, dict):
        cfg = {}
    if usati is None:
        usati = profili_usati()

    nomi_usati = set(usati.get("nomi") or ())
    mercati_usati = set(usati.get("mercati") or ())
    illeggibili = list(usati.get("illeggibili") or ())

    # Il piano di controllo si calcola sulla config **INTERA**, come allo START (rilievo Fable 5
    # sulla PR #276). Il budget globale è globale: ricalcolarlo sulla sotto-config dei soli
    # profili in uso ne libererebbe, e il pannello esaminerebbe un profilo che allo START è
    # stato saltato — dicendo «controllato» dove il log eventi dice «NON controllato». Nessun
    # falso verde, ma due diagnostiche che si contraddicono sullo stesso profilo, e chi le
    # confronta non ha modo di sapere a quale credere.
    non_controllati_ovunque = set(mms.profili_non_controllati(cfg))

    cfg_nomi_usati = _sotto_config(cfg, "name_mappings", nomi_usati)
    cfg_mkt_usati = _sotto_config(cfg, "market_mappings",
                                  mercati_usati - non_controllati_ovunque)

    # Sui mercati si interrogano SOLO i profili che il controllo esaminerebbe davvero: così la
    # parte `struttura` degli avvisi è vuota e ciò che resta sono conflitti, non «non so».
    su_usati = (_conflitti(cfg_nomi_usati, "name_mappings",
                           (nms.ambiguous_alias_warnings, nms.malformed_entry_warnings))
                # `malformed_entry_warnings` NON ha tetti: è sempre completo, quindi va
                # chiesto su TUTTI i profili in uso (2° bloccante Fugu Ultra sulla PR #276).
                # Escluderlo insieme all'ambiguità declassava a 🟡 «non controllato» un profilo
                # con righe malformate REALI — segnali scartati adesso — nascondendo un
                # conflitto **noto** dietro un «non so». Il «non so» vale per ciò che non è
                # stato guardato, non per ciò che è stato guardato e trovato.
                + _conflitti(_sotto_config(cfg, "market_mappings", mercati_usati),
                             "market_mappings", (mms.malformed_entry_warnings,))
                + _conflitti(cfg_mkt_usati, "market_mappings",
                             (mms.ambiguous_phrase_warnings,)))
    # Short-circuit (rilievo Fugu Ultra sulla PR #276): `totali` serve SOLO a distinguere
    # «conflitti su profili orfani» da «pulito», cioè quando `su_usati` è vuoto. Calcolarlo
    # comunque significava una seconda passata completa su TUTTI i profili — costo quadratico
    # nel controllo frasi — proprio nel caso in cui il rosso è già deciso. Sul thread Tk, e a
    # ogni scadenza del TTL.
    totali = [] if su_usati else (_conflitti(cfg, "name_mappings",
                         (nms.ambiguous_alias_warnings, nms.malformed_entry_warnings))
              + _conflitti(
                  _sotto_config(cfg, "market_mappings",
                                {str(k or "").strip()
                                 for k in (cfg.get("market_mappings") or {})}
                                - non_controllati_ovunque),
                  "market_mappings",
                  (mms.ambiguous_phrase_warnings, mms.malformed_entry_warnings)))

    # L'incompletezza che conta è quella **sui profili in uso**: un profilo orfano non
    # controllato non costa segnali, quindi non deve accendere l'avviso «non so».
    non_controllati = sorted(non_controllati_ovunque & mercati_usati)

    if su_usati:
        stato = health_check.RED
        titolo = (f"{len(su_usati)} conflitti su profili usati dai tuoi parser: "
                  f"i segnali che li toccano vengono SCARTATI")
        dettagli = su_usati
    elif non_controllati:
        stato = health_check.YELLOW
        titolo = (f"controllo NON eseguito su {len(non_controllati)} profili in uso "
                  f"({', '.join(f'«{p}»' for p in non_controllati)}): non si sa se abbiano "
                  f"conflitti — riducili o dividili per farli rientrare nel tetto")
        dettagli = []
    elif illeggibili:
        stato = health_check.YELLOW
        titolo = (f"{len(illeggibili)} parser non leggibili "
                  f"({', '.join(illeggibili)}): non si sa quali profili usino")
        dettagli = []
    elif totali:
        stato = health_check.YELLOW
        titolo = (f"{len(totali)} conflitti, ma solo su profili che NESSUN parser usa: "
                  f"nessun segnale perso oggi")
        dettagli = totali
    else:
        stato = health_check.GREEN
        titolo = "nessun conflitto sui profili in uso"
        dettagli = []

    nascosti = max(0, len(dettagli) - MAX_DETTAGLI)
    return {"stato": stato, "titolo": titolo,
            "dettagli": list(dettagli[:MAX_DETTAGLI]), "nascosti": nascosti}
