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
        assert "SPAZI o SLASH finali" in avviso, coda
        assert "404" in avviso, coda
        assert repr(_REALE + coda) in avviso, "il repr rende VISIBILE la differenza invisibile"


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
