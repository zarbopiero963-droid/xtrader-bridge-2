"""P3-11 + P3-12 audit #76 — anteprima parser: base bloccata mal etichettata e
falso «mancanti:» sui limiti di prezzo.

- **P3-11** (`parser_builder.preview_rows`): quando l'output multi è attivo ma il
  motore ritorna SOLO la riga base bloccata (`build_validated_rows` → `[base]`),
  l'etichetta `kind` era assegnata per INDICE (`i < n_markets` → "market") → la base
  finiva etichettata «market»/«selection», `test_verdict` prendeva il ramo multi
  (`preview_summary`: solo status aggregato) e il dettaglio «mancanti: <campi>» del
  ramo single-row andava PERSO.
- **P3-12** (`custom_pipeline._validated_multi_row`): QUALSIASI `detail` list/tuple
  del validator finiva in `missing_required` — ma la tupla di `INVALID_PRICE_BOUNDS`
  è l'elenco delle colonne PRESENTI ma incoerenti (Min > Max), non campi mancanti →
  GUI e assistente (#41, `test_message`) mostravano «mancanti: MinPrice» per un
  limite che c'è.

Fix testato: `PipelineResult.base_fallback` marcato dal motore sul solo ritorno
`[base]` bloccante e onorato da `preview_rows` (kind="base"); `missing_required`
riempito SOLO per `INVALID_MISSING_FIELDS` (stessa regola del ramo single-row di
`test_verdict`). Funzioni REALI del progetto, nessuna GUI."""

from xtrader_bridge import custom_pipeline as cpl
from xtrader_bridge import parser_builder as pb
from xtrader_bridge import validator

# Messaggio reale (stesso di test_parser_builder_multirow) e uno SENZA marcatore 🆚.
MSG = (
    "P.Bet. PREMACHT 0,5HT 🔊 ✅\n"
    "🏆Saudi Professional League\n"
    "🆚Al-Kholood Club v Al-Hilal\n"
    "⚽ 0 - 0\n"
    "⌚ 1m\n"
)
MSG_SENZA_EVENTO = "P.Bet. PREMACHT 0,5HT 🔊 ✅\n🏆Saudi Professional League\n⌚ 1m\n"


def _multimarket_builder(**price_rules):
    """Builder REALE con base valida + 2 righe MultiMarket (pattern #192)."""
    b = pb.ParserBuilder()
    b.name = "PreviewFallback"
    b.mode = "NAME_ONLY"
    b.add_rule(target="Provider", fixed_value="PBet")
    b.add_rule(target="EventName", start_after="🆚", end_before="\n", required=True)
    b.add_rule(target="Price", fixed_value=price_rules.get("price", "1.50"), required=True)
    for col in ("MinPrice", "MaxPrice"):
        if col.lower() in price_rules:
            b.add_rule(target=col, fixed_value=price_rules[col.lower()])
    b.add_rule(target="BetType", fixed_value="PUNTA", required=True)
    b.multi_market_enabled = True
    b.add_multi_market(market_type="FIRST_HALF_GOALS_05",
                       market_name="1º tempo - Totale goal 0,5", selection_name="Over 0,5")
    b.add_multi_market(market_type="OVER_UNDER_15", market_name="Totale goal 1,5",
                       selection_name="Over 1,5")
    return b


# ── P3-11: base bloccata → kind "base", non "market" per posizione ───────────────────

def test_base_bloccata_etichettata_base_con_mancanti():
    """FAIL-FIRST: pre-patch la base bloccata (EventName obbligatorio non estratto,
    NON colmabile dalle righe multi) era etichettata kind="market" per indice."""
    rows = _multimarket_builder().preview_rows(MSG_SENZA_EVENTO)

    assert len(rows) == 1                                  # solo la base bloccata
    assert rows[0].kind == "base"                          # NON «market» per posizione
    assert rows[0].placeable is False
    assert "EventName" in rows[0].missing_required         # il dettaglio è conservato


def test_verdetto_base_bloccata_mostra_i_mancanti():
    """FAIL-FIRST: pre-patch il verdetto passava dal ramo multi («⛔ Nessuna delle 1
    righe è piazzabile (NOT_READY)») e i campi «mancanti:» sparivano."""
    b = _multimarket_builder()
    preview = b.preview_rows(MSG_SENZA_EVENTO)
    res = b.test_message(MSG_SENZA_EVENTO)

    verdict = pb.ParserBuilder.test_verdict(
        [], preview, diag_placeable=res.placeable, diag_status=res.status,
        res_row=res.row, res_missing_required=res.missing_required,
        res_detail=res.detail)

    assert "mancanti:" in verdict and "EventName" in verdict
    assert "Nessuna delle" not in verdict                  # niente ramo multi


def test_multi_legittimo_resta_etichettato_market():
    """Regressione bloccata: con la base VALIDA le righe generate restano
    «market» nell'ordine del motore (il tag riguarda SOLO il fallback base)."""
    rows = _multimarket_builder().preview_rows(MSG)

    assert [r.kind for r in rows] == ["market", "market"]
    assert all(r.placeable for r in rows)
    assert not any(getattr(r, "base_fallback", False) for r in rows)


# ── P3-12: INVALID_PRICE_BOUNDS non è «mancanti» ─────────────────────────────────────

def test_limiti_incoerenti_niente_falso_mancanti():
    """FAIL-FIRST: pre-patch le righe multi con Min>Max (colonne PRESENTI ma
    incoerenti) finivano con missing_required=['MinPrice','MaxPrice'] → la GUI
    diceva «mancanti: MinPrice» per un limite che c'è."""
    rows = _multimarket_builder(price="2.5", minprice="3.0",
                                maxprice="2.0").preview_rows(MSG)

    assert rows, "il motore deve generare le righe multi"
    for r in rows:
        assert r.status == validator.INVALID_PRICE_BOUNDS
        assert r.missing_required == []                    # NON sono campi mancanti
    # A livello motore il `detail` resta la tupla delle colonne offendenti (serve
    # alla diagnostica): il fix svuota SOLO `missing_required`, non il dettaglio.
    b = _multimarket_builder(price="2.5", minprice="3.0", maxprice="2.0")
    results = cpl.build_validated_rows(b.to_def(), MSG, mode="NAME_ONLY",
                                       require_price=True)
    assert all(tuple(res.detail) == ("MinPrice", "MaxPrice") for res in results)


def test_missing_fields_resta_in_mancanti():
    """Regressione bloccata: il detail di INVALID_MISSING_FIELDS (veri campi
    mancanti) deve continuare a riempire missing_required delle righe derivate."""
    defn = _multimarket_builder().to_def()
    rule = defn.active_multi_markets()[0]
    base_row = {"Provider": "PBet", "EventName": "A v B", "Price": "1.50",
                "BetType": "PUNTA"}

    res = cpl._validated_multi_row(base_row, rule, "NAME_ONLY", True)
    ok = res.status == validator.VALID
    # La regola market fornisce mercato+selezione: se la riga è valida il caso va
    # costruito togliendo la selezione (regola con solo market_type).
    if ok:
        from dataclasses import replace
        spoglia = replace(rule, selection_name="", market_name="")
        base_senza = dict(base_row)
        base_senza["EventName"] = ""                       # campo nome davvero assente
        res = cpl._validated_multi_row(base_senza, spoglia, "NAME_ONLY", True)

    assert res.status == validator.INVALID_MISSING_FIELDS
    assert res.missing_required == list(res.detail)        # contratto: detail = mancanti
    assert res.missing_required                            # non vuoto
