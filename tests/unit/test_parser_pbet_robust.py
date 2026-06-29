"""Test del parser robusto P.Bet. (PR-09): emoji + testo, fixtures reali."""

import os

from xtrader_bridge.parser import _is_odds, parse_message


def test_is_odds_rifiuta_inf_e_nan():
    """#184 low-isodds-inf: `float("inf") > 1.0` è True, quindi senza `math.isfinite` un valore non
    finito verrebbe scambiato per una quota valida. inf/nan → False; quote normali invariate.

    Fail-first: sul vecchio codice `_is_odds("inf")` ritornava True."""
    for bad in ("inf", "-inf", "Infinity", "nan", "NaN"):
        assert _is_odds(bad) is False
    # comportamento invariato sui valori reali: quota > 1.0 True, linea/quota piena False.
    assert _is_odds("1.85") is True
    assert _is_odds("2") is True
    assert _is_odds("1.0") is False
    assert _is_odds("0.5") is False
    assert _is_odds("abc") is False

_FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures", "pbet_messages")


def _fixture(name):
    with open(os.path.join(_FIX, name), encoding="utf-8") as f:
        return f.read()


def test_emoji_completo():
    p = parse_message(_fixture("valid_match_odds_emoji.txt"))
    assert p["signal_type"] == "MATCH ODDS"
    assert p["teams"] == "Inter v Milan"
    assert p["quota"] == "1.85"
    assert p["probability"] == "72.5"
    assert p["bet_type"] == "BACK"


def test_testo_semplice_equivalente_a_emoji():
    p = parse_message(_fixture("valid_over25_text.txt"))
    assert p["signal_type"] == "OVER 2.5"
    assert p["teams"] == "Inter v Milan"        # "Inter vs Milan" normalizzato
    assert p["quota"] == "1.85"
    assert p["probability"] == "72.5"


def test_signal_type_emoji_in_coda_rimossa():
    """#184 low-parser-emoji: un'emoji finale FUORI dal set noto `🔊✅🔇` (es. 🔥🚀⚽) restava nel
    signal_type → l'alias non combaciava con la value-map (segnale scartato). Va rimossa, lasciando
    l'alias pulito.

    Fail-first: sul vecchio codice `signal_type` includeva l'emoji finale (es. 'OVER 2.5 🔥')."""
    assert parse_message("P.Bet. OVER 2.5 🔥")["signal_type"] == "OVER 2.5"
    assert parse_message("P.Bet. OVER 2.5 🚀")["signal_type"] == "OVER 2.5"
    assert parse_message("P.Bet. GOL SECONDO TEMPO ⚽")["signal_type"] == "GOL SECONDO TEMPO"
    # emoji + variation selector, e combinazione con un token di stato (in entrambi gli ordini).
    assert parse_message("P.Bet. GG/NG ✅️")["signal_type"] == "GG/NG"
    assert parse_message("P.Bet. OVER 2.5 LIVE 🔥")["signal_type"] == "OVER 2.5"
    assert parse_message("P.Bet. OVER 2.5 🔥 LIVE")["signal_type"] == "OVER 2.5"


def test_signal_type_senza_emoji_invariato():
    """#184 low-parser-emoji: senza emoji finale il signal_type resta intatto (niente over-strip dei
    caratteri legittimi dell'alias: lettere/cifre/`.`/`/`)."""
    assert parse_message("P.Bet. OVER 2.5")["signal_type"] == "OVER 2.5"
    assert parse_message("P.Bet. 1X2")["signal_type"] == "1X2"
    assert parse_message("P.Bet. GG/NG")["signal_type"] == "GG/NG"
    # marker noto già escluso dalla regex: comportamento invariato.
    assert parse_message("P.Bet. OVER 2.5 🔊")["signal_type"] == "OVER 2.5"


def test_plaintext_v_e_banca():
    p = parse_message(_fixture("valid_gg_text.txt"))
    assert p["signal_type"] == "GG"
    assert p["teams"] == "Arsenal v Chelsea"
    assert p["quota"] == "1.95"
    assert p["bet_type"] == "LAY"                # riga "Banca" -> LAY


def test_separatori_normalizzati():
    assert parse_message("P.Bet. 1\nInter vs Milan")["teams"] == "Inter v Milan"
    assert parse_message("P.Bet. 1\nInter v Milan")["teams"] == "Inter v Milan"
    # Il trattino è ammesso solo con l'emoji 🆚 (conferma che è la riga squadre).
    assert parse_message("P.Bet. 1\n🆚 Inter - Milan")["teams"] == "Inter v Milan"
    # In testo libero il trattino NON viene preso (ambiguo): squadre vuote.
    assert parse_message("P.Bet. 1\nInter - Milan")["teams"] == ""


def test_bet_type_solo_da_riga_lato():
    # "Lay" dentro un nome squadra NON deve forzare il lato (P1 wrong-side).
    assert parse_message("P.Bet. OVER 2.5\nInter v Lay Town\nQuota 1,85")["bet_type"] == "BACK"
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nBanca")["bet_type"] == "LAY"
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nPunta")["bet_type"] == "BACK"


def test_bet_type_tokenizza_lettere_unicode():
    # audit L5: il riconoscimento della riga-lato tokenizza per LETTERE Unicode `[^\W\d_]`
    # (non più la classe accentata ristretta `[a-zàèéìòù]`). Le parole-lato restano
    # riconosciute (regressione della modifica) e una parola con accento NON-italiano resta
    # UN solo token: niente split che con la classe ristretta poteva far saltare la
    # riga-lato e lasciare per sbaglio il default BACK su un segnale LAY.
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nBanca")["bet_type"] == "LAY"
    # "Lay" con accento non-italiano accanto (es. una nota "Layür") resta un nome a due+
    # token → non forza il lato (default BACK), senza spezzare in modo da matchare "lay".
    assert parse_message("P.Bet. OVER 2.5\nInter v Layür Town\nQuota 1,85")["bet_type"] == "BACK"
    # Una riga-lato pulita con un solo token Unicode è riconosciuta anche se .lower() di un
    # accento (Ò→ò) resta una sola parola: "Banca" maiuscolo/accentato non si spezza.
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nBANCA")["bet_type"] == "LAY"


def test_quota_malformata_rifiutata():
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 1.2.3")["quota"] == ""


def test_quota_emoji_nuda_non_inventata():
    # "📈 1.2.3" senza marker "Quota": niente numero nudo inventato come prezzo.
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\n📈 1.2.3")["quota"] == ""
    # Anche un numero nudo ben formato senza "Quota"/"@" non è una quota (conservativo).
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\n📈 1.85")["quota"] == ""


def test_riga_lato_solo_token_esatto():
    # "Lay Cup"/"Banca League" (lega/nota) NON devono forzare il lato (P1 wrong-side).
    assert parse_message("P.Bet. OVER 2.5\nLay Cup\nInter v Milan\nQuota 1,85")["bet_type"] == "BACK"
    assert parse_message("P.Bet. OVER 2.5\nBanca League\nInter v Milan\nQuota 1,85")["bet_type"] == "BACK"
    # La riga-lato esatta (una sola parola) continua a funzionare.
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nBanca")["bet_type"] == "LAY"
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nPunta")["bet_type"] == "BACK"


def test_prematch_status_senza_valore_non_scarta_quota():
    # "Quota 1,85 Prematch" (status senza valore, niente HT/FT): la quota resta 1.85.
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 1,85 Prematch")["quota"] == "1.85"


def test_riga_emoji_mista_estrae_quota_e_probabilita():
    # "📈Quota 1,85 📊72%": deve estrarre sia la quota sia la probabilità.
    p = parse_message("P.Bet. OVER 2.5\nInter v Milan\n📈Quota 1,85 📊72%")
    assert p["quota"] == "1.85"
    assert p["probability"] == "72"


def test_linea_ht_non_e_quota():
    # "Quota 1,5 HT" -> 1,5 è la LINEA, non una quota (anche se ≥ 1).
    assert parse_message("P.Bet. OVER 1.5\nInter v Milan\nQuota 1,5 HT")["quota"] == ""
    assert parse_message("📈Quota 1,5 HT Prematch:0")["quota"] == ""
    # Se invece c'è una quota prematch valida, quella sì.
    assert parse_message("📈Quota 2,5 FT Prematch:1,90")["quota"] == "1.90"


def test_token_htft_vagante_non_ribalta_la_quota():
    # audit B2: un "ht"/"ft" NON adiacente al numero dopo Quota non deve ribaltare la
    # modalità di estrazione (prima `\b(?:ht|ft)\b` sull'intera riga → quota persa). Qui
    # 1,90 è la quota reale e va letta, nonostante un "ft" più avanti sulla riga.
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 1,90 nel match ft")["quota"] == "1.90"
    # Il marker ADIACENTE invece continua a identificare la linea/quota a fine tempo.
    assert parse_message("P.Bet. OVER 1.5\nInter v Milan\nQuota 1,5 HT")["quota"] == ""


def test_coda_quota_stessa_riga_non_finisce_in_eventname():
    p = parse_message("P.Bet. OVER 2.5\nInter v Milan Quota 1,85")
    assert p["teams"] == "Inter v Milan"
    assert p["quota"] == "1.85"


def test_competizione_e_fixture_trattino_non_scrivono_evento():
    # Entrambe con "-" in testo libero: nessuna squadra (safe), niente evento errato.
    assert parse_message("P.Bet. GG\nItaly - Serie A\nInter - Milan\nQuota 1,85")["teams"] == ""


def test_quota_virgola_e_punto():
    assert parse_message("Quota 2,40")["quota"] == "2.40"
    assert parse_message("Quota 1.95")["quota"] == "1.95"


def test_score_non_scambiato_per_squadre():
    # "Score: 1 - 0" non deve diventare teams.
    p = parse_message("P.Bet. OVER 2.5\nScore: 1 - 0\nInter v Milan")
    assert p["score"] == "1 - 0"
    assert p["teams"] == "Inter v Milan"


def test_live_flag():
    assert parse_message("P.Bet. OVER 2.5 LIVE\nInter v Milan")["live"] is True
    assert parse_message("P.Bet. OVER 2.5 live\nInter v Milan")["live"] is True
    assert parse_message("P.Bet. OVER 2.5 Live\nInter v Milan")["live"] is True
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan")["live"] is False
    # 'live' dentro una parola più lunga non deve attivare il flag (word-boundary).
    assert parse_message("P.Bet. OVER 2.5 delivery\nInter v Milan")["live"] is False
    assert parse_message("P.Bet. OVER 2.5\nLiverpool v Inter")["live"] is False


def test_probabilita_malformata_rifiutata():
    # "1.2.3%" è malformato: niente frammento ("1.2"/"2.3") -> probabilità vuota.
    p = parse_message("P.Bet. OVER 2.5\nInter v Milan\nProbability 1.2.3%")
    assert p["probability"] == ""


def test_coda_at_spaziato_e_probabilita_non_finiscono_in_eventname():
    # "@ 1,85" (con spazio) e "Probability 72%" sulla riga squadre non devono
    # entrare nell'EventName; quota/probabilità restano estratte a parte.
    p = parse_message("P.Bet. OVER 2.5\nInter v Milan @ 1,85")
    assert p["teams"] == "Inter v Milan"
    assert p["quota"] == "1.85"
    p2 = parse_message("P.Bet. OVER 2.5\nInter v Milan Probability 72%\nQuota 1,85")
    assert p2["teams"] == "Inter v Milan"
    assert p2["probability"] == "72"
    assert p2["quota"] == "1.85"


def test_coda_probabilita_italiana_non_finisce_in_eventname():
    # Etichetta italiana "Probabilità" sulla riga squadre: EventName resta pulito.
    p = parse_message("P.Bet. OVER 2.5\nInter v Milan Probabilità 72%\nQuota 1,85")
    assert p["teams"] == "Inter v Milan"
    assert p["probability"] == "72"
    assert p["quota"] == "1.85"


def test_quota_testo_su_riga_emoji_probabilita():
    # "📊72% Quota 1,85": la quota in testo va estratta anche senza 📈.
    p = parse_message("P.Bet. OVER 2.5\nInter v Milan\n📊72% Quota 1,85")
    assert p["probability"] == "72"
    assert p["quota"] == "1.85"


def test_numero_nudo_su_riga_emoji_senza_marker_non_e_quota():
    # "📊72% 1,85" senza "Quota"/@: nessun prezzo inventato dal numero nudo.
    p = parse_message("P.Bet. OVER 2.5\nInter v Milan\n📊72% 1,85")
    assert p["probability"] == "72"
    assert p["quota"] == ""


def test_quota_con_punto_finale_di_frase():
    # "Quota 1,85." (punto finale): il prezzo reale non va perso.
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 1,85.")["quota"] == "1.85"
    # ma "1.2.3" (decimali multipli) resta rifiutato.
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 1.2.3")["quota"] == ""


def test_quota_decimali_multipli_non_troncata():
    # "1.85.3"/"1,85,3" NON devono essere troncati a un prefisso valido ("1.8"):
    # il token malformato va rifiutato del tutto (no prezzo sbagliato a XTrader).
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 1.85.3")["quota"] == ""
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 1,85,3")["quota"] == ""
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\n📈Quota 2,5 FT Prematch:1,85,3")["quota"] == ""
    # contro-prova: il token ben formato resta accettato.
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 1,85")["quota"] == "1.85"


def test_quota_prematch_con_punto_finale_di_frase():
    # Stesso boundary (?![.,]\d) anche nel branch Prematch: il punto finale è ammesso,
    # i decimali multipli no. (NB: "HT Quota 1,85" resta "" per design: la riga HT è la
    # linea del mercato, la quota arriva solo da "Prematch:".)
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nPrematch: 1,85.")["quota"] == "1.85"
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nPrematch: 1.2.3")["quota"] == ""


def test_quota_uno_punto_zero_non_e_quota():
    # 1,00 non è una quota piazzabile: scartata a livello di parsing.
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 1,00")["quota"] == ""
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 1,01")["quota"] == "1.01"


def test_vuoto_non_crasha():
    p = parse_message("")
    assert p["signal_type"] == "" and p["teams"] == "" and p["quota"] == ""
    assert p["bet_type"] == "BACK" and p["live"] is False


def test_missing_teams_resta_vuoto():
    p = parse_message(_fixture("invalid_missing_teams.txt"))
    assert p["signal_type"] == "OVER 2.5"
    assert p["teams"] == ""                      # nessuna riga squadre


def test_missing_price_resta_vuoto():
    p = parse_message(_fixture("invalid_missing_price.txt"))
    assert p["teams"] == "Inter v Milan"
    assert p["quota"] == ""


def test_testo_casuale_non_inventa_segnale():
    p = parse_message(_fixture("invalid_random_text.txt"))
    assert p["signal_type"] == ""
    assert p["teams"] == ""
    assert p["quota"] == ""


def test_live_rimosso_da_signal_type():
    # "OVER 2.5 LIVE" -> signal_type "OVER 2.5" (così il mapping trova l'alias).
    p = parse_message("P.Bet. OVER 2.5 LIVE\nInter v Milan")
    assert p["signal_type"] == "OVER 2.5"
    assert p["live"] is True


def test_nome_squadra_che_inizia_con_label_prefix():
    # "Preston" non deve essere scambiato per l'etichetta "pre".
    assert parse_message("P.Bet. 1\nPreston v Leeds")["teams"] == "Preston v Leeds"


def test_cifre_nei_nomi_squadra():
    assert parse_message("P.Bet. 1\nSchalke 04 v Inter")["teams"] == "Schalke 04 v Inter"


def test_coda_punteggio_rimossa_dalle_squadre():
    p = parse_message("P.Bet. OVER 2.5\nYangon City v Silver Stars FC 6 - 0 46m")
    assert p["teams"] == "Yangon City v Silver Stars FC"


def test_vs_line_punteggio_in_mezzo_recupera_le_squadre():
    """#184 M10: su una riga 🆚 col punteggio IN MEZZO ("Real Madrid 2 - 1 Barcelona") il
    punteggio fa da separatore tra le squadre. Prima `_SCORE_TAIL` divorava " 2 - 1 Barcelona"
    lasciando solo "Real Madrid" → nessun separatore → squadre PERSE.

    Fail-first: sul vecchio codice `teams` restava vuoto."""
    assert parse_message("P.Bet. 1\n🆚 Real Madrid 2 - 1 Barcelona")["teams"] == \
        "Real Madrid v Barcelona"
    # varianti del separatore-punteggio: en-dash, due punti, senza spazi.
    assert parse_message("P.Bet. 1\n🆚 Real Madrid 2 – 1 Barcelona")["teams"] == \
        "Real Madrid v Barcelona"
    assert parse_message("P.Bet. 1\n🆚 Real Madrid 2:1 Barcelona")["teams"] == \
        "Real Madrid v Barcelona"
    assert parse_message("P.Bet. 1\n🆚 Real Madrid 2-1 Barcelona")["teams"] == \
        "Real Madrid v Barcelona"


def test_vs_line_punteggio_in_mezzo_con_coda_quota():
    """#184 M10 (Sourcery): col punteggio in mezzo E una coda quota/@/probabilità sulla stessa
    riga, `_teams_from_score` ripulisce la coda prima di usare il punteggio come separatore."""
    assert parse_message("P.Bet. 1\n🆚 Real Madrid 2 - 1 Barcelona @1.85")["teams"] == \
        "Real Madrid v Barcelona"
    assert parse_message("P.Bet. 1\n🆚 Real Madrid 2:1 Barcelona @ 1,85")["teams"] == \
        "Real Madrid v Barcelona"
    assert parse_message("P.Bet. 1\n🆚 Real Madrid 2-1 Barcelona quota 1.85")["teams"] == \
        "Real Madrid v Barcelona"
    assert parse_message("P.Bet. 1\n🆚 Real Madrid 2 - 1 Barcelona Probabilità 72%")["teams"] == \
        "Real Madrid v Barcelona"


def test_vs_line_punteggio_senza_away_non_inventa_squadra():
    """#184 M10: "🆚 Real Madrid 2 - 1 46m" (punteggio + minuto, NESSUNA squadra away) non deve
    produrre squadre fasulle: il lato dopo il punteggio inizia con una cifra (tempo) → fail-closed."""
    assert parse_message("P.Bet. 1\n🆚 Real Madrid 2 - 1 46m")["teams"] == ""


def test_vs_line_punteggio_senza_home_non_inventa_squadra():
    """#184 M10 (Sourcery): "🆚 46m 2 - 1 Real Madrid" (minuto + punteggio, NESSUNA squadra home)
    non deve produrre squadre fasulle: il lato home è solo un minuto → fail-closed."""
    assert parse_message("P.Bet. 1\n🆚 46m 2 - 1 Real Madrid")["teams"] == ""


def test_vs_line_coda_tempo_dopo_away_viene_rimossa():
    """#184 M10 (Codex P1): "🆚 Real Madrid 2 - 1 Barcelona 46m" — la coda di tempo dopo la squadra
    away va RIMOSSA, non inclusa nell'EventName.

    Fail-first: sul codice precedente l'away era "Barcelona 46m" → "Real Madrid v Barcelona 46m"."""
    assert parse_message("P.Bet. 1\n🆚 Real Madrid 2 - 1 Barcelona 46m")["teams"] == \
        "Real Madrid v Barcelona"
    # più token di metadati in coda
    assert parse_message("P.Bet. 1\n🆚 Real Madrid 2 - 1 Barcelona 90+2 FT")["teams"] == \
        "Real Madrid v Barcelona"


def test_vs_line_token_di_stato_non_diventa_squadra_away():
    """#184 M10 (Codex P1): uno stato alfabetico (HT/FT/LIVE/PRE) dopo il punteggio NON è una
    squadra: la riga deve fallire chiusa, non emettere "Real Madrid v HT".

    Fail-first: sul codice precedente l'away "HT"/"FT"/"LIVE" passava il guard `_STARTS_ALPHA`."""
    for tok in ("HT", "FT", "LIVE", "PRE"):
        assert parse_message(f"P.Bet. 1\n🆚 Real Madrid 2 - 1 {tok}")["teams"] == ""


def test_vs_line_squadra_away_a_cifra_iniziale_ammessa():
    """#184 M10 (Codex P2): un club con cifra iniziale ("1. FC Köln", "1860 Munich") è una squadra
    reale, non un metadato: deve essere ammesso. Una cifra NUDA non è tempo/stato.

    Fail-first: sul codice precedente `_STARTS_ALPHA` rifiutava ogni lato a cifra iniziale → vuoto."""
    assert parse_message("P.Bet. 1\n🆚 Bayern 2 - 1 1. FC Köln")["teams"] == "Bayern v 1. FC Köln"
    assert parse_message("P.Bet. 1\n🆚 Augsburg 2 - 1 1860 Munich")["teams"] == "Augsburg v 1860 Munich"
    # una cifra nuda a fine nome (Schalke 04) NON è un minuto: non va rimossa.
    assert parse_message("P.Bet. 1\n🆚 Roma 2 - 1 Schalke 04")["teams"] == "Roma v Schalke 04"


def test_vs_line_separatore_v_vince_sul_punteggio_in_coda():
    """#184 M10: se c'è un separatore `v` esplicito, il punteggio resta una CODA da rimuovere
    (non un separatore): "Inter v Milan 2 - 1 46m" → "Inter v Milan", non "Inter v Milan 2 - 1 46m"."""
    assert parse_message("P.Bet. 1\n🆚 Inter v Milan 2 - 1 46m")["teams"] == "Inter v Milan"


def test_testo_libero_punteggio_in_mezzo_non_diventa_squadre():
    """#184 M10: il recupero score-come-separatore vale SOLO per le righe 🆚. In testo libero uno
    score in mezzo è troppo ambiguo e NON deve produrre squadre ("Italy 2 - 1 Serie A").
    Coperti anche esempi "betting-like" o descrittivi (Sourcery)."""
    assert parse_message("P.Bet. GG\nItaly 2 - 1 Serie A")["teams"] == ""
    assert parse_message("P.Bet. GG\nItaly 2 - 1 Serie A @1.85")["teams"] == ""
    assert parse_message("P.Bet. GG\nItaly 2:1 Friendly match")["teams"] == ""


def test_competizione_non_scambiata_per_squadre():
    # "Italy - Serie A" (trattino) non deve vincere sul fixture "Inter v Milan" (v).
    p = parse_message("P.Bet. GG\nItaly - Serie A\nInter v Milan")
    assert p["teams"] == "Inter v Milan"


def test_messaggio_reale_gol_secondo_tempo():
    # Messaggio P.Bet reale (formato multi-riga con emoji).
    p = parse_message(_fixture("real_gol_secondo_tempo_live.txt"))
    assert p["signal_type"] == "GOL SECONDO TEMPO"       # LIVE rimosso
    assert p["competition"] == "Myanmar National League 2"
    assert p["teams"] == "Yangon City v Silver Stars FC"  # lega su riga 🏆 separata
    assert p["score"] == "6 - 0"
    assert p["time_"] == "46m"
    assert p["quota"] == ""                                # "Quota 0,5 HT" = linea, non quota
    assert p["probability"] == "81.29"
    assert p["live"] is True


def test_quota_sotto_uno_non_e_quota():
    # "0,5" (linea del mercato) non è una quota valida (le quote sono ≥ 1).
    assert parse_message("Quota 0,5 HT")["quota"] == ""
    assert parse_message("Quota 1,85")["quota"] == "1.85"


def test_tutte_le_chiavi_presenti():
    p = parse_message("qualcosa")
    for k in ("signal_type", "competition", "teams", "score", "time_",
              "quota", "probability", "bet_type", "live"):
        assert k in p


# ── A3: quota con HT/FT senza Prematch (regola universale del valore .5) ──

def test_quota_ft_senza_prematch_recuperata():
    # A3: "Quota 1,90 FT" senza "Prematch:" → 1.90 è la QUOTA (non è un valore .5),
    # prima veniva persa. Vale anche con HT e altri decimali non-.5.
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 1,90 FT")["quota"] == "1.90"
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 2,05 HT")["quota"] == "2.05"
    assert parse_message("📈Quota 1,90 FT")["quota"] == "1.90"


def test_quota_linea_mezzo_punto_resta_linea():
    # A3: un valore .5 con HT/FT e senza Prematch resta una LINEA over/under → nessuna
    # quota (comportamento storico preservato: niente prezzo errato a XTrader).
    assert parse_message("P.Bet. OVER 1.5\nInter v Milan\nQuota 1,5 HT")["quota"] == ""
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 2,5 FT")["quota"] == ""


def test_quota_ft_prematch_malformato_fail_closed():
    # Codex P1: se un marker "Prematch:" è presente ma il suo valore è malformato, la
    # quota era lì ed è invalida → fail-closed (""). Il fallback A3 NON deve promuovere
    # il numero pre-Prematch (la LINEA) a prezzo. Vale per linea .5 e non-.5.
    assert parse_message("P.Bet. OVER 2.5\nInter v Milan\nQuota 1,90 FT Prematch:1,85,3")["quota"] == ""
    assert parse_message("📈Quota 2,5 FT Prematch:1,85,3")["quota"] == ""


def test_quota_prematch_su_riga_successiva():
    # Codex P1 (multi-line): il "Prematch:" reale è sulla riga DOPO. Il recupero A3 è
    # whole-message: vede il Prematch e usa 1,85 (la quota vera), NON promuove 1,90 (la
    # linea) della prima riga. Senza Prematch da nessuna parte, invece, 1,90 è la quota.
    assert parse_message("Quota 1,90 FT\nPrematch:1,85")["quota"] == "1.85"
    assert parse_message("Quota 1,90 FT\nPrematch:1,85,3")["quota"] == ""   # malformato → fail-closed
    assert parse_message("Quota 1,90 FT")["quota"] == "1.90"                # nessun Prematch → A3
