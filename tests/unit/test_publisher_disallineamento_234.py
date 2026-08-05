"""#234 — il 403 indirizzava alla correzione SBAGLIATA, che trasforma un errore rumoroso in un
fallimento silenzioso.

Da un incidente reale del proprietario (2026-08-03). Il campo Repository puntava a
`xtrader-bridge-2` mentre il token aveva `Contents: Read and write` su `xtrader-revocation`.
Esito: 403, auto-pubblicazione ferma, avviso visibile.

Il messaggio del 403 diceva — correttamente ma **parzialmente** — «allarga il token». Chi lo
segue alla lettera aggiunge `xtrader-bridge-2` al token, e a quel punto:

- la pubblicazione **riesce**: «✅ Pubblicato», nessun errore;
- la lista finisce in un repository che **nessun bridge legge** (`REVOCATION_LIST_URL` punta
  altrove);
- le revoche **smettono di propagarsi**, in silenzio, a tempo indeterminato.

**Il 403 era più sicuro del successo che il messaggio suggeriva di ottenere.** Un fallimento
rumoroso sostituito da uno silenzioso, su una funzione di sicurezza.

Qui si bloccano le due metà della correzione: il confronto fra l'URL che si sta per pubblicare
e quello che i bridge scaricano davvero, e il testo del 403 che deve nominare **entrambe** le
ipotesi.
"""

from xtrader_bridge.licensing import revocation_client

from license_manager import publisher

_REALE = "https://raw.githubusercontent.com/tizio/xtrader-revocation/main/revocation_list.txt"


def test_234_repo_diverso_da_quello_che_i_bridge_leggono_PRODUCE_l_avviso(monkeypatch):
    """Il cuore della issue: pubblicare altrove non propaga nulla, e va detto."""
    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", _REALE)

    avviso = publisher.disallineamento_bridge("tizio/xtrader-bridge-2", "revocation_list.txt", "main")

    assert avviso, "un repository diverso da quello dei bridge deve produrre un avviso"
    # deve dire ENTRAMBI gli URL: senza, chi legge non sa cosa correggere
    assert "xtrader-bridge-2" in avviso, avviso
    assert "xtrader-revocation" in avviso, avviso
    # e deve dire la conseguenza, non solo che qualcosa non torna
    assert "revoca" in avviso.lower(), avviso
    # e deve VIETARE di allargare il token, non solo nominarlo (rilievo CodeRabbit): un
    # `"token" in avviso` accetterebbe anche il messaggio che RACCOMANDA di allargarlo, cioe'
    # proprio il consiglio dannoso che questa PR esiste per togliere.
    assert "NON allargare il token" in avviso, avviso


def test_234_configurazione_allineata_NON_produce_rumore(monkeypatch):
    """Contro-guardia. Un avviso su una configurazione corretta sarebbe peggio del silenzio:
    si impara a ignorarlo, e quando arriva quello vero non lo legge più nessuno."""
    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", _REALE)

    assert publisher.disallineamento_bridge("tizio/xtrader-revocation",
                                            "revocation_list.txt", "main") == ""


def test_234_url_placeholder_non_produce_MAI_avviso(monkeypatch):
    """Con l'URL placeholder di sviluppo la revoca online è inattiva **per costruzione**
    (`is_placeholder_url`), quindi il confronto non ha un termine di paragone valido: qualunque
    repo si stia configurando, avvisare sarebbe rumore su uno stato che non è un errore."""
    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", "")
    assert publisher.disallineamento_bridge("chiunque/qualsiasi", "x.txt", "main") == ""

    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", "non-un-url")
    assert publisher.disallineamento_bridge("chiunque/qualsiasi", "x.txt", "main") == ""


def test_234_path_da_CODIFICARE_e_configurazione_corretta_non_da_falso_disallineamento(monkeypatch):
    """Il confronto va fatto sull'URL **quotato** da `raw_url`, non sui campi grezzi.

    `raw_url` codifica `path`/`branch` apposta (rilievo Fugu #158): l'API pubblica il file
    all'indirizzo *codificato*, quindi confrontare stringhe non codificate segnalerebbe un
    disallineamento **falso** su ogni path con spazi o accenti — e un avviso falso su una
    configurazione giusta è esattamente ciò che insegna a ignorarlo.
    """
    url_con_spazio = ("https://raw.githubusercontent.com/tizio/xtrader-revocation/main/"
                      "lista%20revoche.txt")
    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", url_con_spazio)

    # il campo GUI contiene il path GREZZO, con lo spazio
    assert publisher.disallineamento_bridge("tizio/xtrader-revocation",
                                            "lista revoche.txt", "main") == ""


def test_234_il_403_nomina_ENTRAMBE_le_ipotesi():
    """Il difetto originale: il messaggio indirizzava a UNA sola delle due cause possibili.

    Seguire il rimedio suggerito — allargare il token — quando la causa vera è il repository
    sbagliato **risolve il 403 e crea il fallimento silenzioso**.
    """
    msg = publisher._error_message(403, "scrittura", "tizio/xtrader-bridge-2")

    assert "Contents: Read and write" in msg, msg          # ipotesi 1: token troppo stretto
    # ipotesi 2: repository sbagliato — quella che l'incidente reale ha dimostrato
    assert "repository" in msg.lower() and (
        "sbagliat" in msg.lower() or "non è quello" in msg.lower()), msg
    # e nell'ORDINE giusto (rilievo CodeRabbit): il repository PRIMA del token. Chi legge dall'alto
    # deve incontrare per prima l'ipotesi che, se ignorata, produce il fallimento silenzioso.
    assert msg.index("1) il REPOSITORY") < msg.index("2) il token"), msg


def test_234_il_403_di_RATE_LIMIT_resta_pulito():
    """Contro-guardia: il ramo rate-limit non deve ereditare le due ipotesi — lì il token e il
    repository sono entrambi corretti, e suggerire di controllarli manderebbe fuori strada."""
    msg = publisher._error_message(403, "scrittura", "tizio/x",
                                   {"message": "API rate limit exceeded"})
    assert "limite di frequenza" in msg
    assert "Contents: Read and write" not in msg


def test_234_slash_o_spazi_finali_AVVISANO_e_lo_spiegano(monkeypatch):
    """Secondo rilievo Fable 5, che ha CORRETTO il primo — e io avevo seguito il primo.

    Una stesura intermedia normalizzava spazi e slash finali «perché servono lo stesso file».
    È falso: su `raw.githubusercontent.com` un file con slash in coda
    (`…/revocation_list.txt/`) risponde **404**, e uno spazio pure. E `REVOCATION_LIST_URL` non
    è una preferenza: è la stringa che i bridge **scaricano davvero**.

    Normalizzarle significava **silenziare un bridge realmente rotto** — dentro la funzione che
    esiste per non silenziare nulla. Il difetto originale, riprodotto nella sua correzione.

    Si avvisa sempre, ma nominando la differenza: due URL che differiscono per uno spazio si
    leggono come identici, e un avviso che sembra sbagliato è un avviso che nessuno rilegge.
    """
    for coda in ("/", "//", " ", "\t"):
        monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", _REALE + coda)
        avviso = publisher.disallineamento_bridge("tizio/xtrader-revocation",
                                                  "revocation_list.txt", "main")
        assert avviso, f"coda {coda!r}: un 404 per tutti i bridge non puo' essere silenzioso"
        assert "SPAZI (a inizio o fine) o SLASH finali" in avviso, coda
        assert "404" in avviso, coda
        assert repr(_REALE + coda) in avviso, "il repr rende VISIBILE la differenza invisibile"


def test_234_spazio_INIZIALE_avvisa_e_il_testo_NON_lo_chiama_finale(monkeypatch):
    """Rilievo Fable 5 e GPT-5.5 sul confronto esatto, ed è il difetto di questa PR in miniatura.

    Il ramo usa `strip()`, che toglie il bianco da **entrambi** i lati: uno spazio *iniziale* in
    `REVOCATION_LIST_URL` finisce quindi nello stesso ramo — ma il messaggio lo chiamava «SPAZI o
    SLASH **finali**», e chi legge va a guardare la coda dove non c'è niente.

    È la stessa classe di difetto che questa PR corregge: **un testo che dichiara una cosa
    diversa da quella che il codice fa**. Qui il codice è giusto (avvisare è corretto: uno spazio
    iniziale rende l'URL inutilizzabile per i bridge quanto uno slash in coda) e il testo era
    impreciso, quindi si corregge il testo — e lo si blocca con un test.
    """
    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", " " + _REALE)
    avviso = publisher.disallineamento_bridge("tizio/xtrader-revocation",
                                              "revocation_list.txt", "main")

    assert avviso, "uno spazio iniziale rompe il download per tutti i bridge: va detto"
    # Il testo deve dire ESATTAMENTE cosa copre il ramo, in entrambe le direzioni: `strip()` è
    # bilaterale sugli spazi, `rstrip("/")` agisce SOLO in coda sugli slash (rilievo indipendente
    # di Fable 5 e Fugu Ultra sulla prima stesura di questa correzione, che diceva «SLASH in
    # eccesso (a inizio o fine)» — cioè si era allargata di un lato mentre ne stringeva un altro).
    assert "SPAZI (a inizio o fine) o SLASH finali" in avviso, avviso
    assert repr(" " + _REALE) in avviso, "il repr rende VISIBILE la differenza invisibile"
    assert "NON allargare il token" in avviso, avviso


def test_234_slash_INIZIALE_tace_perche_lo_ferma_un_gate_PIU_FORTE(monkeypatch):
    """Perché `rstrip("/")` può restare solo-coda: il caso simmetrico non arriva mai qui.

    Fable 5 e Fugu Ultra hanno notato che uno slash *iniziale* non entra nel ramo spazi/slash;
    entrambi hanno supposto che finisse nel messaggio generico «indirizzo diverso». Misurato,
    non è così: `"/https://…"` **non ha host**, quindi `is_placeholder_url` lo classifica
    placeholder (fail-closed) e `disallineamento_bridge` esce prima di qualunque confronto.

    Il silenzio è **corretto**, e per una ragione più forte: un `REVOCATION_LIST_URL` malformato
    significa revoca online inattiva per costruzione, e il **gate di release** legge quello stesso
    predicato e **blocca il tag** — non può finire in un EXE distribuito. Il caso è fermato a
    monte da una barriera più severa di un avviso, non lasciato passare.

    Questo test esiste per bloccare l'inversione: se un domani `is_placeholder_url` smettesse di
    essere fail-closed sugli URL senza host, qui si accenderebbe.
    """
    assert revocation_client.is_placeholder_url("/" + _REALE), (
        "un URL senza host deve restare placeholder: è il fail-closed su cui poggia il gate di release")

    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", "/" + _REALE)
    assert publisher.disallineamento_bridge("tizio/xtrader-revocation",
                                            "revocation_list.txt", "main") == ""


def test_234_configurazione_ESATTAMENTE_uguale_non_avvisa(monkeypatch):
    """Contro-guardia del confronto esatto: l'uguaglianza vera resta silenziosa."""
    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", _REALE)
    assert publisher.disallineamento_bridge("tizio/xtrader-revocation",
                                            "revocation_list.txt", "main") == ""


def test_234_differenza_di_SOLO_CASE_avvisa_ma_lo_DICE(monkeypatch):
    """Sempre Fable 5, e qui la scelta è delicata: si avvisa **comunque**.

    Su `raw.githubusercontent.com` branch e percorso sono **case-sensitive**: un `Main` al posto
    di `main` darebbe 404 a **tutti** i bridge, cioè esattamente il fallimento silenzioso che
    questa funzione esiste per impedire. Tacere sarebbe il difetto opposto e peggiore.

    Ma il messaggio deve dire **cos'è**: chi vede due URL che «sembrano identici» e un avviso di
    disallineamento conclude che l'avviso è rotto, e la volta dopo non lo legge.
    """
    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL",
                        "https://raw.githubusercontent.com/tizio/xtrader-revocation/Main/"
                        "revocation_list.txt")
    avviso = publisher.disallineamento_bridge("tizio/xtrader-revocation",
                                              "revocation_list.txt", "main")

    assert avviso, "un branch con case diverso è un 404 per i bridge: va detto"
    assert "maiuscole/minuscole" in avviso, avviso        # dice COS'È la differenza
    assert "case-sensitive" in avviso, avviso             # e perché conta
    assert "NON allargare il token" in avviso, avviso     # e cosa NON fare


def test_234_case_diverso_nel_solo_OWNER_REPO_non_e_un_disallineamento(monkeypatch):
    """Rilievo Fable 5 sull'intera PR, verificato contro il server reale — non dedotto.

    Su `raw.githubusercontent.com` i segmenti dell'URL **non** hanno tutti la stessa sensibilità
    alle maiuscole. Misurato con `curl` su un repository pubblico:

    ```
    …/python/cpython/main/README.rst   → 200
    …/Python/CPython/main/README.rst   → 200   ← owner/repo: case-INsensitive
    …/python/cpython/Main/README.rst   → 404   ← branch:     case-sensitive
    …/python/cpython/main/readme.rst   → 404   ← percorso:   case-sensitive
    ```

    Quindi un `Zarbopiero963-Droid/XTrader-Revocation` al posto di `zarbopiero963-droid/…`
    **funziona**: i bridge scaricano la lista, le revoche si propagano, non c'è niente da
    correggere. Avvisare lì sarebbe un **falso allarme** — e questa PR esiste per la tesi opposta,
    che un avviso falso su una configurazione giusta insegna a ignorare quello vero.

    È l'unica normalizzazione ammessa in questa funzione, e per la ragione esattamente contraria a
    quella respinta per slash e spazi: lì la misura diceva **404** (bridge rotto, silenziarlo
    sarebbe il difetto), qui dice **200** (bridge sano, avvisarlo è rumore).
    """
    monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", _REALE)

    assert publisher.disallineamento_bridge("TIZIO/XTrader-Revocation",
                                            "revocation_list.txt", "main") == ""


def test_234_case_diverso_in_BRANCH_o_PERCORSO_avvisa_ANCHE_con_owner_repo_diverso(monkeypatch):
    """Contro-guardia della normalizzazione sopra: deve toccare **solo** owner/repo.

    Se si allargasse a tutto l'URL, un `Main` al posto di `main` — che la misura dà **404** per
    tutti i bridge — verrebbe silenziato: cioè il difetto originale reintrodotto dalla porta di
    servizio, che è precisamente come è nato il giro `7ffe6c3`.
    """
    for descrizione, atteso in (
        ("branch con case diverso",
         "https://raw.githubusercontent.com/TIZIO/XTrader-Revocation/Main/revocation_list.txt"),
        ("percorso con case diverso",
         "https://raw.githubusercontent.com/TIZIO/XTrader-Revocation/main/Revocation_List.txt"),
    ):
        monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", atteso)
        avviso = publisher.disallineamento_bridge("tizio/xtrader-revocation",
                                                  "revocation_list.txt", "main")
        assert avviso, f"{descrizione}: è un 404 per tutti i bridge, non può tacere"
        assert "maiuscole/minuscole" in avviso, descrizione
        # e il testo deve dire QUALI segmenti contano, non «l'URL è case-sensitive» (falso per
        # owner/repo, come la misura dimostra)
        assert "branch e percorso" in avviso, avviso
        assert "NON allargare il token" in avviso, descrizione


def test_234_la_normalizzazione_del_case_non_silenzia_host_o_SCHEMA_diversi(monkeypatch):
    """Contro-guardia richiesta da GPT-5.5: «URL non canonici → silenziamenti inattesi?».

    `_case_normalizzata_dove_il_server_lo_e` abbassa il case anche di schema e host, ed è lì che
    un allargamento futuro farebbe il danno peggiore: un **host diverso** silenziato significa
    credere di pubblicare dove i bridge leggono mentre si pubblica altrove — la issue #234 nella
    sua forma più grave.

    Misurato: si silenziano **solo** le differenze di solo-case in schema e host, che sono
    case-insensitive per RFC 3986 (schema) e per DNS (host) — cioè sono davvero lo stesso
    indirizzo. Tutto il resto avvisa, incluso un URL troppo corto per essere interpretato.

    Onestà su cosa questo test dimostra e cosa no. Il caso «URL troppo corto» **non** è un
    presidio del ramo fail-safe: provato per sabotaggio (`return str(u).lower()` al posto di
    `return str(u)`) resta verde, perché quell'URL è già minuscolo. Il ramo `len(parti) < 5` è del
    resto **strutturalmente** incapace di produrre silenzio — un URL con meno di cinque segmenti
    non può risultare uguale ai sette dell'URL configurato, comunque lo si normalizzi. Il confine
    che conta davvero è dove la normalizzazione si ferma, ed è presidiato altrove: portandola al
    sesto segmento diventano rossi `test_234_differenza_di_SOLO_CASE_avvisa_ma_lo_DICE` e
    `test_234_case_diverso_in_BRANCH_o_PERCORSO_avvisa_ANCHE_con_owner_repo_diverso`.
    """
    casi = {
        "host DIVERSO":
            "https://evil.example.com/tizio/xtrader-revocation/main/revocation_list.txt",
        "schema http invece di https":
            "http://raw.githubusercontent.com/tizio/xtrader-revocation/main/revocation_list.txt",
        "URL troppo corto per avere owner/repo":
            "https://raw.githubusercontent.com",
    }
    for descrizione, atteso in casi.items():
        monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", atteso)
        assert publisher.disallineamento_bridge(
            "tizio/xtrader-revocation", "revocation_list.txt", "main"), (
            f"{descrizione}: NON è lo stesso indirizzo, silenziarlo è il difetto della issue")

    # ...mentre solo-case in schema e host è lo stesso indirizzo per lo standard: tacere è giusto,
    # e avvisare sarebbe il falso allarme che insegna a ignorare quello vero.
    for descrizione, atteso in {
        "host in maiuscolo (case-insensitive per DNS)":
            "https://RAW.GITHUBUSERCONTENT.COM/tizio/xtrader-revocation/main/revocation_list.txt",
        "schema in maiuscolo (case-insensitive per RFC 3986)":
            "HTTPS://raw.githubusercontent.com/tizio/xtrader-revocation/main/revocation_list.txt",
    }.items():
        monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", atteso)
        assert publisher.disallineamento_bridge(
            "tizio/xtrader-revocation", "revocation_list.txt", "main") == "", descrizione


def test_234_branch_o_PERCORSO_diverso_producono_l_avviso(monkeypatch):
    """Rilievo CodeRabbit, ed è un buco vero: negli altri test differisce solo il `repo`.

    Un'implementazione che confrontasse **solo il repository** li passerebbe tutti — e
    lascerebbe scoperti i due disallineamenti che il proprietario può introdurre con la stessa
    facilità: il branch e il percorso del file. Entrambi danno 404 ai bridge esattamente come un
    repository sbagliato, cioè zero revoche propagate.
    """
    for descrizione, atteso in (
        ("branch diverso",
         "https://raw.githubusercontent.com/tizio/xtrader-revocation/altro/revocation_list.txt"),
        ("percorso diverso",
         "https://raw.githubusercontent.com/tizio/xtrader-revocation/main/altra_lista.txt"),
    ):
        monkeypatch.setattr(revocation_client, "REVOCATION_LIST_URL", atteso)
        avviso = publisher.disallineamento_bridge("tizio/xtrader-revocation",
                                                  "revocation_list.txt", "main")
        assert avviso, f"{descrizione}: nessun avviso"
        assert "NON propagherà alcuna revoca" in avviso, descrizione
