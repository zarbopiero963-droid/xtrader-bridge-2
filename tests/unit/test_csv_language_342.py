"""#342: separatore decimale del CSV configurabile per lingua (IT/EN/ES).

Il supporto XTrader ha confermato che la versione ITALIANA (attuale) legge i decimali di
quote/points con la VIRGOLA; EN col punto. Il bridge resta CANONICO col punto all'interno
(validatori/dedup invariati) e localizza SOLO al confine di scrittura (`csv_writer.write_rows`).
Colonne localizzate (decisione owner): Price, MinPrice, MaxPrice, Points, Handicap.
Esercita le funzioni REALI: `normalize_csv_language`, `set/get_csv_language`, `write_rows`
end-to-end su file, e la coercion/sync di `config_store.load_config`/`save_config`.
"""

import csv
import json

import pytest

from xtrader_bridge import config_store, csv_writer


@pytest.fixture(autouse=True)
def _ripristina_lingua():
    # Stato di modulo: ogni test parte e finisce con la lingua precedente (nessun leak
    # verso gli altri test della suite, che assumono il default IT).
    prev = csv_writer.get_csv_language()
    yield
    csv_writer.set_csv_language(prev)


def _riga(**over):
    row = dict.fromkeys(csv_writer.CSV_HEADER, "")
    row.update({"Provider": "PBet", "EventName": "Inter v Milan",
                "MarketType": "MATCH_ODDS", "SelectionName": "Inter",
                "BetType": "PUNTA", "Handicap": "0"})
    row.update(over)
    return row


def _scrivi_e_rileggi(row, tmp_path):
    p = str(tmp_path / "segnali.csv")
    csv_writer.write_rows([row], p)
    with open(p, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    assert rows[0] == csv_writer.CSV_HEADER          # header MAI localizzato/tradotto
    return dict(zip(csv_writer.CSV_HEADER, rows[1]))


# ── normalize_csv_language (fail-closed) ────────────────────────────────────

def test_normalize_lingue_valide_case_insensitive():
    assert csv_writer.normalize_csv_language("it") == "IT"
    assert csv_writer.normalize_csv_language(" En ") == "EN"
    assert csv_writer.normalize_csv_language("es") == "ES"


def test_normalize_fail_closed_su_valori_sporchi():
    # mancante/non-stringa/sconosciuto → default sicuro IT (il formato del target principale).
    for sporco in (None, "", "fr", "uk", "italiano", 5, ["IT"], {"lang": "EN"}):
        assert csv_writer.normalize_csv_language(sporco) == "IT"


def test_set_csv_language_normalizza_e_ritorna():
    assert csv_writer.set_csv_language("en") == "EN"
    assert csv_writer.get_csv_language() == "EN"
    assert csv_writer.set_csv_language("garbage") == "IT"   # fail-closed
    assert csv_writer.get_csv_language() == "IT"


# ── scrittura localizzata end-to-end (file reale) ────────────────────────────

def test_it_default_tutte_le_colonne_decimali_con_virgola(tmp_path):
    # IT è il DEFAULT: senza alcuna set esplicita i decimali escono con la virgola.
    csv_writer.set_csv_language("IT")
    out = _scrivi_e_rileggi(_riga(Price="1.85", MinPrice="1.5", MaxPrice="2.05",
                                  Points="1.5", Handicap="-0.5"), tmp_path)
    assert out["Price"] == "1,85"
    assert out["MinPrice"] == "1,5"
    assert out["MaxPrice"] == "2,05"
    assert out["Points"] == "1,5"
    assert out["Handicap"] == "-0,5"


def test_en_decimali_con_punto_anche_da_input_virgola(tmp_path):
    # EN: qualunque separatore interno (punto o virgola residua) esce col PUNTO.
    csv_writer.set_csv_language("EN")
    out = _scrivi_e_rileggi(_riga(Price="1,85", Points="1.5", Handicap="+1,5"), tmp_path)
    assert out["Price"] == "1.85"
    assert out["Points"] == "1.5"
    assert out["Handicap"] == "+1.5"


def test_es_decimali_con_virgola(tmp_path):
    # ES segue la convenzione spagnola (virgola) — da confermare col supporto; la mappa
    # è una riga (`_COMMA_DECIMAL_LANGUAGES`).
    csv_writer.set_csv_language("ES")
    out = _scrivi_e_rileggi(_riga(Price="2.5"), tmp_path)
    assert out["Price"] == "2,5"


def test_colonne_testuali_mai_toccate(tmp_path):
    # SelectionName/MarketName contengono decimali LEGITTIMI nel testo («Over 2.5 Goals»):
    # NON sono colonne decimali → mai localizzate (un rename cambierebbe la selezione!).
    csv_writer.set_csv_language("IT")
    out = _scrivi_e_rileggi(_riga(SelectionName="Over 2.5 Goals",
                                  MarketName="Over/Under 2.5"), tmp_path)
    assert out["SelectionName"] == "Over 2.5 Goals"
    assert out["MarketName"] == "Over/Under 2.5"


def test_valori_non_numerici_o_vuoti_invariati(tmp_path):
    # Fail-closed: un valore malformato (già rifiutato a monte dai validatori) NON viene
    # "aggiustato" dal writer; vuoto resta vuoto; interi senza parte decimale invariati.
    csv_writer.set_csv_language("IT")
    out = _scrivi_e_rileggi(_riga(Price="abc", MinPrice="1.2.3", Points="", Handicap="0"),
                            tmp_path)
    assert out["Price"] == "abc"
    assert out["MinPrice"] == "1.2.3"
    assert out["Points"] == ""
    assert out["Handicap"] == "0"


def test_handicap_negativo_localizzato_non_apostrofato(tmp_path):
    # Interazione con l'anti CSV-injection (B1): «-1,5» localizzato è ancora un numero
    # (SIGNED_DECIMAL accetta la virgola) → NIENTE apice; il contratto numerico regge.
    csv_writer.set_csv_language("IT")
    out = _scrivi_e_rileggi(_riga(Handicap="-1.5"), tmp_path)
    assert out["Handicap"] == "-1,5"


# ── config: coercion + sync del writer ───────────────────────────────────────

def test_load_config_coercion_e_sync(tmp_path):
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"csv_language": "en"}, f)
    cfg = config_store.load_config(p)
    assert cfg["csv_language"] == "EN"               # coercion canonica
    assert csv_writer.get_csv_language() == "EN"     # writer allineato al load


def test_load_config_lingua_sporca_o_mancante_default_it(tmp_path):
    p = str(tmp_path / "config.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"csv_language": "francese"}, f)
    assert config_store.load_config(p)["csv_language"] == "IT"
    assert csv_writer.get_csv_language() == "IT"
    p2 = str(tmp_path / "config2.json")
    with open(p2, "w", encoding="utf-8") as f:
        json.dump({"provider": "X"}, f)              # chiave assente → default
    assert config_store.load_config(p2)["csv_language"] == "IT"


def test_save_config_sincronizza_il_writer(tmp_path):
    # Un salvataggio (es. caricamento profilo) che porta una lingua diversa ha effetto
    # SENZA riavvio: save_config allinea il writer alla config viva. Save PARZIALE
    # (nessuna chiave bot_token) → nessuna interazione keyring nel test.
    csv_writer.set_csv_language("IT")
    p = str(tmp_path / "config.json")
    cfg = {"csv_language": "ES", "provider": "X"}
    saved, ok = config_store.save_config(cfg, p)
    assert ok and saved["csv_language"] == "ES"
    assert csv_writer.get_csv_language() == "ES"


def test_save_parziale_senza_chiave_non_resetta_la_lingua(tmp_path):
    # #344 (Fable): un save PARZIALE la cui cfg NON contiene `csv_language` non dice nulla
    # sulla lingua → NON deve resettare il writer al default IT (un utente EN tornerebbe
    # silenziosamente alla virgola). Fail-first sul guard `if "csv_language" in in_memory`.
    csv_writer.set_csv_language("EN")
    p = str(tmp_path / "config.json")
    saved, ok = config_store.save_config({"provider": "X"}, p)   # chiave ASSENTE
    assert ok
    assert csv_writer.get_csv_language() == "EN"                 # lingua PRESERVATA


def test_save_config_persiste_il_valore_canonico(tmp_path):
    # #344 (CodeRabbit): il valore CANONICO normalizzato viene riscritto in config PRIMA
    # della copia per il disco: config.json, `saved` del chiamante e lingua attiva del
    # writer non divergono mai (niente «francese» persistito verbatim col writer a IT).
    p = str(tmp_path / "config.json")
    saved, ok = config_store.save_config({"csv_language": "es", "provider": "X"}, p)
    assert ok and saved["csv_language"] == "ES"              # canonico nel saved
    with open(p, encoding="utf-8") as f:
        assert json.load(f)["csv_language"] == "ES"          # canonico SU DISCO
    saved, ok = config_store.save_config({"csv_language": "francese", "provider": "X"}, p)
    assert ok and saved["csv_language"] == "IT"              # sporco → fail-closed ovunque
    with open(p, encoding="utf-8") as f:
        assert json.load(f)["csv_language"] == "IT"
    assert csv_writer.get_csv_language() == "IT"


def test_chiave_presente_ma_none_fail_closed_a_it(tmp_path):
    # #344 (GLM/GPT gap): chiave PRESENTE con valore None/malformato = intento sconosciuto →
    # fail-closed al default IT (formato del target principale), coerente con `normalize`.
    # DIVERSO dal save PARZIALE (chiave ASSENTE = nessuna affermazione → lingua preservata).
    csv_writer.set_csv_language("EN")
    p = str(tmp_path / "config.json")
    saved, ok = config_store.save_config({"csv_language": None, "provider": "X"}, p)
    assert ok
    assert csv_writer.get_csv_language() == "IT"


def test_colonne_decimali_sempre_trimmate_end_to_end(tmp_path):
    # #344 (Fable/GLM/Fugu): regola UNIFORME e deterministica — una colonna DECIMALE esce
    # SEMPRE trimmata nel FILE (il parser numerico XTrader non è garantito tolleri il
    # padding), col separatore della lingua. End-to-end su file reale, non helper isolato.
    csv_writer.set_csv_language("IT")
    out = _scrivi_e_rileggi(_riga(Price=" 1.85 ", Handicap=" -0.5", Points="1.5 "), tmp_path)
    assert out["Price"] == "1,85"
    assert out["Handicap"] == "-0,5"
    assert out["Points"] == "1,5"
    # anche un contenuto NON numerico in colonna decimale esce trimmato (regola uniforme),
    # ma il CONTENUTO resta invariato (fail-closed: niente "aggiusti", scartato a monte).
    out = _scrivi_e_rileggi(_riga(Price=" abc "), tmp_path)
    assert out["Price"] == "abc"


def test_scritture_stesso_file_lingua_coerente(tmp_path):
    # La lingua è catturata UNA volta per scrittura: righe multiple nello stesso file
    # escono tutte con lo stesso separatore.
    csv_writer.set_csv_language("IT")
    p = str(tmp_path / "segnali.csv")
    csv_writer.write_rows([_riga(Price="1.85"), _riga(Price="2.10")], p)
    with open(p, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    prices = [dict(zip(csv_writer.CSV_HEADER, r))["Price"] for r in rows[1:]]
    assert prices == ["1,85", "2,10"]


# ── localize_row (wrapper pubblico per le anteprime, PR-cestino) ─────────────

def test_localize_row_lang_esplicita_es_e_default_corrente():
    # GLM #348: copertura esplicita del wrapper pubblico. `lang` esplicita vince sempre;
    # senza `lang` usa la lingua corrente del modulo (stessa fonte del write-path).
    row = _riga(Price="1.85", Points="2.5", Handicap="-1.5")
    es = csv_writer.localize_row(row, "ES")
    assert (es["Price"], es["Points"], es["Handicap"]) == ("1,85", "2,5", "-1,5")
    assert es["EventName"] == "Inter v Milan"            # testuali invariate
    assert row["Price"] == "1.85"                        # l'input NON è mutato (copia)
    csv_writer.set_csv_language("EN")
    default_en = csv_writer.localize_row(row)
    assert default_en["Price"] == "1.85"
    csv_writer.set_csv_language("IT")
    default_it = csv_writer.localize_row(row)
    assert default_it["Price"] == "1,85"
