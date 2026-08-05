"""Guardia sui `except Exception` / bare `except:` "ciechi" (issue #186 finding 4).

Un `except Exception:` (o `except BaseException:`, o un bare `except:`) cattura **qualsiasi**
errore, anche quelli inattesi: usato dove serve (best-effort/fail-safe documentati) è corretto,
ma un nuovo blind-except introdotto per sbaglio può **ingoiare silenziosamente** un bug reale.

Questo test NON vieta i blind-except: ne fotografa i **siti** in un baseline motivato e
**fallisce se cambiano** (ratchet). Così:
- aggiungere un nuovo blind-except → il sito non è nel baseline → il test FALLISCE finché non
  lo si restringe a un'eccezione specifica, OPPURE lo si motiva aggiornando il baseline;
- rimuoverne uno → il sito sparisce → il test FALLISCE per ricordare di **stringere** il
  baseline (lo mantiene onesto, come `test_build_exe_safety.py` per le opzioni PyInstaller).

## Perché per SITO e non più per conteggio (#224)

Fino alla #224 il baseline era un **numero per file**. Un numero non sa *dove*: rimuovere un
`except Exception` motivato e approvato e aggiungerne uno **nudo** in un'altra funzione dello
stesso file lasciava il totale invariato, e il gate passava. Dimostrato:

    def sana():                          def sana():
        try: pass                            pass
        except Exception:  # motivato    def altra():
            pass                             try: pass
    def altra():                             except Exception:      <- NUDO
        pass                                     pass

    conteggio: 1                         conteggio: 1     -> gate VERDE

Su `app.py` — 53 handler, ed è il modulo di START/STOP, listener, scrittura CSV e conferme
XTrader — è esattamente la classe di bug che questo gate esiste per fermare.

Ora l'identità di un sito è **(funzione, motivo)**, dove il motivo viene dal `# noqa: BLE001`
sulla riga dell'except, **per intero** (minuscolo, spazi collassati). Il baseline sta in
`blind_except_sites.py` e si rigenera con `python tools/gen_blind_except_sites.py`.

Il motivo **non è troncato**. Una prima stesura lo tagliava a 60 caratteri per assorbire le
riformulazioni di dettaglio, ma due motivi diversi con lo stesso prefisso avrebbero avuto la
stessa identità — e la sostituzione a saldo zero sarebbe ripassata proprio dalla porta che
questo gate chiude (rilievo Fugu Ultra sulla #260; misurato: 0 collisioni reali, ma 5 motivi
su 194 oltre i 60 caratteri, cioè un buco latente). Il prezzo è che riformulare un motivo
obbliga a rigenerare il baseline: accettabile, ed è ciò che serve perché il baseline dica il
vero invece di dirne una versione accorciata.

⚠️ **Un baseline aggiornato a occhi chiusi è peggio di nessun baseline**, perché dà falsa
sicurezza: quando questo test fallisce, il messaggio dice **quali** siti sono comparsi o
spariti — vanno letti, non rigenerati per far tornare il verde.

## Il debito dichiarato — estinto

Alla #224 erano **19 su 194** a non dichiarare un motivo: 11 senza alcun marcatore, 8 con un
`# noqa: BLE001` **muto**, cioè il timbro «approvato» senza il perché. Non furono inventati
motivi a posteriori — un motivo plausibile ma sbagliato è più difficile da smascherare di un
motivo assente — e il ratchet impediva solo che il numero salisse.

Sono stati poi scritti **tutti e 19, uno per uno leggendo il codice**. Nessuno ha richiesto di
indovinare: l'intento era già dimostrato dal docstring o dal ramo di fallback. `token_store`,
che da solo ne conteneva 8, dichiara in ogni docstring cosa significa il `False` che ritorna —
inclusa la distinzione che conta davvero, «lettura fallita» ≠ «token assente». `atomic_io`
cattura `BaseException` e **rilancia**: cattura larga perché il temporaneo va rimosso anche su
`KeyboardInterrupt`, non perché l'errore vada ingoiato.

Oggi `_SITI_SENZA_MOTIVO_ATTESI = 0`: il ratchet non è più un tetto sul debito, è un divieto.
"""

import ast
import importlib.util
import os

import pytest

_RADICE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_PKG = os.path.join(_RADICE, "xtrader_bridge")


def _carica_generatore():
    """Il modulo `tools/gen_blind_except_sites.py`, importato per path.

    **La scansione è UNA SOLA** (#224, Regola 3): il generatore che scrive il baseline e il
    test che lo verifica devono usare la stessa identica funzione. Se il test si riscrivesse
    la sua, le due divergerebbero alla prima modifica di una delle due — e un gate che misura
    qualcosa di diverso da ciò che il baseline registra è peggio che inutile.

    `tools/` non è un package installabile, quindi si importa per path invece che con `import`.
    """
    percorso = os.path.join(_RADICE, "tools", "gen_blind_except_sites.py")
    spec = importlib.util.spec_from_file_location("_gen_blind_except_sites", percorso)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


_GEN = _carica_generatore()

# Allowlist: per ogni modulo che ne contiene, il numero di blind-except ATTESI + il perché.
# I blind-except qui sono best-effort/fail-safe documentati (spesso con `# noqa: BLE001`):
# GUI Tk (un callback che solleva non deve buttare giù la finestra), soft-import/fallback
# (keyring/credential store: qualsiasi errore = backend non disponibile), best-effort di
# teardown/log/summary (un fallimento non critico non deve propagare nel percorso safety).
# Aggiornare SOLO con motivazione esplicita quando si aggiunge/rimuove un blind-except.
_ALLOWLIST = {
    "ui_cards.py": (5, "composizione visiva #182 (card/badge/hint) + tune_scrolling: helper best-effort "
                       "sui DOPPI dei test headless (classi generate al volo, senza Tk) e "
                       "su widget gia distrutti — la cornice non deve MAI far cadere un "
                       "pannello; nessun dato/flusso dentro, solo presentazione"),
    "dirty_csv_store.py": (3, "registro dei path CSV sporchi (P3-6 #76), FAIL-SAFE per contratto: "
                              "lettura su file assente/corrotto/schema inatteso → nessun path; "
                              "mark/clear best-effort — un I/O rotto non deve bloccare STOP/chiusura "
                              "(la marcatura avviene comunque PRIMA di armare il retry, crash-safe)"),
    "app.py": (53, "glue runtime/GUI Tk: teardown, callback after(), log e auto-start best-effort; #182 PR A: `_select_tool_tab` — navigazione fra schede dell'hub, hub chiuso/distrutto = nessuna UI da spostare; "
                   "gate revoca (#159): la traccia diagnostica del ramo fail-open è essa stessa "
                   "protetta — `_dbg` può sollevare (GUI non costruita, istanza parziale) e "
                   "l'eccezione USCIREBBE dal gate, che `_license_is_valid` non assorbe: una riga "
                   "aggiunta per osservabilità diventerebbe il blocco di un utente legittimo, vietato "
                   "dalla policy fail-open del proprietario. Qui il silenzio è il male minore; "
                   "diagnosi revoca (#212): `_license_bloccata_da_revoca` sceglie solo il MESSAGGIO "
                   "e su errore ritorna False → testo generico, mai un'accusa di revoca non "
                   "dimostrata, e mai un'eccezione che rompa il lock; "
                   "incidente 2026-08-04 (revoca invisibile + Strumenti fail-open), 4 handler: "
                   "`_revoca_nega` fail-safe su False — in dubbio NON si accusa di revoca, l'unico "
                   "blocco legittimo e' quello dimostrato da una lista firmata; "
                   "`_chiudi_finestre_operative_per_lock` gira a OGNI giro da bloccato e deve tollerare una "
                   "finestra gia' distrutta: un errore qui romperebbe il lock che deve proteggere; "
                   "`_mostra_license_banner` e `_set_license_banner` sono render Tk best-effort — un "
                   "widget distrutto non puo' impedire il BLOCCO, che resta applicato comunque; "
                   "worker probe csv_writable async (follow-up #76, nota Fable PR #94): sonda Salute "
                   "best-effort come _refresh_health — probe che solleva su share instabile non "
                   "uccide il worker, sblocca il flag inflight e si riprova al giro dopo; "
                   "pannello Assistente (#41 PR-3) best-effort: costruzione che fallisce → label di "
                   "fallback invece di rompere la finestra; teardown del suo thread worker best-effort "
                   "in _on_close; "
                   "event journal best-effort (#230); refill campo token su widget Tk distrutto (PR-08c); "
                   "resolver ID del dizionario locale best-effort (#192: DB assente → None, il flusso "
                   "resta a nomi senza crashare); "
                   "controller del viewer «Dizionario» best-effort (#20: DB non apribile → controller "
                   "None, il pannello mostra l'avviso invece di crashare la costruzione della scheda); "
                   "after_cancel del retry post-stop clear CSV su id scaduto/invalido (#259 A1; "
                   "P3-8 #76: secondo sito nel ri-arm per-path — cancel del timer precedente dello "
                   "stesso path, best-effort come in _on_close); "
                   "known_teams/competitions/teams del dizionario locale per precompilare la mappatura "
                   "nomi e il «Mapping guidato» best-effort (#282: DB assente → [], la GUI non crasha); "
                   "delete_known_team best-effort (#282 PR 11-bis: DB assente → False); "
                   "known_market_terms best-effort (#283 PR 13: DB assente → liste vuote); "
                   "snapshot Riepilogo config best-effort (#293 slice 3: conteggio del dizionario "
                   "locale → DB occupato/assente degrada a False, il riepilogo sola-lettura non "
                   "deve mai crashare); "
                   "avviso «già in esecuzione» su root Tk temporanea best-effort (#311-1.1: "
                   "in headless/display assente l'uscita della seconda istanza avviene comunque); "
                   "dialog conferma COLLAUDO (#311 §3.1): errore dialog → NON confermare "
                   "(fail-closed, stesso pattern di _confirm_real_mode/_confirm_multi_signal); "
                   "_refresh_health interamente best-effort (Fable #351): una sonda che solleva "
                   "(share instabile, config corrotta) non deve MAI rompere il monitoraggio "
                   "primario ne' i chiamanti _set_last/START/STOP/save; "
                   "apertura Wizard best-effort (#311 §3.4: un Toplevel che fallisce mostra "
                   "la classe dell'errore nel log invece di rompere la finestra principale); "
                   "singleton Wizard (Fable #354): riferimento stantio con winfo_exists che "
                   "solleva (Tk smontato) → si riapre un wizard nuovo invece di crashare; "
                   "lift/focus_force best-effort sul wizard vivo (GPT #354: un errore di "
                   "focus non deve degradare in un secondo Toplevel modale doppione); "
                   "selettore lingua al primo avvio (#343): apertura best-effort (senza "
                   "scelta resta il comportamento storico IT e si ripropone al prossimo "
                   "avvio) + destroy best-effort del selettore su widget già distrutto; "
                   "LOCK LICENZA (#140 PR 4): gate `_license_is_valid` FAIL-CLOSED (qualunque "
                   "errore nel calcolo stato → bloccato, mai aperto); `_set_operational_lock` e i "
                   "`configure(state=)` di START in `_apply_license_lock` best-effort per-widget "
                   "(un CTkLabel/widget senza `state` o distrutto non deve rompere il lock); "
                   "`after`/`after_cancel` del tick licenza best-effort su root distrutta "
                   "(stesso pattern dei timer in _on_close); il tick `_license_tick` non deve "
                   "morire se il gate solleva (si ri-arma comunque); "
                   "REVOCA online (#140 R3c): (1) gate `_revocation_gate_ok` FAIL-CLOSED (qualunque "
                   "errore nel determinare token/hwid o nel calcolo → bloccato, mai aperto); "
                   "(2) ciclo del supervisore `_revocation_loop` non deve morire per un errore "
                   "imprevisto (ritenta al giro dopo con l'intervallo di refresh)"),
    "guided_mapping_gui.py": (3, "GUI Tk «Mapping guidato» best-effort (Fase 3): lettura config "
                                 "illeggibile → messaggio; lettura competizioni/squadre Betfair "
                                 "con DB assente/illeggibile → tendina/elenco vuoti; nessuno di "
                                 "questi deve crashare la finestra Strumenti (il caso 'sync in "
                                 "corso' è gestito a parte, non-blind, con DictionaryBusy)"),
    "atomic_io.py": (1, "cleanup del temporaneo su QUALSIASI errore di scrittura/rename (BaseException)"),
    "wizard_gui.py": (4, "vista Wizard (#311 §3.4, review Fable #354): (1) sonda in thread "
                         "che solleva → esito FAIL-CLOSED con la sola classe dell'errore e "
                         "flag _probe_running SEMPRE rilasciato (mai ⏳ eterna); (2) after() "
                         "su finestra/Tk distrutti durante la sonda → niente da aggiornare; "
                         "(3) winfo_exists che solleva a interprete smontato = finestra chiusa; "
                         "(4) valutazione step 3 (cfg_provider iniettato E check_parser col "
                         "contesto; P2-8 #76, review #82 round 2 GPT/Fugu + final Fable) che "
                         "solleva → esito FAIL-CLOSED sanificato (StepResult ⛔ e return, MAI "
                         "degrado al parser nudo: sarebbe fail-open), mai crash del wizard"),
    "wizard.py": (3, "sonde one-shot del Wizard (#311 §3.4): getMe/getUpdates/scrittura "
                     "di prova — qualsiasi errore diventa un esito FAIL-CLOSED col messaggio "
                     "SANIFICATO (mai il token/URL nell'errore), lo step non passa e il "
                     "wizard non crasha"),
    "parser_builder.py": (1, "isolamento PER-MESSAGGIO del tester batch (#311 §3.2, CodeRabbit "
                             "#350): un messaggio patologico non deve abortire il batch "
                             "nascondendo gli altri report — l'errore resta VISIBILE nel "
                             "verdetto ❌ di quel messaggio (fail-visible, mai silenzioso)"),
    "instance_lock.py": (2, "#311-1.1 single-instance: fail-open CONSAPEVOLE su errore imprevisto "
                         "del SO nella creazione del lock (un bridge inavviabile per un guasto raro "
                         "è peggio del caso limite; warning nei log) + release best-effort (a morte "
                         "processo rilascia comunque il SO: mutex named / flock)"),
    "config_store.py": (3, "backup config corrotta best-effort + rollback keyring best-effort + "
                           "gate #311-2.3 `_default_recognition_mode` fail-safe → NAME_ONLY"),
    "config_summary_gui.py": (1, "GUI Tk scheda Riepilogo (#293 slice 3, sola lettura): il "
                             "summary_provider che solleva mostra un avviso invece di rompere "
                             "la finestra (stesso pattern best-effort degli altri pannelli)"),
    "csv_writer.py": (1, "callback diagnostico best-effort di clear_stale_csv: un sink log/GUI che "
                         "solleva non deve rompere il cleanup anti-segnale-stantio all'avvio/STOP (#241)"),
    "dizionario.py": (1, "gate #311-2.3 `is_validated` fail-safe: dizionario assente/header rotto → "
                         "non validato (False) → default recognition_mode resta NAME_ONLY, mai BOTH su "
                         "dati inaffidabili"),
    "custom_parser_gui.py": (21, "GUI Tk del costruttore parser: render/azioni best-effort (#182 PR A, 4 nuovi: `_parser_usage` config illeggibile = nessun marcatore ma elenco usabile — l'except copre SOLO la lettura del file, le tre letture di routing di `parser_manager` stanno FUORI così un nome di API sbagliato esplode invece di svuotare il badge in silenzio (rilievo Fugu #223); `_autoload_active_parser` parser attivo corrotto = editor vuoto, non un pannello che non si apre; `_open_provider_registry` hub irraggiungibile = fallback all'aggiunta rapida; `_highlight_saved` widget distrutto durante un refresh; #182 PR A ⑥, 2 nuovi: `_riga_ha_valore_fisso` widget assente = nessun avviso, `_mostra_avviso_valore_fisso` widget distrutto durante un refresh; review Fugu/GPT-5.5 #223: `bind_accetta_add` firma non ispezionabile = si assume il Tk vero e si sceglie la forma NON distruttiva `add="+"`, più `_segui_valore_fisso`, 2 — variabile non tracciabile, widget non legabile: nessun ri-aggancio su quell'evento ma si prova comunque il successivo e la riga si disegna) (P3-28 #76: _builder_snapshot fail-safe — stato non fotografabile = modificato, meglio una conferma in più che una perdita silenziosa); "
                             "(incl. resolver ID anteprima fail-open, #192; termini Betfair "
                             "per le tendine MarketType/MarketName/SelectionName best-effort, "
                             "#283 PR 13: sync in corso/DB assente → nessun suggerimento; "
                             "risoluzione profili nomi + lingua-fonte anteprima da config, "
                             "#3 slice 5b: config illeggibile → nessun filtro, fail-safe)"),
    "custom_pipeline.py": (3, "id_resolver iniettato: un resolver che solleva NON blocca la riga (fail-open); "
                              "_default_registry (P3-14 #76): dizionario bundled corrotto/mancante -> fallback "
                              "built-in in cache con warning, MAI eccezione per-messaggio nell'handler Telegram; "
                              "ultimo-resort sul ramo built-in (follow-up nota Fable PR #108): anche se il "
                              "fallback stesso solleva -> registro VUOTO cacheato con error log, ogni value-map "
                              "risolve a vuoto (fail-closed), mai un crash per-messaggio"),
    "dpi_awareness.py": (3, "#311 §3.5 fail-open per contratto: un fallimento DPI "
                            "(ctypes/windll assente, shcore mancante su Win<8.1, "
                            "awareness già impostata, API che solleva) non deve MAI "
                            "impedire l'avvio del bridge — esito testuale, mai raise"),
    "gui_utils.py": (3, "helper GUI best-effort; ask_confirm FAIL-CLOSED (P3-27/28 #76): dialog rotto/headless → False, un'azione distruttiva non parte mai senza conferma esplicita · +1 #176 running_edit_notice: la sonda `is_running` è iniettata dal chiamante e solo INFORMATIVA (decide un avviso, non una scrittura); se solleva si assume bridge fermo e si ritorna \"\" — una sonda difettosa non deve né impedire un salvataggio né inventare un avviso"),
    "journal_view_gui.py": (2, "GUI Tk scheda Diario (#236): lettura ledger best-effort "
                            "(avviso invece di crash) e apertura cartella best-effort"),
    "known_teams_gui.py": (2, "GUI Tk ripulitura nomi Betfair (#282 PR 11-bis): lettura e "
                           "eliminazione best-effort (avviso invece di crash; DictionaryBusy "
                           "gestita a parte per il fail-fast durante la sync)"),
    "name_mapping_gui.py": (11, "GUI Tk mapping: render/azioni best-effort; "
                            "precompila nomi Betfair best-effort (#282 PR 11: provider "
                            "che solleva → avviso, nessun crash); #182 PR B, 3 nuovi nella "
                            "colonna profili sempre visibile: `_profile_var.trace_add` "
                            "(variabile non tracciabile = nessuna evidenziazione viva, ma "
                            "l'elenco resta usabile), `_profile_usage` (cartella parser "
                            "illeggibile = nessun badge 🧩 ma i profili si aprono comunque) e "
                            "`_highlight_profiles` (widget distrutto durante un refresh); #182 PR C, 1 nuovo: "
                            "il `trace_add` gemello nel pannello 🎯 Mercati, stessa ragione"),
    "provider_gui.py": (5, "GUI Tk provider: render/azioni best-effort; #182 PR E, 2 nuovi: "
                        "`_provider_usage` (cartella parser illeggibile → nessun marcatore "
                        "«🧩 N parser», ma l'anagrafica resta gestibile) e l'elenco dei parser "
                        "colpiti nella conferma di rimozione (parser illeggibili → conferma "
                        "senza elenco invece di bloccare la rimozione)"),
    "ui_widgets.py": (2, "#182: `rendi_attivabile` mette la riga-elenco nel giro del Tab; "
                      "`configure(takefocus=1)` è best-effort perché su un widget-spia dei "
                      "test o su un widget distrutto durante un refresh può sollevare, e non "
                      "poter rendere focusabile una riga non deve impedire di DISEGNARLA "
                      "(resta comunque cliccabile col mouse). PR C, 1 nuovo: `evidenzia_profilo` "
                      "ricolora le righe e un widget distrutto durante un refresh non deve far "
                      "saltare l'evidenziazione delle altre"),
    "reconnect_policy.py": (1, "classificazione errore di reconnect tollerante"),
    "source_chats_gui.py": (2, "GUI Tk sorgenti: best-effort (refresh-options + modal transient/grab_set)"),
    "config_agent.py": (12, "assistente di configurazione (#41 PR-1): dispatch di un tool "
                           "sola-lettura best-effort (un handler che solleva NON deve crashare "
                           "l'agente → errore restituito come contenuto); logging dell'audit "
                           "best-effort (un logger che solleva non deve far fallire il dispatch); "
                           "soft-import 'anthropic' (dipendenza opzionale: assenza = errore chiaro "
                           "solo all'uso reale, mai all'import del modulo); tester «Prova messaggio» "
                           "(#41 PR-8 Blocco B): un parser attivo malformato non deve crashare "
                           "l'assistente → l'errore diventa un messaggio guida, mai scrittura; "
                           "«Consulta dizionario» (#41 PR-9 Blocco C): dizionario non incluso/"
                           "illeggibile (es. EXE senza data/) → fail-safe, sezione marcata non "
                           "disponibile, mai crash; diagnosi (#41 PR-10 Blocco D): un health_provider "
                           "dell'app difettoso → ripiego su valutazione da config; risoluzione del "
                           "path del diario che fallisce → fail-safe (nessun evento), mai crash; "
                           "redazione chat_id centralizzata (audit #137): il provider dei chat_id "
                           "legge la config, e una config illeggibile non deve far crashare "
                           "l'assistente → si degrada alla sola redazione dei segreti. Accettabile "
                           "perché quella nel dispatcher è la SECONDA rete: la prima "
                           "(`_redact_config`, redazione strutturata del JSON) resta in piedi"),
    "config_agent_controller.py": (7, "controller assistente (#41 PR-3/PR-4): emit di un evento verso "
                                      "la view best-effort (un handler della GUI che solleva non deve "
                                      "rompere il controller); un turno che solleva nel worker non "
                                      "uccide il loop (errore restituito come turno); persistenza "
                                      "cronologia best-effort (qualsiasi errore di save non deve "
                                      "scartare il turno già calcolato, CodeRabbit #64); in "
                                      "apply_pending il LOADER e il SAVER che sollevano sono trattati "
                                      "come config non disponibile / save fallito, mai crash del "
                                      "thread GUI (GPT/Fable/Fugu #65); in enable() un config_loader "
                                      "difettoso nel leggere app_language non impedisce l'avvio "
                                      "dell'assistente (default lingua IT, #41 PR-7 Blocco A); in "
                                      "redact_for_log un config_loader difettoso non impedisce di "
                                      "loggare la riga coi soli segreti registrati redatti (AC-M9 #114)"),
    "config_agent_gui.py": (3, "view assistente (#41 PR-3/PR-4): marshalling evento via after() su "
                               "root Tk distrutta/assente (teardown) best-effort; log della riga di "
                               "trascritto best-effort; nascondere il banner di conferma su widget "
                               "già distrutto (teardown) best-effort"),
    "token_store.py": (8, "soft-import/fallback keyring: qualsiasi errore = backend non disponibile "
                          "(bot token + API key Anthropic #41: save/load-status/delete per la chiave)"),
    "tools_gui.py": (3, "GUI Tk finestra strumenti: apertura sotto-finestre best-effort"),
    "write_path.py": (3, "write-failure fail-safe: la scrittura CSV fallita non deve crashare → "
                         "rollback di coda/guardrail ed errore riportato, in commit_signal, "
                         "commit_signals (multi-riga #192) e nel riallineamento del disco stantio "
                         "(_realign_dirty_disk, D1 audit #114: la riscrittura di realign fallita è "
                         "riportata al chiamante, disco resta stantio col retry pendente)"),
    "betfair/dictionary_viewer_gui.py": (2, "GUI Tk viewer dizionario best-effort: lettura "
                                            "dizionario e stile Treeview (Fase 2) non devono "
                                            "crashare la finestra Strumenti"),
    "licensing/ed25519.py": (1, "verifica firma Ed25519 (#140 PR 1) FAIL-CLOSED: qualunque input "
                                "malformato (punto non sulla curva, lunghezze errate, s fuori "
                                "range) = firma NON valida → False, mai un'eccezione che aggiri il "
                                "gate licenza"),
    "licensing/hwid.py": (3, "impronta Hardware ID (#140 PR 1): le 3 sorgenti reali (MachineGuid "
                             "registro, seriale volume ctypes, MAC) sono best-effort e solo-Windows "
                             "→ sorgente assente/non leggibile = omessa, l'impronta resta stabile "
                             "sulle altre senza crashare"),
    "licensing/license.py": (3, "verifica licenza (#140 PR 1) FAIL-CLOSED: (1) token corrotto/"
                                "incompleto = MALFORMED; (2) chiave pubblica hex malformata = "
                                "INVALID_SIGNATURE → una licenza non verificabile non sblocca mai; "
                                "(3) `_b64u_canonico` (B2, PR-C #194): una parte non decodificabile "
                                "è per definizione non canonica → False, cioè MALFORMED. L'except "
                                "è ampio di proposito perché il valore arriva da un token non "
                                "fidato e QUALUNQUE errore deve valere «rifiuta», mai «accetta»"),
    "licensing/revocation.py": (3, "lista di revoche (#140 revoca online) FAIL-CLOSED in "
                                   "verify_revocation_list: (1) envelope corrotto/non decodificabile, "
                                   "(2) chiave pubblica hex malformata, (3) payload non conforme "
                                   "(versione/tipi) → in tutti i casi la lista NON è fidata (ritorna "
                                   "None): una lista di revoche non verificabile non blocca né sblocca "
                                   "per errore, la policy è del bridge chiamante"),
    "licensing/revocation_client.py": (1, "client bridge revoca online (#140 R3c) FAIL-CLOSED in "
                                          "fetch_signed: qualunque errore di scarico dell'URL (rete, "
                                          "DNS, HTTP, timeout, TLS, decodifica, lista troppo grande) → "
                                          "None: mai una lista non verificata trattata come buona. "
                                          "NB la CONSEGUENZA a valle è cambiata il 2026-07-30 e la "
                                          "motivazione era rimasta stantia (rilievo CodeRabbit #235): "
                                          "nessuna lista fresca NON blocca più (gate fail-open, "
                                          "`gate_allows`) — si ferma la propagazione delle revoche, "
                                          "non il bridge. Fail-closed resta il PARSING qui: un errore "
                                          "di rete/formato non produce mai una lista valida"),
    "license_store.py": (2, "persistenza licenza (#140 PR 2) FAIL-SAFE: (1) file corrotto/illeggibile "
                            "in load → (None, None) «nessuna licenza», mai crash; (2) rimozione "
                            "best-effort in clear. Coerente col fail-closed della verifica"),
    "license_gui.py": (7, "schermata Licenza (#140 PR 2): (1) copia appunti best-effort, (2) lettura "
                          "campo in teardown/headless, (3) render Tk best-effort — non rompono la scheda; "
                          "(4) save all'ATTIVAZIONE FAIL-CHIUSA (persistenza fallita = attivazione non "
                          "riuscita, stato precedente intatto, CodeRabbit #144); (5) provider difettoso in "
                          "current_status degrada a stato neutro senza rompere il chiamante (Fable #144); "
                          "(6) heartbeat anti-rollback: tollera i fallimenti transitori, FAIL-CHIUSO sui "
                          "PERSISTENTI (≥ _HEARTBEAT_FAIL_LIMIT consecutivi) — review GPT/Fable #144; "
                          "(7) `_revoca_nega` (incidente 2026-08-04): seam revoca difettoso → False, "
                          "cioè NESSUNA accusa di revoca non dimostrata. Un utente in regola mandato "
                          "dal fornitore per un bug nostro chiederebbe una licenza che ha già"),
}


def _siti_attuali():
    """Siti attuali, con la STESSA scansione del generatore del baseline."""
    return _GEN.scansiona(_PKG)


def _siti_baseline():
    from tests.safety.blind_except_sites import SITI
    return SITI


def test_nessun_blind_except_nuovo_o_non_motivato():
    attuali = _siti_attuali()
    baseline = _siti_baseline()

    # File con blind-except ma NON in allowlist → nuovo file non motivato.
    fuori_allowlist = sorted(set(attuali) - set(_ALLOWLIST))
    assert not fuori_allowlist, (
        "Blind-except (`except Exception`/bare `except:`) in moduli NON in allowlist: "
        f"{ {f: len(attuali[f]) for f in fuori_allowlist} }. "
        "Restringili a un'eccezione specifica, oppure aggiungi il file a _ALLOWLIST con il motivo.")

    # Confronto per SITO, non per conteggio: è ciò che chiude la sostituzione a saldo zero.
    # Multiset, non insieme: due handler identici nella stessa funzione sono due siti, e
    # rimuoverne uno solo deve farsi notare.
    from collections import Counter
    comparsi, spariti = {}, {}
    for f in sorted(set(attuali) | set(baseline)):
        a, b = Counter(attuali.get(f, ())), Counter(baseline.get(f, ()))
        if a == b:
            continue
        piu, meno = a - b, b - a
        if piu:
            comparsi[f] = sorted(piu.elements())
        if meno:
            spariti[f] = sorted(meno.elements())

    assert not (comparsi or spariti), (
        "I siti blind-except non combaciano col baseline.\n"
        f"COMPARSI (nuovi o spostati qui): {comparsi or '—'}\n"
        f"SPARITI  (rimossi o spostati altrove): {spariti or '—'}\n"
        "LEGGI queste righe prima di rigenerare. Un sito comparso senza motivo, o comparso in "
        "una funzione diversa a saldo zero, è precisamente ciò che questo gate esiste per "
        "fermare. Se il cambiamento è voluto e motivato: "
        "`python tools/gen_blind_except_sites.py` e committa il diff del baseline.")


def test_il_conteggio_dell_allowlist_resta_agganciato_ai_siti():
    """Il numero in `_ALLOWLIST` è il riassunto leggibile; `SITI` è l'identità verificabile.
    Questo test li tiene agganciati, così il riassunto non può mentire sul dettaglio."""
    baseline = _siti_baseline()
    disallineati = {f: (n, len(baseline.get(f, ())))
                    for f, (n, _motivo) in _ALLOWLIST.items() if n != len(baseline.get(f, ()))}
    assert not disallineati, (
        f"conteggio _ALLOWLIST ≠ numero di siti in blind_except_sites.py (allowlist, siti): "
        f"{disallineati}")


# Debito ESTINTO. Alla #224 erano 19 (11 senza marcatore, 8 con un `# noqa: BLE001` MUTO —
# il timbro «approvato» senza motivazione); tutti e 19 sono stati scritti leggendo cosa il
# codice dimostra di fare, non indovinando. A zero il ratchet diventa una regola secca: ogni
# blind-except deve dire perché, senza eccezioni residue.
_SITI_SENZA_MOTIVO_ATTESI = 0


def test_il_debito_dei_siti_senza_motivo_non_cresce():
    """Ratchet sul debito — ora a zero, quindi di fatto un divieto.

    Alla #224 il debito era 19 e restava dichiarato: non erano state inventate motivazioni a
    posteriori, perché un motivo plausibile ma sbagliato è più difficile da smascherare di un
    motivo assente. I 19 sono stati poi scritti **uno per uno leggendo il codice**: in ogni
    caso l'intento era già dimostrato dal docstring della funzione o dal ramo di fallback (es.
    `token_store` dichiara in ogni docstring cosa significa il `False` che ritorna), quindi
    trascriverlo non è stato indovinare.

    A zero il ratchet non tollera più margine: un blind-except nuovo senza `# noqa: BLE001
    <perché>` fallisce subito. Il ramo `<` resta e serve: se un domani un handler viene
    rimosso, obbliga ad abbassare ancora invece di lasciare spazio libero che si riempie in
    silenzio.
    """
    attuali = _siti_attuali()
    senza = sorted(f"{f}::{fn}" for f, siti in attuali.items() for fn, motivo in siti if not motivo)
    assert len(senza) <= _SITI_SENZA_MOTIVO_ATTESI, (
        f"siti blind-except senza motivo: {len(senza)} (attesi al massimo "
        f"{_SITI_SENZA_MOTIVO_ATTESI}). Nuovi senza motivazione:\n" + "\n".join(senza) +
        "\n\nOgni blind-except nuovo deve portare `# noqa: BLE001 <perché>` sulla sua riga.")
    if len(senza) < _SITI_SENZA_MOTIVO_ATTESI:
        pytest.fail(
            f"il debito è SCESO a {len(senza)}: ottimo, ma abbassa "
            f"_SITI_SENZA_MOTIVO_ATTESI a {len(senza)} per non lasciare margine libero.")


def _count_in_snippet(code: str) -> int:
    """Blind-except in uno snippet, contati col rilevatore **vero** — quello del generatore.

    Prima della #224 questo helper aveva una copia locale di `_handler_is_blind`: il test sui
    tuple verificava quindi la copia, non il rilevatore che scansiona davvero il package. Se
    quest'ultimo avesse perso il caso `except (Exception, X)`, il test sarebbe rimasto verde
    mentre il gate smetteva di vederlo. Una copia in meno, un modo in meno di divergere.
    """
    return sum(1 for n in ast.walk(ast.parse(code))
               if isinstance(n, ast.ExceptHandler) and _GEN.is_blind(n))


def test_rileva_handler_a_tupla_che_include_exception():
    # Codex P2 (#232): un handler a TUPLA che include Exception/BaseException è un blind-catch
    # e va contato — altrimenti `except (Exception, X):` sfuggirebbe alla guardia.
    assert _count_in_snippet("try:\n pass\nexcept (Exception, ValueError):\n pass\n") == 1
    assert _count_in_snippet("try:\n pass\nexcept (ValueError, BaseException):\n pass\n") == 1
    # bare / nome singolo restano contati
    assert _count_in_snippet("try:\n pass\nexcept Exception:\n pass\n") == 1
    assert _count_in_snippet("try:\n pass\nexcept:\n pass\n") == 1
    # tuple SOLO di eccezioni specifiche NON è cieco → non contato
    assert _count_in_snippet("try:\n pass\nexcept (ValueError, KeyError):\n pass\n") == 0
    assert _count_in_snippet("try:\n pass\nexcept ValueError:\n pass\n") == 0


def test_un_except_in_una_CLOSURE_e_attribuito_alla_funzione_INTERNA(tmp_path):
    """Un `except` dentro una funzione annidata appartiene alla funzione **interna**.

    Prima della correzione (rilievo Fable 5 sulla #260) la mappa qualname visitava la funzione
    esterna per prima e `setdefault` gliela assegnava, quindi il baseline diceva
    `App._safe_shutdown_tg` per un handler che vive in `_shutdown`. Due danni:

    - il nome nel baseline **mentiva**, e il nome è tutto ciò che questo gate offre a chi legge
      un fallimento;
    - uno spostamento di un except **fra la closure e la funzione che la contiene** non
      cambiava l'identità → non veniva visto, che è esattamente il buco che la #224 chiude.

    Erano 5 casi reali, fra cui `_safe_shutdown_tg._shutdown`, `_kick_csv_probe_async._worker`
    e `commit_signals._realign_dirty_disk`.
    """
    modulo = tmp_path / "m.py"
    modulo.write_text(
        "class C:\n"
        "    def esterna(self):\n"
        "        def interna():\n"
        "            try: pass\n"
        "            except Exception:  # noqa: BLE001 - dentro la closure\n"
        "                pass\n"
        "        try: pass\n"
        "        except Exception:  # noqa: BLE001 - fuori, nella esterna\n"
        "            pass\n", encoding="utf-8")

    siti = _GEN.scansiona(str(tmp_path))["m.py"]
    nomi = {fn for fn, _motivo in siti}
    assert nomi == {"C.esterna", "C.esterna.interna"}, nomi


def test_ogni_voce_allowlist_ha_un_motivo():
    # Ogni voce del baseline DEVE avere una motivazione non vuota (l'audit chiede una lista motivata).
    for f, (n, reason) in _ALLOWLIST.items():
        assert n > 0, f"voce baseline con conteggio non positivo: {f}"
        assert isinstance(reason, str) and reason.strip(), f"voce baseline senza motivo: {f}"
