"""P3-15 audit #76 — RIMOZIONE del modulo P.Bet hardcoded (decisione del proprietario).

`xtrader_bridge/parser.py` (~390 righe, `parse_message` + regex P.Bet) era fuori dal
flusso live da CP-09b (senza Parser Personalizzato attivo il messaggio è IGNORATO)
ma restava nel repo «per compatibilità/test»: codice morto attivo, superficie di
manutenzione e ambiguità («quale parser gira?»). Rimosso.

Guardia anti-reintroduzione (fail-first: ROSSA prima della rimozione):
- il modulo NON deve più esistere né essere importabile;
- l'invariante live resta: nessun custom attivo → messaggio ignorato, nessuna riga
  (era già il comportamento CP-09b, qui pinnato dopo la rimozione)."""

import importlib

import pytest

from xtrader_bridge import signal_router


def test_modulo_parser_rimosso():
    """FAIL-FIRST: prima della rimozione l'import riusciva (modulo morto attivo)."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("xtrader_bridge.parser")


def test_live_senza_custom_resta_ignorato(tmp_path):
    """L'invariante CP-09b sopravvive alla rimozione: nessun parser custom attivo →
    il messaggio (formato P.Bet reale) NON produce righe — ignorato, non parsato
    da alcun hardcoded."""
    res = signal_router.resolve_row(
        "P.Bet. OVER 2.5 LIVE\nInter v Milan\nQuota 1,85",
        {}, parsers_dir=str(tmp_path))

    assert res.row is None
    assert res.status == signal_router.NO_PARSER
    assert res.detail == "no_active_parser"


# ── Residuo P.Bet: nome del parser d'esempio e docs disallineate (#219) ──────────────────────

def test_il_parser_d_esempio_non_si_chiama_come_un_parser_RIMOSSO():
    """Il parser d'esempio spedito col prodotto si chiamava «Esempio P.Bet.», ma non ha nulla a
    che vedere con quel formato: legge `Match:` / `Esito:` / `Quota:` / `Lato:` su un messaggio
    `Inter v Milan`. Il nome prometteva un parser per i messaggi P.Bet e ne consegnava un altro —
    e per giunta citava un componente **rimosso** dal repo (#76 P3-15).

    Fail-first: prima della correzione il nome era `"Esempio P.Bet."` e questo test era rosso."""
    from xtrader_bridge import parser_io

    nome = parser_io.example_parser().name
    assert "P.Bet" not in nome and "PBet" not in nome, (
        f"il parser d'esempio si chiama {nome!r}: cita un parser che non esiste più")
    # e deve dire cosa fa davvero, cioè nominare TUTTI i campi che legge (rilievo CodeRabbit
    # #220): con `any` un nome come «Esempio: Quota» sarebbe passato pur descrivendo un quarto
    # del parser — l'asserzione prometteva «dice cosa fa» e verificava «dice qualcosa».
    mancanti = [c for c in ("Match", "Esito", "Quota", "Lato") if c not in nome]
    assert not mancanti, (
        f"il nome {nome!r} non nomina i campi che il parser legge: mancano {mancanti}")


def test_nessuna_doc_DICHIARA_che_il_parser_hardcoded_esiste_ancora():
    """`docs/custom_parser.md` affermava: «Il parser hardcoded P.Bet **resta nel repo** solo per
    compatibilità/test». Era **falso** dal #76: `xtrader_bridge/parser.py` non esiste più, e lo
    verifica `test_modulo_parser_rimosso` qui sopra.

    Una doc che dichiara presente un componente rimosso è la stessa classe di difetto inseguita
    nelle #216/#217: un'affermazione che non corrisponde al fatto, e che nessuno smentisce finché
    qualcuno non va a cercare quel file. L'archivio audit è escluso: lì la frase è registro
    storico, ed era vera quando è stata scritta.

    Fail-first: prima della correzione questo test era rosso su `docs/custom_parser.md`."""
    import pathlib
    import re

    radice = pathlib.Path(__file__).resolve().parents[2]
    # «resta nel repo» / «è nel repo» / «presente nel repo» in una riga che nomina P.Bet
    # Richiede la parola «parser» oltre a «P.Bet»: il FORMATO P.Bet esiste eccome (è il
    # formato dei messaggi del proprietario) e una frase legittima come «il formato P.Bet resta
    # nel repo come esempio» non deve far fallire il gate. A essere rimosso è il *parser*.
    bugia = re.compile(r"parser.{0,60}P\.?Bet.{0,60}(resta|rimane|è|e')\s+(ancora\s+)?(nel|in)\s+repo"
                       r"|P\.?Bet.{0,40}parser.{0,60}(resta|rimane)\s+(nel|in)\s+repo",
                       re.IGNORECASE)
    colpevoli = []
    for doc in sorted(radice.glob("docs/**/*.md")) + [radice / "README.md"]:
        if "archive" in doc.parts:
            continue                      # registro storico: era vero quando fu scritto
        for n, riga in enumerate(doc.read_text(encoding="utf-8").splitlines(), 1):
            if bugia.search(riga):
                colpevoli.append(f"{doc.relative_to(radice)}:{n} — {riga.strip()[:90]}")

    assert not colpevoli, (
        "documentazione che dichiara ancora presente il parser hardcoded RIMOSSO (#76 P3-15):\n  "
        + "\n  ".join(colpevoli))


def test_un_parser_salvato_col_VECCHIO_nome_continua_a_funzionare(tmp_path):
    """Rilievo GPT-5.5 sulla #220, su cui i reviewer si contraddicevano.

    GPT-5.5: «il nome è usato come chiave in `parser_by_chat`; rinominarlo può essere una
    regressione per utenti che hanno salvato parser/config con il vecchio nome».
    Fable 5: «il rename non impatta i parser già salvati, il nome è solo il default alla
    creazione».

    Ha ragione Fable, e questo test lo dimostra invece di sostenerlo: `example_parser()` è una
    **fabbrica** che produce una definizione nuova, non un registro di nomi. Un parser già su
    disco porta il proprio nome dentro il file, e `parser_by_chat` lo risolve per quel nome —
    che il default di fabbrica sia cambiato non lo riguarda.

    È la verifica che il rename non tocchi la catena Telegram → parser → CSV per chi ha già
    configurato il bridge: l'unica cosa che renderebbe questa PR pericolosa."""
    from xtrader_bridge import custom_parser as cp
    from xtrader_bridge import parser_io, signal_router

    # un utente che aveva importato l'esempio PRIMA del rename
    vecchio = parser_io.example_parser()
    vecchio.name = "Esempio P.Bet."
    cp.save_parser(vecchio, str(tmp_path))

    cfg = {"provider": "TG", "recognition_mode": "NAME_ONLY",
           "parser_by_chat": {"111": "Esempio P.Bet."}}
    res = signal_router.resolve_row(parser_io.fixture_message(), cfg,
                                    parsers_dir=str(tmp_path), chat_id="111")
    assert res.placeable, (
        f"un parser salvato col vecchio nome non produce più una riga piazzabile: "
        f"REGRESSIONE — status={res.status!r} source={res.source!r}")
    assert res.source == signal_router.CUSTOM, res.source
    assert res.row["EventName"] == "Inter v Milan", res.row
