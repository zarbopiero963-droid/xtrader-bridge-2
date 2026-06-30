"""Test del motore di estrazione del Parser Personalizzato (CP-02).

Esercitano le funzioni reali di `xtrader_bridge.custom_parser_engine`:
estrazione per singola regola (fixed/start_after/end_before/emoji/multiriga) e
applicazione completa con gate "Non pronto" sugli obbligatori vuoti.
"""

from xtrader_bridge import custom_parser as cp
from xtrader_bridge import custom_parser_engine as eng
from xtrader_bridge.csv_writer import CSV_HEADER


# ── extract_value: singola regola ──────────────────────────────────────────

def test_fixed_value_ignora_il_testo():
    r = cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM")
    assert eng.extract_value("qualsiasi cosa", r) == "TG_CUSTOM"
    assert eng.extract_value("", r) == "TG_CUSTOM"


def test_start_after_e_end_before_estrae_in_mezzo():
    r = cp.FieldRule(target="EventName", start_after="Match:", end_before="\n")
    assert eng.extract_value("Match: Inter v Milan\nAltro", r) == "Inter v Milan"


def test_start_after_assente_ritorna_vuoto():
    r = cp.FieldRule(target="Price", start_after="Quota:")
    assert eng.extract_value("nessuna quota qui", r) == ""


def test_end_before_vuoto_si_ferma_a_fine_riga():
    r = cp.FieldRule(target="Price", start_after="Quota:")
    assert eng.extract_value("Quota: 1,85\nLato: BACK", r) == "1,85"


def test_end_before_vuoto_senza_a_capo_prende_fino_a_fine():
    r = cp.FieldRule(target="Price", start_after="Quota:")
    assert eng.extract_value("Quota: 1,85", r) == "1,85"


def test_end_before_configurato_ma_assente_fallisce():
    # Strict: se il delimitatore di fine è configurato ma manca, estrazione vuota
    # (un messaggio non conforme non deve passare il gate). [Codex P2]
    r = cp.FieldRule(target="EventName", start_after="Match:", end_before="@@@")
    assert eng.extract_value("Match: Inter v Milan", r) == ""


def test_regola_non_configurata_e_vuota():
    # Né fixed né delimitatori → vuoto (non sappiamo dove prendere il valore).
    r = cp.FieldRule(target="EventName")
    assert eng.extract_value("Inter v Milan\nx", r) == ""


def test_start_after_vuoto_parte_da_inizio():
    r = cp.FieldRule(target="EventName", end_before="|")
    assert eng.extract_value("Inter v Milan|resto", r) == "Inter v Milan"


def test_delimitatori_emoji():
    r = cp.FieldRule(target="Price", start_after="📊", end_before="%")
    assert eng.extract_value("📊72% Quota", r) == "72"


def test_valore_viene_rifilato():
    r = cp.FieldRule(target="EventName", start_after=":", end_before="\n")
    assert eng.extract_value(":   Inter v Milan   \n", r) == "Inter v Milan"


def test_value_map_non_applicata_in_cp02():
    # CP-02 estrae il valore grezzo; la value-map è CP-03.
    r = cp.FieldRule(target="BetType", start_after="Lato:", value_map="bettype")
    assert eng.extract_value("Lato: BACK", r) == "BACK"


# ── extract_value: tolleranza agli spazi nei delimitatori ───────────────────

def test_delim_spazi_ai_bordi_del_campo_ignorati():
    # Spazio iniziale/finale digitato per errore nel campo: non rompe il match.
    r = cp.FieldRule(target="Price", start_after=" Quota: ")
    assert eng.extract_value("Quota: 1,85", r) == "1,85"
    r2 = cp.FieldRule(target="EventName", start_after="Match:", end_before=" | ")
    assert eng.extract_value("Match: Inter v Milan | resto", r2) == "Inter v Milan"


def test_delim_spazi_interni_flessibili():
    # "Esito :" (campo con spazio) combacia con "Esito :" e "Esito  :" nel msg.
    r = cp.FieldRule(target="SelectionName", start_after="Esito :", end_before="\n")
    assert eng.extract_value("Esito : GG\n", r) == "GG"
    assert eng.extract_value("Esito  : GG\n", r) == "GG"
    assert eng.extract_value("Esito : GG\n", cp.FieldRule(
        target="SelectionName", start_after="Esito  :", end_before="\n")) == "GG"


def test_delim_parole_ed_emoji_restano_letterali():
    # Le parole devono restare uguali: un delimitatore diverso non combacia.
    r = cp.FieldRule(target="Price", start_after="Quota:")
    assert eng.extract_value("Quotaz: 1,85", r) == ""        # parola diversa → no match
    e = cp.FieldRule(target="Price", start_after="📊", end_before="%")
    assert eng.extract_value("📊72%", e) == "72"             # emoji letterale, ok
    assert eng.extract_value("📈72%", e) == ""               # emoji diversa → no match


def test_delim_valore_con_spazi_interni_preservato():
    # Gli spazi DENTRO il valore non vengono toccati (solo bordi rifilati).
    r = cp.FieldRule(target="EventName", start_after="Match:", end_before="\n")
    assert eng.extract_value("Match:   Inter  v  Milan  \n", r) == "Inter  v  Milan"


def test_delim_newline_resta_letterale():
    # end_before "\n" non è "spazio": resta letterale → se manca l'a-capo e c'è
    # solo quella riga... il default (end_before vuoto) va a fine stringa, ma un
    # "\n" esplicito richiede l'a-capo (comportamento invariato, niente regressioni).
    r = cp.FieldRule(target="EventName", start_after="Match:", end_before="\n")
    assert eng.extract_value("Match: Inter v Milan\nAltro", r) == "Inter v Milan"
    assert eng.extract_value("Match: Inter v Milan", r) == ""   # nessun "\n" → fallisce


# ── apply_parser: gate "Non pronto" ────────────────────────────────────────

def _parser():
    return cp.CustomParserDef(name="Yangon", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM"),
        cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
        cp.FieldRule(target="Price", start_after="Quota:", end_before="\n", required=True),
        cp.FieldRule(target="BetType", start_after="Lato:", required=True),
        cp.FieldRule(target="MarketName", start_after="Mercato:", end_before="\n"),  # opzionale
    ])


_MSG_OK = "Match: Inter v Milan\nQuota: 1,85\nLato: BACK"


def test_apply_parser_ready_quando_obbligatori_presenti():
    res = eng.apply_parser(_parser(), _MSG_OK)
    assert res.ready is True
    assert res.missing_required == []
    assert res.values["EventName"] == "Inter v Milan"
    assert res.values["Price"] == "1,85"
    assert res.values["BetType"] == "BACK"
    assert res.values["Provider"] == "TG_CUSTOM"
    assert res.values["MarketName"] == ""  # opzionale assente → vuoto, non blocca


def test_apply_parser_non_pronto_se_obbligatorio_vuoto():
    msg = "Match: Inter v Milan\nLato: BACK"  # manca Quota
    res = eng.apply_parser(_parser(), msg)
    assert res.ready is False
    assert res.missing_required == ["Price"]


def test_apply_parser_opzionale_vuoto_non_blocca():
    res = eng.apply_parser(_parser(), _MSG_OK)
    assert res.ready is True
    assert "MarketName" not in res.missing_required


def test_as_csv_row_ha_le_14_colonne():
    res = eng.apply_parser(_parser(), _MSG_OK)
    row = res.as_csv_row()
    assert list(row.keys()) == CSV_HEADER
    assert len(row) == 14
    assert row["EventName"] == "Inter v Milan"
    assert row["MarketId"] == ""  # colonna senza regola → vuota


def test_apply_parser_testo_vuoto_non_pronto():
    res = eng.apply_parser(_parser(), "")
    assert res.ready is False
    # tutti gli obbligatori non-fixed risultano mancanti
    assert set(res.missing_required) == {"EventName", "Price", "BetType"}


def test_required_soddisfatto_da_fixed_value():
    # Un obbligatorio con fixed_value è sempre soddisfatto, anche a testo vuoto.
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG_CUSTOM", required=True),
    ])
    res = eng.apply_parser(defn, "")
    assert res.ready is True
    assert res.missing_required == []
    assert res.values["Provider"] == "TG_CUSTOM"


def test_matches_message_solo_fixed_mai_corrisponde():
    # Parser a soli valori fissi: nessuna estrazione → non corrisponde a nessun
    # messaggio (gate di contenuto del live, anti-segnale-fantasma).
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Provider", fixed_value="TG"),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
    ])
    assert eng.matches_message(defn, "qualsiasi cosa") is False
    assert eng.matches_message(defn, "") is False


def test_matches_message_estrazione_dipende_dal_testo():
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="EventName", start_after="Match:", end_before="\n", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
    ])
    assert eng.matches_message(defn, "Match: Inter v Milan\n") is True   # delimitatore presente
    assert eng.matches_message(defn, "nessun delimitatore") is False     # assente → no match


def test_matches_message_estrazione_opzionale_non_basta():
    # A10: campi scommessa FISSI + una regola di estrazione OPZIONALE "larga" non deve
    # far risultare segnale un messaggio non pertinente che combacia con quella regola.
    # Conta solo un'estrazione OBBLIGATORIA (il contenuto vero del segnale).
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="Price", fixed_value="2.0", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        # nota opzionale che estrae da "qualsiasi" riga con uno spazio iniziale
        cp.FieldRule(target="MarketName", start_after="x", end_before="\n", required=False),
    ])
    # Un messaggio non-segnale che però attiva la regola opzionale → NON è un match.
    assert eng.matches_message(defn, "xyz roba a caso\n") is False
    # Aggiungendo un'estrazione OBBLIGATORIA, il match dipende dal contenuto reale.
    defn.rules[3] = cp.FieldRule(target="MarketName", start_after="x", end_before="\n", required=True)
    assert eng.matches_message(defn, "xyz roba a caso\n") is True


def test_matches_message_campo_riconoscimento_estratto_anche_se_opzionale():
    # Codex: in modalità BOTH la GUI lascia i campi nome/ID NON obbligatori (basta un
    # set). Un campo di RICONOSCIMENTO estratto deve contare come contenuto anche se non
    # `required`, altrimenti un parser BOTH legittimo verrebbe scartato (NO_CONTENT_MATCH).
    defn = cp.CustomParserDef(name="Both", mode="BOTH", rules=[
        cp.FieldRule(target="EventName", start_after="🆚", end_before="\n", required=False),
        cp.FieldRule(target="Price", fixed_value="2.0"),
    ])
    assert eng.matches_message(defn, "🆚Inter v Milan\n") is True       # recognition estratto
    assert eng.matches_message(defn, "nessuna squadra") is False        # niente contenuto


def test_matches_message_campo_riconoscimento_fuori_modalita_non_basta():
    # Codex P2 (A10): i campi di riconoscimento contano SOLO se rilevanti per la
    # modalità. Un parser NAME_ONLY con nome/price/bet FISSI + un'estrazione OPZIONALE
    # su un campo ID (MarketId, non usato da NAME_ONLY) NON deve far passare un
    # messaggio non-segnale solo perché quell'ID combacia con testo arbitrario.
    defn = cp.CustomParserDef(name="NameOnly", mode="NAME_ONLY", rules=[
        cp.FieldRule(target="EventName", fixed_value="Inter v Milan", required=True),
        cp.FieldRule(target="MarketType", fixed_value="OU", required=True),
        cp.FieldRule(target="SelectionName", fixed_value="Over 2.5", required=True),
        cp.FieldRule(target="BetType", fixed_value="PUNTA", required=True),
        # ID opzionale "largo": estrae da qualsiasi riga, ma è fuori dalla modalità.
        cp.FieldRule(target="MarketId", start_after="x", end_before="\n", required=False),
    ])
    assert eng.matches_message(defn, "xyz roba a caso\n") is False
    # #74: anche in BOTH, se i SOLI valori fissi completano già un set di riconoscimento (qui
    # il set NOMI è tutto fisso → riga piazzabile per QUALSIASI messaggio), un'estrazione
    # OPZIONALE su un campo fuori da quel set (MarketId) NON deve far passare un non-segnale:
    # altrimenti si scriverebbe un bet spurio. Prima questo ritornava True (bug A10).
    assert eng.matches_message(defn, "xyz roba a caso\n", "BOTH") is False
    defn.mode = "BOTH"
    assert eng.matches_message(defn, "xyz roba a caso\n") is False


def test_matches_message_set_riconoscimento_fisso_completo_blocca_estrazione_opzionale():
    # #74 (repro della issue): in BOTH un parser con ID FISSI completi (MarketId+SelectionId →
    # riga piazzabile per QUALSIASI messaggio) + un'estrazione OPZIONALE "larga" su EventName
    # NON deve far passare un messaggio non-segnale, altrimenti scrive un bet spurio coi fissi.
    defn = cp.CustomParserDef(name="Both", mode="BOTH", rules=[
        cp.FieldRule(target="MarketId", fixed_value="1.234"),
        cp.FieldRule(target="SelectionId", fixed_value="5678"),
        cp.FieldRule(target="Price", fixed_value="2.0"),
        cp.FieldRule(target="BetType", fixed_value="PUNTA"),
        cp.FieldRule(target="EventName", start_after="", end_before="\n", required=False),
    ])
    assert eng.matches_message(defn, "Promo: scarica la nostra app gratis!\n") is False
    # Rendendo OBBLIGATORIA l'estrazione, il match torna a dipendere dal contenuto reale.
    defn.rules[4] = cp.FieldRule(target="EventName", start_after="🆚", end_before="\n", required=True)
    assert eng.matches_message(defn, "🆚Inter v Milan\n") is True
    assert eng.matches_message(defn, "Promo non pertinente\n") is False


def test_matches_message_id_fissi_con_mappatura_mercati_non_e_fisso_completo():
    # #74 review (Codex): una mappatura MERCATI può azzerare MarketId/SelectionId fissi (stale-ID)
    # e validare la riga sui nomi mappati. Quindi ID fissi + `market_mapping_profiles` NON sono
    # "fisso-completi": un parser BOTH che estrae EventName (setup normale) deve continuare a
    # fare match, altrimenti il path supportato verrebbe scartato come NO_CONTENT_MATCH.
    defn = cp.CustomParserDef(name="Both", mode="BOTH",
                              market_mapping_profiles=["mercati"], rules=[
        cp.FieldRule(target="MarketId", fixed_value="1.234"),
        cp.FieldRule(target="SelectionId", fixed_value="5678"),
        cp.FieldRule(target="EventName", start_after="🆚", end_before="\n", required=False),
    ])
    assert eng.matches_message(defn, "🆚Inter v Milan\n") is True
    # Senza mappatura mercati gli stessi ID fissi tornano "fisso-completi": l'estrazione
    # opzionale non basta più (comportamento #74).
    defn.market_mapping_profiles = []
    assert eng.matches_message(defn, "🆚Inter v Milan\n") is False


def test_apply_parser_target_duplicato_ultimo_vince_senza_doppioni():
    # Difesa: due regole stesso target (vietate da validate, ma il motore non
    # deve produrre stati incoerenti). L'ultima vince; missing_required dedup.
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="Price", start_after="A:", end_before="\n", required=True),
        cp.FieldRule(target="Price", start_after="B:", end_before="\n", required=True),
    ])
    res = eng.apply_parser(defn, "B: 2,10\n")  # solo il secondo trova valore
    assert res.values["Price"] == "2,10"
    assert res.ready is True
    assert res.missing_required == []  # niente "Price" doppio né falso mancante


def test_extract_value_robusto_a_none():
    # Costruzione "a mano" con None: niente crash su .find() (None → "").
    r = cp.FieldRule(target="EventName", start_after=None, end_before="|")
    assert eng.extract_value("Inter v Milan|x", r) == "Inter v Milan"


def test_skeleton_non_configurato_non_e_pronto():
    # Lo skeleton (CP-01) ha regole obbligatorie senza delimitatori: applicato
    # a un messaggio NON deve diventare "pronto" con dati fasulli. [Codex P2]
    res = eng.apply_parser(cp.skeleton("X"), "Inter v Milan\nQuota 1,85")
    assert res.ready is False
    assert set(res.missing_required) == {"EventName", "MarketType", "SelectionName", "Price", "BetType"}
    assert res.values["Provider"] == "TG_CUSTOM"  # i fixed restano valorizzati


def test_obbligatorio_con_end_before_assente_non_pronto():
    # Un obbligatorio con end_before configurato ma assente nel messaggio → "Non pronto".
    defn = cp.CustomParserDef(name="X", rules=[
        cp.FieldRule(target="EventName", start_after="Match:", end_before="\nQuota:", required=True),
    ])
    res = eng.apply_parser(defn, "Match: Inter v Milan (manca il marker di fine)")
    assert res.ready is False
    assert res.missing_required == ["EventName"]
