"""PR-14c: test del report diagnostico (logica pura)."""

import pytest

from xtrader_bridge import __version__, diagnostics, log_privacy


def test_report_contiene_titolo_versione_e_campi():
    report = diagnostics.build_report([
        ("Stato", "ATTIVO"),
        ("Ricevuti", 5),
        ("Ultimo CSV", "C:/x/segnali.csv @ 10:00"),
    ])
    assert "XTrader Signal Bridge — diagnostica" in report
    assert f"versione: {__version__}" in report
    assert "Stato: ATTIVO" in report
    assert "Ricevuti: 5" in report
    assert "Ultimo CSV: C:/x/segnali.csv @ 10:00" in report


def test_valori_vuoti_mostrati_come_trattino():
    report = diagnostics.build_report([("Ultimo errore", ""), ("Ultimo segnale", None)])
    assert "Ultimo errore: —" in report
    assert "Ultimo segnale: —" in report


def test_valori_di_soli_spazi_mostrati_come_trattino():
    # #184 LOW: un valore whitespace-only (spazi/tab) NON deve apparire come campo
    # vuoto (`label: `) ma come `—`, come un valore assente.
    report = diagnostics.build_report([
        ("Spazi", "   "), ("Tab", "\t"), ("Newline", "\n  ")])
    assert "Spazi: —" in report
    assert "Tab: —" in report
    assert "Newline: —" in report
    # nessun campo deve restare con valore vuoto dopo i due punti
    for label in ("Spazi", "Tab", "Newline"):
        assert f"{label}: \n" not in report and not report.endswith(f"{label}: ")


def test_zero_non_e_trattato_come_vuoto():
    # Lo `0` (numerico) è un valore reale, non "vuoto": deve restare "0", non "—".
    report = diagnostics.build_report([("Ricevuti", 0), ("Scartati", 0)])
    assert "Ricevuti: 0" in report
    assert "Scartati: 0" in report


def test_valore_con_spazi_attorno_viene_strippato():
    report = diagnostics.build_report([("Stato", "  ATTIVO  ")])
    assert "Stato: ATTIVO" in report


def test_accetta_anche_un_dict_in_ordine():
    report = diagnostics.build_report({"A": "1", "B": "2"})
    # L'ordine di inserimento del dict è preservato.
    assert report.index("A: 1") < report.index("B: 2")


def test_redazione_token_nel_report():
    # Un bot token incollato per sbaglio in un campo NON deve finire nel report.
    # Il valore token-like è COSTRUITO a runtime: nel sorgente non compare un letterale
    # che combaci con lo scanner segreti del repo (forbidden-files/safety), ma a runtime
    # innesca comunque la redazione (`\d{6,}:[A-Za-z0-9_-]{20,}`).
    token = "1234567" + ":" + "x" * 30
    report = diagnostics.build_report([("Note", f"token {token} qui")])
    assert token not in report
    assert "[REDACTED_TOKEN]" in report


# ── C1 (#114 P2): privacy del report condiviso col supporto ─────────────────────────────────────
# Il report nasce per essere INCOLLATO in una segnalazione: oltre ai token deve uscire senza
# l'identità della chat Telegram e senza il nome utente del PC. Prima di questo fix `build_report`
# passava solo per `redact_secrets` → chat_id e `C:\Users\<nome>` finivano in chiaro.

def test_username_windows_mascherato_nel_path():
    """Il nome utente Windows non deve uscire dal PC: resta il path, sparisce la persona."""
    report = diagnostics.build_report([
        ("CSV path", r"C:\Users\Piero\Documents\XTrader\segnali.csv"),
        ("Cartella log", r"C:\Users\Piero\AppData\Local\XTraderBridge\logs"),
    ])
    assert "Piero" not in report
    assert report.count(diagnostics.MASKED_USER) == 2
    # Il resto del path resta LEGGIBILE: al supporto serve sapere dov'è il CSV.
    assert r"Documents\XTrader\segnali.csv" in report
    assert r"C:\Users" in report


@pytest.mark.parametrize("path,utente,atteso", [
    (r"C:\Users\Mario Rossi\segnali.csv", "Mario Rossi", r"C:\Users\<utente>\segnali.csv"),
    ("C:/Users/piero/segnali.csv", "piero", "C:/Users/<utente>/segnali.csv"),
    (r"D:\Users\admin\x.csv", "admin", r"D:\Users\<utente>\x.csv"),
    ("/home/piero/segnali.csv", "piero", "/home/<utente>/segnali.csv"),
    ("/Users/piero/Documents/segnali.csv", "piero", "/Users/<utente>/Documents/segnali.csv"),
    # Username con accenti: su Windows il nome utente segue il nome della persona
    # (Niccolò, José…) e la regex non deve essere ASCII-only (GPT-5.5 #164).
    (r"C:\Users\Niccolò\segnali.csv", "Niccolò", r"C:\Users\<utente>\segnali.csv"),
    (r"C:\Users\José Muñoz\segnali.csv", "José Muñoz", r"C:\Users\<utente>\segnali.csv"),
])
def test_username_mascherato_in_tutte_le_forme_di_path(path, utente, atteso):
    """Windows (barra rovescia e dritta, altra unità, accenti), Linux e macOS: la home è la home.

    Si asserisce il path mascherato **per intero**, non solo «il nome non c'è»: una regex
    che coprisse solo la parte ASCII lascerebbe `C:\\Users\\<utente>ò\\…` — il nome intero
    non comparirebbe più (assert soddisfatto) ma un suo **frammento** sì. Il confronto
    esatto è l'unico che vede quel caso."""
    report = diagnostics.build_report([("CSV path", path)])
    assert f"CSV path: {atteso}" in report
    assert utente not in report


def test_onedrive_maschera_solo_lo_username():
    """Caso Windows più comune di tutti (GPT-5.5 #164): la cartella Documenti redirezionata
    su OneDrive. Deve sparire SOLO il nome utente — che «il CSV sta su OneDrive» è
    proprio l'informazione che serve al supporto quando il file risulta lockato o lento."""
    report = diagnostics.build_report([
        ("CSV path", r"C:\Users\Piero\OneDrive\Documenti\XTrader\segnali.csv"),
        ("Cartella log", r"C:\Users\Piero\OneDrive - Azienda SpA\logs"),
    ])
    assert "Piero" not in report
    assert r"OneDrive\Documenti\XTrader\segnali.csv" in report
    assert "OneDrive - Azienda SpA" in report
    assert report.count(diagnostics.MASKED_USER) == 2


def test_username_mascherato_anche_su_share_di_rete_unc():
    """Buco trovato da CodeRabbit (#164): il CSV su **share di rete** è uno scenario che
    l'app supporta esplicitamente (tutto il Tema A dell'audit nasce da lì), e su
    `\\\\Server\\Users\\<nome>` lo username è esposto esattamente come in locale. Le due
    regex precedenti pretendevano una lettera di unità o un `/home` iniziale → la forma UNC
    passava intatta, proprio la PII che questa PR esiste per togliere."""
    report = diagnostics.build_report([
        ("CSV path", r"\\FileServer\Users\john.doe\segnali.csv"),
        ("Cartella log", "//FileServer/Users/john.doe/logs"),
    ])
    assert "john.doe" not in report
    assert r"CSV path: \\FileServer\Users\<utente>\segnali.csv" in report
    assert "Cartella log: //FileServer/Users/<utente>/logs" in report


@pytest.mark.parametrize("path,atteso", [
    # Admin share Windows (`C$`): tipica su macchine gestite da un IT aziendale.
    (r"\\Server\C$\Users\john.doe\segnali.csv", r"\\Server\C$\Users\<utente>\segnali.csv"),
    # Share con le home annidate sotto una cartella qualsiasi.
    (r"\\Server\Condivisa\Users\john.doe\x.csv", r"\\Server\Condivisa\Users\<utente>\x.csv"),
    (r"D:\Backup\Users\john.doe\x.csv", r"D:\Backup\Users\<utente>\x.csv"),
])
def test_username_mascherato_anche_in_share_annidate(path, atteso):
    """Secondo giro sul tema UNC (Claude Fable 5 #164): ancorare `Users` **subito dopo** il
    server copriva `\\\\Server\\Users\\<nome>` ma non `\\\\Server\\C$\\Users\\<nome>` né una
    share con le home annidate — e lì lo username resta in chiaro identico.

    La regola è ora «un segmento di path chiamato `Users` seguito da un nome», ovunque si
    trovi. È deliberatamente **fail-safe verso la privacy**: se una cartella si chiama
    davvero `Users` senza essere una home, si perde un nome di file nel report; nella
    direzione opposta si perderebbe il nome di una persona."""
    report = diagnostics.build_report([("CSV path", path)])
    assert "john.doe" not in report
    assert f"CSV path: {atteso}" in report


def test_path_senza_home_utente_resta_intatto():
    """La mascheratura è mirata alla home, non a «qualsiasi cartella»: un path di servizio
    deve restare integro o il report diventa inutile per diagnosticare."""
    report = diagnostics.build_report([
        ("CSV path", r"D:\XTrader\dati\segnali.csv"),
        ("Rete", r"\\NAS\condivisa\segnali.csv"),
        ("Sotto-cartella", "C:/Progetti/home/segnali.csv"),
    ])
    assert r"D:\XTrader\dati\segnali.csv" in report
    assert r"\\NAS\condivisa\segnali.csv" in report
    assert "C:/Progetti/home/segnali.csv" in report
    assert diagnostics.MASKED_USER not in report


@pytest.mark.parametrize("testo", [
    # Il caso che divorava la frase fino al `/` successivo (Claude Fable 5 #164).
    "Active Users/list non raggiungibile su api/v2",
    "Active Users/list non raggiungibile",
    r"errore in Users\cache",
])
def test_testo_libero_che_nomina_users_resta_intatto(testo):
    """`Users` in una FRASE non è un path e non va toccato (Claude Fable 5 #164).

    Era il fallimento più insidioso di questa PR: «Active Users/list non raggiungibile su
    api/v2» veniva mascherato fino al `/` successivo, cioè **il messaggio d'errore spariva
    dal report**. In un testo che esiste per far diagnosticare un problema, quello è danno
    reale, non un dettaglio cosmetico — e nessun campo libero contiene una home utente."""
    report = diagnostics.build_report([("Ultimo errore", testo)])
    assert f"Ultimo errore: {testo}" in report
    assert diagnostics.MASKED_USER not in report


@pytest.mark.parametrize("path,atteso", [
    (r"C:\Users\Mario Rossi", r"C:\Users\<utente>"),
    (r"C:\Users\Mario Rossi\file.csv", r"C:\Users\<utente>\file.csv"),
    (r"Users\Mario Rossi", r"Users\<utente>"),
    (r"Users\Mario Rossi\file.csv", r"Users\<utente>\file.csv"),
])
def test_nome_con_spazi_mascherato_per_intero_anche_senza_separatore_finale(path, atteso):
    """Under-masking trovato da GPT-5.5 (#164): un nome utente Windows PUÒ contenere spazi
    («Mario Rossi»), e un path incollato da Explorer o digitato in «CSV Path» spesso **non**
    finisce con un separatore. Un tentativo precedente vietava gli spazi per non divorare il
    testo libero, e su `C:\\Users\\Mario Rossi` lasciava «Rossi» in chiaro: mezzo cognome nel
    report è la direzione di errore peggiore delle due.

    Ora il nome può contenere spazi senza rischio, perché il match parte solo in un contesto
    di path — e in un path la classe di caratteri esclude già i separatori, quindi finisce da
    sola a fine segmento o a fine valore."""
    report = diagnostics.build_report([("CSV path", path)])
    assert "Rossi" not in report
    assert f"CSV path: {atteso}" in report


def test_contratto_pubblico_di_mask_user_paths():
    """`mask_user_paths` è pubblica: qui sta il suo contratto, verificato invece che assunto
    (GPT-5.5 e Claude Fable 5 #164). Oggi l'unico chiamante nel package è `build_report`, che
    la invoca **per valore** — ma la funzione resta esposta, quindi cosa copre e cosa no va
    scritto."""
    m = diagnostics.mask_user_paths

    # 1. Path ASSOLUTO dentro un testo composto: coperto — `Users` è preceduto da un separatore.
    assert m(r"Errore: C:\Users\Mario Rossi\file.csv") == r"Errore: C:\Users\<utente>\file.csv"

    # 2. Valore MULTILINEA: il path relativo è riconosciuto su ogni riga, non solo la prima
    #    (rilievo Fable: con l'ancora `\A` la seconda riga restava in chiaro).
    assert m("prima riga\n" + r"Users\john.doe\x.csv") == "prima riga\n" + r"Users\<utente>\x.csv"

    # 3. LIMITE DICHIARATO: un path relativo preceduto da altro testo sulla stessa riga non è
    #    riconoscibile — «Users» lì è indistinguibile da una parola. Non è un buco pratico
    #    (`build_report` passa i valori singolarmente, mai composti), ma è un motivo per non
    #    iniziare a chiamare questa funzione su testo già assemblato.
    assert m(r"Errore: Users\Mario Rossi\x.csv") == r"Errore: Users\Mario Rossi\x.csv"

    # 4. Over-masking accettato: in un URL `/Users/<x>/` il segmento sembra una home. Si perde
    #    un pezzo di URL, non si espone una persona — la direzione voluta.
    assert m("https://host/Users/list/api") == "https://host/Users/<utente>/api"


def test_path_relativo_senza_separatore_iniziale():
    """Edge case sollevato da Fugu Ultra (#164): in «CSV Path» si può digitare un percorso
    **relativo**. Senza separatore iniziale il match non scattava e lo username restava in
    chiaro — stessa PII, solo scritta in modo più corto."""
    report = diagnostics.build_report([("CSV path", r"Users\john.doe\segnali.csv")])
    assert "john.doe" not in report
    assert r"CSV path: Users\<utente>\segnali.csv" in report


@pytest.mark.parametrize("path", [
    "/data/ProjectUsers/john/x.csv",      # "Users" come SUFFISSO di un altro nome
    r"D:\SuperUsers\john\x.csv",
    r"C:\Users",                          # nessun nome dopo: niente da mascherare
    "/data/MyUsers/john/x.csv",
])
def test_users_come_pezzo_di_un_altro_nome_non_viene_toccato(path):
    """Guard di regressione (GPT-5.5 #164): `Users` deve valere come **segmento intero** di
    path, non come sottostringa. Senza il separatore obbligatorio a sinistra, `ProjectUsers`
    o `SuperUsers` farebbero sparire il segmento successivo — un match parziale che
    storpierebbe path del tutto innocui."""
    report = diagnostics.build_report([("CSV path", path)])
    assert f"CSV path: {path}" in report
    assert diagnostics.MASKED_USER not in report


def test_chat_id_redatto_con_la_stessa_impronta_del_diario():
    """Il chat_id sparisce ma resta CORRELABILE: stessa impronta usata dal diario eventi
    (`log_privacy.redact_chat_id`), così supporto e ledger parlano della stessa chat senza
    che nessuno dei due riveli l'ID."""
    chat = "123456789"
    report = diagnostics.build_report(
        [("Ultimo errore", f"bot: Chat not found ({chat})")], chat_ids=[chat])
    assert chat not in report
    assert log_privacy.redact_chat_id(chat) in report


def test_chat_id_supergruppo_redatto_anche_senza_il_meno():
    """Un supergruppo è `-100…` in config ma l'API lo cita spesso senza segno: entrambe le
    forme devono sparire, altrimenti la redazione è solo apparente."""
    chat = "-1001234567890"
    report = diagnostics.build_report([
        ("Ultimo errore", f"bot: forbidden in {chat}"),
        ("Ultimo messaggio", "peer id 1001234567890"),
    ], chat_ids=[chat])
    assert "1001234567890" not in report
    assert report.count(log_privacy.redact_chat_id(chat)) == 2


def test_supergruppo_redatto_anche_nella_forma_del_link_t_me():
    """Terza grafia dello stesso supergruppo (Fugu Ultra #164): i link `t.me/c/<id>/<msg>` —
    che Telegram genera e che finiscono nei messaggi e negli errori — usano l'id **senza il
    prefisso `-100`**. Senza questa forma la redazione sarebbe aggirabile da un campo libero
    come «Ultimo messaggio», proprio in un report nato per essere condiviso."""
    chat = "-1001234567890"
    interno = "1234567890"
    report = diagnostics.build_report([
        ("Ultimo messaggio", f"vedi https://t.me/c/{interno}/45"),
        ("Ultimo errore", f"bot: forbidden in {chat}"),
    ], chat_ids=[chat])
    assert interno not in report
    # Tutte le grafie puntano alla STESSA chat → stessa impronta, altrimenti il report
    # sembrerebbe parlare di due chat diverse.
    assert report.count(log_privacy.redact_chat_id(chat)) == 2


def test_collisione_fra_forma_derivata_e_id_configurato():
    """Caso limite sollevato da GPT-5.5 (#164): l'utente configura sia il supergruppo
    `-1001234567890` sia una chat il cui id è **esattamente** la forma interna del primo
    (`1234567890`). Quel testo è genuinamente ambiguo.

    Comportamento definito: **vince l'id configurato esplicitamente**. Entrambe le chat
    restano redatte (la privacy non dipende dalla disambiguazione), ma l'impronta mostrata
    è quella della chat che l'utente ha davvero scritto in config — l'alternativa sarebbe
    attribuire il testo a una delle due a sorte, rendendo ambigua la diagnostica condivisa."""
    supergruppo, esplicita = "-1001234567890", "1234567890"
    report = diagnostics.build_report([
        ("Ultimo messaggio", f"link https://t.me/c/{esplicita}/45"),
        ("Ultimo errore", f"bot: forbidden in {supergruppo}"),
    ], chat_ids=[supergruppo, esplicita])

    # Nessuna delle due esce in chiaro.
    assert esplicita not in report and supergruppo not in report
    # Il testo ambiguo è attribuito alla chat CONFIGURATA, non alla forma derivata.
    assert log_privacy.redact_chat_id(esplicita) in report
    # Il supergruppo resta comunque redatto con la propria impronta, dov'è scritto per intero.
    assert log_privacy.redact_chat_id(supergruppo) in report


def test_la_precedenza_non_dipende_dall_ordine_di_configurazione():
    """Congela la regola indipendentemente dall'ordine (GPT-5.5 #164): invertendo le due
    voci di `chat_ids` il report deve essere **identico**. Se l'esito dipendesse dall'ordine
    di iterazione, due utenti con la stessa config ma inserita in ordine diverso vedrebbero
    impronte diverse per lo stesso testo."""
    supergruppo, esplicita = "-1001234567890", "1234567890"
    campi = [("Ultimo messaggio", f"link https://t.me/c/{esplicita}/45"),
             ("Ultimo errore", f"bot: forbidden in {supergruppo}")]
    diretto = diagnostics.build_report(campi, chat_ids=[supergruppo, esplicita])
    invertito = diagnostics.build_report(campi, chat_ids=[esplicita, supergruppo])
    assert diretto == invertito


def test_chat_id_con_spazi_e_duplicati_normalizzati():
    """Config editata a mano (GPT-5.5 #164): lo stesso id ripetuto e con spazi attorno non
    deve né sfuggire alla redazione né produrre sostituzioni doppie."""
    report = diagnostics.build_report(
        [("Ultimo errore", "bot: chat 1234567890 irraggiungibile")],
        chat_ids=["  1234567890  ", "1234567890"])
    assert "1234567890" not in report
    assert report.count(log_privacy.redact_chat_id("1234567890")) == 1


def test_chat_id_non_redige_un_numero_che_lo_contiene():
    """Confini numerici: `12345` non deve mordere dentro `9912345678` (contatori, id evento,
    timestamp) — una redazione che storpia i numeri rende il report inservibile."""
    report = diagnostics.build_report([
        ("Ricevuti", "9912345678"),
        ("Ultimo errore", "codice 12345"),
    ], chat_ids=["12345"])
    assert "9912345678" in report
    assert "codice " + log_privacy.redact_chat_id("12345") in report


def test_chat_id_troppo_corto_ignorato():
    """Fail-safe al contrario: un valore di 1-2 cifre non è un chat_id Telegram reale (config
    di prova, campo mezzo compilato). Sostituirlo cancellerebbe ogni cifra uguale del report."""
    report = diagnostics.build_report([("Ricevuti", "5"), ("Scartati", "12")],
                                      chat_ids=["5", "12"])
    assert "Ricevuti: 5" in report
    assert "Scartati: 12" in report


def test_chat_id_assenti_o_sporchi_non_rompono_il_report():
    """`None`, vuoto, spazi, valori non-stringa: il report è un pulsante di supporto, non
    deve mai sollevare."""
    report = diagnostics.build_report([("Stato", "ATTIVO")],
                                      chat_ids=[None, "", "   ", 123456789])
    assert "Stato: ATTIVO" in report


def test_collect_chat_ids_raccoglie_tutte_le_fonti_di_config():
    """Il call site non deve dimenticare una fonte: chat principale, chat notifiche XTrader,
    chat sorgenti multiple e le chiavi delle mappe parser-per-chat."""
    cfg = {
        "chat_id": "111111111",
        "xtrader_notification_chat_id": "222222222",
        "source_chats": [{"name": "A", "chat_id": "333333333"},
                         {"name": "B", "chat_id": "444444444"}],
        "parser_by_chat": {"555555555": "p1"},
        "parser_list_by_chat": {"666666666": ["p1", "p2"]},
    }
    raccolti = set(diagnostics.collect_chat_ids(cfg))
    assert raccolti == {"111111111", "222222222", "333333333",
                        "444444444", "555555555", "666666666"}


def test_collect_chat_ids_tollera_config_malformata():
    """Config editata a mano / vecchia: nessuna eccezione, si raccoglie ciò che c'è."""
    assert diagnostics.collect_chat_ids(None) == ()
    assert diagnostics.collect_chat_ids({"source_chats": "non-una-lista"}) == ()
    assert diagnostics.collect_chat_ids(
        {"source_chats": [None, {"chat_id": "  777777777  "}, "x"]}) == ("777777777",)


def test_il_call_site_gui_passa_davvero_i_chat_id():
    """La redazione dei chat_id è **opt-in per parametro**: se il pulsante GUI chiamasse
    `build_report(info)` senza `chat_ids`, tutti i test qui sopra resterebbero verdi e il
    report reale continuerebbe a uscire con l'id in chiaro. Questo guard lega il fix al suo
    unico chiamante (`app._copy_diagnostics`), che è Tk e non si può istanziare headless."""
    import pathlib
    sorgente = (pathlib.Path(diagnostics.__file__).parent / "app.py").read_text(encoding="utf-8")
    chiamate = [r for r in sorgente.splitlines() if "diagnostics.build_report(" in r]
    assert chiamate, "call site sparito: la diagnostica GUI non costruisce più il report"
    for riga in chiamate:
        assert "chat_ids=" in riga, (
            "`build_report` chiamata senza `chat_ids`: il chat_id tornerebbe in chiaro "
            f"nel report condiviso (C1 #114) → {riga.strip()}")


def test_ordine_redazione_token_poi_chat_poi_path():
    """I tre livelli convivono nello stesso report senza annullarsi a vicenda."""
    token = "1234567" + ":" + "y" * 30
    report = diagnostics.build_report([
        ("Note", f"token {token}"),
        ("CSV path", r"C:\Users\Piero\segnali.csv"),
        ("Ultimo errore", "bot: chat 987654321 non raggiungibile"),
    ], chat_ids=["987654321"])
    assert token not in report
    assert "Piero" not in report
    assert "987654321" not in report
    assert "[REDACTED_TOKEN]" in report
    assert diagnostics.MASKED_USER in report
    assert log_privacy.redact_chat_id("987654321") in report
