"""#258 — il semaforo Dizionari non deve mostrare verde su profili mai controllati.

Il controllo delle frasi ambigue (`market_mapping_store.ambiguous_phrase_warnings`) può
**non guardare** un profilo, in due modi diversi e per ottime ragioni di costo:

- **tetto per profilo** (`_MAX_VOCI_CONTROLLO_AMBIGUITA`): oltre quella soglia il controllo
  costerebbe decine di secondi di finestra bloccata all'avvio;
- **budget globale** (`_MAX_VOCI_TOTALI_CONTROLLO`): il costo totale su tutti i profili.

Entrambi sono già **dichiarati** nei messaggi. Ma il semaforo del pannello 🚦 Salute non legge
messaggi: legge uno stato. Se lo derivasse dal solo «quanti conflitti sono stati elencati»,
mostrerebbe **verde** su un profilo che nessuno ha guardato — cioè la rassicurazione senza
copertura che tutta questa serie di PR esiste per togliere.

`profili_non_controllati` è la risposta a quella domanda, e viene dalla **stessa** decisione che
governa gli avvisi (`_piano_controllo_ambiguita`): due copie direbbero, prima o poi, una
«pulito» dove l'altra dice «non controllato».
"""

from xtrader_bridge import market_mapping_store as mms


def _voci(n: int, prefisso: str = "v") -> list:
    """`n` voci mercato valide e tutte distinte fra loro (nessun conflitto di frase)."""
    return [{"phrase": f"{prefisso}{i}", "market_name": f"M{i}", "selection_name": f"S{i}"}
            for i in range(n)]


def test_258_config_piccola_e_sana_non_ha_profili_non_controllati():
    """Il caso normale: tutto viene guardato, quindi non c'è nulla da dichiarare."""
    cfg = {"market_mappings": {"Piccolo": _voci(3)}}
    assert mms.profili_non_controllati(cfg) == []


def test_258_profilo_oltre_il_tetto_PER_PROFILO_e_dichiarato_non_controllato():
    """Il profilo troppo grande: il controllo non viene eseguito, e va detto.

    Senza questa risposta il semaforo direbbe «nessun conflitto» su un profilo di cui non sa
    nulla — peggio del silenzio, perché il silenzio almeno non rassicura.
    """
    grande = mms._MAX_VOCI_CONTROLLO_AMBIGUITA + 1
    cfg = {"market_mappings": {"Enorme": _voci(grande)}}

    assert mms.profili_non_controllati(cfg) == ["Enorme"]

    # …e la risposta è COERENTE con ciò che gli avvisi dicono all'utente: stessa decisione,
    # una fonte sola. Se divergessero, il pannello e il log eventi si contraddirebbero.
    avvisi = mms.ambiguous_phrase_warnings(cfg)
    assert any("controllo NON eseguito su questo profilo" in a for a in avvisi), avvisi
    assert any("«Enorme»" in a for a in avvisi), avvisi


def test_258_profili_saltati_dal_BUDGET_GLOBALE_sono_dichiarati(monkeypatch):
    """L'altro modo di non guardare: il budget complessivo finisce e i profili successivi
    vengono saltati **pur essendo sotto il tetto individuale**."""
    monkeypatch.setattr(mms, "_MAX_VOCI_CONTROLLO_AMBIGUITA", 50)
    monkeypatch.setattr(mms, "_MAX_VOCI_TOTALI_CONTROLLO", 60)
    cfg = {"market_mappings": {"A": _voci(40, "a"), "B": _voci(40, "b")}}

    # A entra (40 ≤ 60), B no (40+40 > 60): l'ordine è per nome normalizzato, deterministico.
    assert mms.profili_non_controllati(cfg) == ["B"]

    avvisi = mms.ambiguous_phrase_warnings(cfg)
    assert any("budget complessivo" in a and "«B»" in a for a in avvisi), avvisi


def test_258_il_tetto_per_profilo_NON_consuma_il_budget_dei_successivi(monkeypatch):
    """Contro-guardia sull'ordine dei due tetti — l'invariante che la #261 ha corretto.

    Un profilo oltre il tetto individuale non viene esaminato, quindi **non deve** scalare il
    proprio peso dal budget: se lo facesse, farebbe saltare profili successivi *sani* con un
    «budget esaurito» che non è vero. Qui il profilo enorme viene escluso dal tetto e quello
    piccolo, che nel budget ci sta comodamente, deve restare controllato.
    """
    monkeypatch.setattr(mms, "_MAX_VOCI_CONTROLLO_AMBIGUITA", 50)
    monkeypatch.setattr(mms, "_MAX_VOCI_TOTALI_CONTROLLO", 60)
    cfg = {"market_mappings": {"AEnorme": _voci(100, "x"), "BPiccolo": _voci(10, "y")}}

    non_controllati = mms.profili_non_controllati(cfg)

    assert "AEnorme" in non_controllati, "il profilo oltre il tetto non è stato dichiarato"
    assert "BPiccolo" not in non_controllati, (
        "il profilo piccolo è stato saltato: il peso di un profilo MAI esaminato ha consumato "
        "il budget, ed è il difetto corretto dalla #261")


def test_258_config_malformata_non_solleva():
    """Fail-safe come le funzioni di avviso sorelle. La config è un file editabile a mano, e
    questa funzione viene interrogata dal pannello Salute all'apertura della finestra: se
    sollevasse, un dizionario manomesso spegnerebbe la diagnostica invece di descriverla."""
    for cfg in ({}, {"market_mappings": None}, {"market_mappings": {"A": "non-una-lista"}},
                {"market_mappings": {"A": [None, 3, "x"]}}, {"market_mappings": {3: [{}]}}):
        assert mms.profili_non_controllati(cfg) == [] or isinstance(
            mms.profili_non_controllati(cfg), list), cfg


def test_258_chiavi_di_tipo_misto_non_sollevano_TypeError():
    """Regressione diretta della #261: `sorted()` sulle chiavi grezze solleva `TypeError` se la
    config mescola tipi. Questa funzione condivide quell'ordinamento, quindi eredita il rischio
    — e il pannello Salute la chiama all'apertura della finestra, senza try/except."""
    cfg = {"market_mappings": {"A": [{"phrase": "p", "market_name": "M", "selection_name": "S"}],
                               3: [{"phrase": "q", "market_name": "M", "selection_name": "S"}]}}
    assert isinstance(mms.profili_non_controllati(cfg), list)
