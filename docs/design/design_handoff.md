# XTrader Signal Bridge — Design Handoff

> **Scopo di questo documento.** Dare a chi si occupa del **design** (UI/UX) **tutto**
> ciò che serve per capire il prodotto e ridisegnarlo senza rompere la logica di
> sicurezza: cos'è l'app, chi la usa, ogni schermata, ogni controllo, ogni stato, ogni
> messaggio, i colori attuali, il glossario di dominio e — soprattutto — **cosa NON si
> può cambiare** perché tocca la sicurezza (soldi veri).
>
> Non è una richiesta di implementazione: è un **brief di contesto**. Il codice resta la
> fonte di verità; qui trovi la mappa completa per proporre un design coerente.
>
> Fonti: `README.md`, `docs/custom_parser.md`, `docs/xtrader_csv_contract.md`,
> `docs/audit/mercati_mapping_design.md` e lettura diretta dei moduli GUI
> (`xtrader_bridge/app.py` e i vari `*_gui.py`).

---

## Indice

1. [Il prodotto in una frase](#1-il-prodotto-in-una-frase)
2. [Contesto, utente, piattaforma](#2-contesto-utente-piattaforma)
3. [Stack tecnico attuale (vincoli di design)](#3-stack-tecnico-attuale-vincoli-di-design)
4. [Principi di design (safety-first)](#4-principi-di-design-safety-first)
5. [Mappa dell'app (information architecture)](#5-mappa-dellapp-information-architecture)
6. [Finestra principale — dettaglio completo](#6-finestra-principale--dettaglio-completo)
7. [Hub Strumenti e finestre secondarie](#7-hub-strumenti-e-finestre-secondarie)
8. [Stati dinamici e indicatori](#8-stati-dinamici-e-indicatori)
9. [Flussi critici e dialoghi di conferma](#9-flussi-critici-e-dialoghi-di-conferma)
10. [Palette colori e stile attuale](#10-palette-colori-e-stile-attuale)
11. [Inventario copy / microcopy](#11-inventario-copy--microcopy)
12. [Glossario di dominio](#12-glossario-di-dominio)
13. [Invarianti di sicurezza — cosa NON toccare](#13-invarianti-di-sicurezza--cosa-non-toccare)
14. [Pain point e opportunità di design](#14-pain-point-e-opportunità-di-design)
15. [Deliverable utili al team](#15-deliverable-utili-al-team)

---

## 1. Il prodotto in una frase

**XTrader Signal Bridge** è un'app desktop Windows che fa da **ponte** tra i messaggi di
una chat/canale **Telegram** e il software **XTrader** (TradingSportivo): legge i segnali,
li traduce nel formato CSV che XTrader monitora, e svuota il CSV dopo un timeout.

```text
Telegram corretto → parsing corretto → CSV corretto → XTrader legge → CSV pulito
```

Il bridge **non piazza scommesse**: scrive solo il CSV. È XTrader a piazzare. Per
sicurezza parte di default in **simulazione** (`dry_run=true`): riconosce i segnali ma
**non** scrive il CSV operativo.

---

## 2. Contesto, utente, piattaforma

- **Utente tipo:** una singola persona (il proprietario/trader) che usa l'app sul proprio
  PC Windows. Non è un utente tecnico-sviluppatore: sa usare Telegram e XTrader, non il
  terminale. Deve poter configurare tutto **dalla GUI**, senza toccare file JSON.
- **Uso reale:** l'app gira **in background** per ore/giorni mentre arrivano i segnali.
  Spesso **minimizzata**. Deve essere leggibile "con un colpo d'occhio" (l'utente ci torna
  ogni tanto per controllare che sia ATTIVO e che non ci siano errori).
- **Posta in gioco:** **soldi veri.** Un errore di UX (attivare la modalità reale per
  sbaglio, non accorgersi che è attiva, configurare la chat sbagliata) può generare
  scommesse reali indesiderate. Il design deve **rendere impossibile sbagliare per caso**.
- **Piattaforma primaria:** **Windows desktop**. (Su Linux/macOS gira solo in dev/CI.)
- **Lingua UI:** **italiano** (tutte le label sono in italiano, con emoji).
- **Distribuzione:** EXE singolo generato via GitHub Actions (`XTrader-Signal-Bridge.exe`).
- **DPI e schermi piccoli (#311 §3.5):** l'app si dichiara **DPI-aware** all'avvio
  (per-monitor, prima della root Tk): su Windows con scaling 125–150% il testo è nitido
  (niente bitmap-stretch) e le misure sono in pixel reali; fallimento fail-open (l'app
  parte comunque). Tutte le finestre passano da `fit_to_screen`, che clampa **altezza E
  larghezza** all'area schermo disponibile (margine 80px) con pavimento al `minsize`
  dichiarato: anche le finestre larghe (Strumenti/dizionario, fino a 1140px) restano
  interamente visibili su schermi 1024px.

---

## 3. Stack tecnico attuale (vincoli di design)

- **Toolkit GUI:** [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) (`ctk`)
  sopra Tkinter. È un layer di widget "moderni" su Tkinter.
- **Tema:** default **scuro** (`set_appearance_mode("dark")` + `set_default_color_theme("blue")`,
  accento blu). Dalla #288 Delta 1 è **commutabile** chiaro/scuro con un **toggle nell'header**
  (icona 🌙/☀️): la preferenza è persistita in `config.json` (chiave `theme`, valori `dark`/`light`,
  default `dark`, fail-closed) e riapplicata all'avvio. I widget standard CustomTkinter si
  ri-tematizzano da soli; dalla **#288 Delta 3** i **colori semantici di stato** sono resi
  **theme-aware** `(light, dark)` con leggibilità (contrasto WCAG) verificata in CI (vedi «Palette»).
  Restano tinta-unita i pulsanti d'azione e i colori secondari `_set_last` → ulteriore rifinitura
  estetica è follow-up di **Delta 3** (issue #288).
- **Widget disponibili** (ciò che il toolkit offre e che il design può assumere come
  building block): finestra (`CTk`), frame con `corner_radius` e `fg_color`, `CTkLabel`,
  `CTkButton` (con `fg_color`/`hover_color`), `CTkEntry` (anche password con `show="●"`),
  `CTkOptionMenu` (dropdown), `CTkCheckBox`, `CTkTextbox`, `CTkTabview` (tab), 
  `CTkScrollableFrame`, `CTkInputDialog` (input modale), più i `messagebox` classici di
  Tkinter (`askyesno`, ecc.).
- **Limiti pratici del toolkit** (importanti per il design): non è un motore UI moderno
  tipo web/Qt. Niente vera tabella/`DataGrid` nativa (le "tabelle" sono griglie di label
  in `CTkScrollableFrame`), animazioni limitate, tipografia limitata ai font di sistema,
  layout a griglia/pack. Un redesign può proporre pattern nuovi ma va tenuto conto di
  ciò che CustomTkinter può realizzare senza riscrivere il toolkit.
- **Versione app:** `0.1.0` (mostrata nel titolo finestra).

> Se il redesign implica **cambiare toolkit** (es. passare a un UI framework più ricco),
> va segnalato come decisione esplicita: è fuori scope "estetico" e ha impatto tecnico.

---

## 4. Principi di design (safety-first)

Questi principi nascono dal dominio (soldi veri) e devono guidare ogni scelta:

1. **La sicurezza è visibile, sempre.** Lo stato "reale vs simulazione" non deve mai essere
   ambiguo. Oggi c'è un **banner rosso persistente** in modalità reale: qualunque redesign
   deve mantenere un segnale **impossibile da ignorare**.
2. **Le azioni pericolose sono "frictionful".** Attivare la modalità reale richiede di
   **digitare la parola `REALE`**; attivare modalità multi-segnale richiede conferma. Il
   design deve preservare (o migliorare) questo attrito **intenzionale**.
3. **Stato operativo leggibile a colpo d'occhio.** ATTIVO / OFFLINE / RICONNESSIONE, righe
   attive N/M, ultimo errore: devono essere immediatamente comprensibili anche da lontano.
4. **Configurazione senza toccare file.** Tutto ciò che serve va fatto dalla GUI. Il design
   deve rendere la configurazione lineare (l'app ha molte opzioni: serve gerarchia chiara).
5. **Errori parlanti.** Se il bridge non parte, l'utente deve capire **perché** (manca il
   token? manca la chat? timeout non valido?).
6. **Privacy dei dati sensibili.** Token mai mostrato in chiaro/log; testo dei messaggi non
   loggato di default. La UI non deve esporre segreti.
7. **Prevedibilità.** L'app deve comportarsi come l'utente si aspetta: START avvia, STOP
   ferma, chiudere la finestra ferma tutto.

---

## 5. Mappa dell'app (information architecture)

L'app è **una finestra principale** + un **hub "Strumenti"** che apre finestre/pannelli
di configurazione avanzata.

```text
FINESTRA PRINCIPALE  (720×760, larghezza fissa, altezza ridimensionabile)
│
├── Header
│     ├─ Titolo "🤖  XTrader Signal Bridge"
│     ├─ Toggle tema chiaro/scuro (icona 🌙/☀️, #288 Delta 1)
│     ├─ Indicatore stato (OFFLINE / ATTIVO / RICONNESSIONE…)
│     └─ Indicatore righe attive (N/M)
│
├── Banner rosso "MODALITÀ REALE ATTIVA"   (visibile solo in modalità reale)
│
├── Tabview CONFIGURAZIONE (4 tab)
│     ├─ ⚙️ Generale            (Token, Chat ID, CSV Path, Timeout, Provider)
│     ├─ 🎯 Riconoscimento      (modalità riconoscimento)
│     ├─ 🛡️ Sicurezza           (DRY_RUN, auto-start, privacy log, limiti, coda)
│     └─ ✅ Conferme XTrader     (chat notifiche, timeout, keyword conferma/rifiuto)
│
├── Barra pulsanti principali
│     ├─ ▶ AVVIA   ■ STOP   🗑️ Svuota CSV ora   💾 Salva Config
│     └─ 🧰 Strumenti
│
└── Tabview MONITORAGGIO (4 tab)
      ├─ 📡 Chat ascoltate   (elenco chat + Esporta audit / Apri log / Copia diagnostica)
      ├─ 📡 Stato            (ultimo segnale / messaggio / CSV / errore)
      ├─ 📊 Dashboard        (contatori di sessione)
      └─ 📋 Log              (viewer log + filtro + retention + Debug + Svuota log)

HUB "🧰 STRUMENTI"  (tab PIATTE ma RAGGRUPPATE per flusso ①..④, #293 slice 4; su richiesta)
   ① Sorgenti
      ├─ ① 📡 Chat sorgenti      → gestione multi-chat
      └─ ① 📇 Provider           → anagrafica nomi Provider
   ② Lettura messaggi
      ├─ ② 🧩 Parser             → Parser Personalizzato (regole + 🔗 Traduzioni attive + multi-riga)
      └─ ② 🗺️ Mapping            → dizionari mappatura (sotto-tab: ⚽ Calcio nomi · 🎯 Mercati · 🌳 Mapping guidato)
   ③ Dizionario
      ├─ ③ 📖 Dizionario         → browser sola-lettura del dizionario locale
      ├─ ③ 📒 Diario             → vista sola-lettura del diario eventi (event journal)
      └─ ③ 🧹 Nomi squadra       → ripulitura dei nomi squadra del dizionario (sfoglia + elimina)
   ④ Impostazioni
      ├─ ④ 📁 Profili            → profili impostazioni salvabili
      └─ ④ 📋 Riepilogo          → colpo d'occhio sola-lettura: modalità + dizionario locale + canali «Pronto?»
```

> **#293 slice 4 (raggruppamento per flusso).** Le schede dell'hub restano un unico `CTkTabview`
> **piatto**, ma sono **riordinate per gruppo** e il titolo di ognuna è **prefissato** col numero
> del gruppo (①..④): primo passo incrementale verso la IA a 4 gruppi dell'issue #293, senza tab
> annidate. La IA (gruppi → strumenti, ordine, prefissi) è la fonte unica `tools_gui.TOOL_GROUPS`/
> `TOOL_TITLES`/`build_tool_panels`. Le funzioni e le callback dei pannelli sono **invariate**.

**Frequenza d'uso (per prioritizzare la gerarchia visiva):**
- **Quotidiano / sempre a vista:** stato ATTIVO/OFFLINE, banner reale, righe attive,
  AVVIA/STOP, ultimo errore, log.
- **Setup iniziale (poi raro):** tab Generale (token/chat/csv), Parser Personalizzato,
  Chat sorgenti, Dizionario, Mapping.
- **Occasionale:** Sicurezza (cambio modalità), Profili, Conferme XTrader, Dashboard.

---

## 6. Finestra principale — dettaglio completo

**Titolo:** `XTrader Signal Bridge v0.1.0` · **Geometria:** 720×760, **larghezza fissa**,
altezza ridimensionabile, min 720×600.

### 6.1 Header
- Titolo grande: **"🤖  XTrader Signal Bridge"** (font ~20, bold), su frame scuro
  (`#1a1a2e`, angoli arrotondati). Testo titolo in ciano (`#4fc3f7`).
- **Indicatore di stato** (a destra): pallino + testo, vedi §8.
- **Indicatore righe attive** (arancione): "N/M", vedi §8.

### 6.2-quinquies Selettore «🌐 Scegli la lingua del bridge» al primo avvio (#343)

Toplevel MODALE (grab) che compare **solo al primo avvio** (config con `app_language`
mai scelta), ~300ms dopo la finestra principale. Contenuto verticale: titolo verbatim
**«🌐 Scegli la lingua del bridge»** (bold 14), tre bottoni larghezza 240 — **«🇮🇹
Italiano» / «🇬🇧 English» / «🇪🇸 Español»** — e hint grigio (11px, wraplength 320):
*«Ricorda: in XTrader/Betting Toolkit imposta la LINGUA DELLA FONTE uguale a quella
scelta qui — col riconoscimento a nomi i nomi dipendono dalla lingua del palinsesto.»*
Comportamento: il click su una lingua **persiste** `app_language` e **allinea**
`csv_language` (separatore decimale CSV #342) — ma una csv_language **personalizzata**
(≠ default IT e ≠ lingua scelta) viene **preservata**, e il log lo dice («…lingua CSV
personalizzata preservata: EN»); su salvataggio FALLITO il log è onesto («⚠️ …
salvataggio config FALLITO: nulla è cambiato (la sessione resta nella lingua
precedente) e il selettore riapparirà…») — mai un falso successo, e la config viva
NON viene adottata (memoria, runtime CSV e disco restano coerenti sulla lingua
precedente).
Chiudere SENZA scegliere è sicuro (comportamento storico IT, il selettore ricompare al
prossimo avvio — la non-scelta non viene mai persistita). Con **auto-start attivo** il
selettore NON compare (mai un grab modale sopra un avvio non presidiato: STOP deve
restare raggiungibile) — log «🌐 Selettore lingua rimandato: auto-start attivo…».
Invarianti: la scelta lingua NON tocca modalità/gate di sicurezza. Dalla **slice 4a**
la lingua governa anche le etichette STATICHE della finestra principale (tab, bottoni,
nomi campo INCLUSE le impostazioni avanzate dei tab Riconoscimento/Sicurezza/Conferme e
le etichette dei contatori Dashboard — catalogo `i18n.py`, italiano = riferimento,
fallback fail-safe: una
traduzione mancante mostra l'italiano, mai stringhe vuote), applicate al **riavvio**
(log di conferma: «…riavvia il bridge per applicare la lingua all'interfaccia…»).
Dalla **slice 4b** anche gli stati dinamici «⬤ ATTIVO/RICONNESSIONE…» sono
localizzati (EN: ACTIVE/RECONNECTING… · ES: ACTIVO/RECONEXIÓN… · «⬤  OFFLINE» è
universale): il semaforo 🚦 Salute non fa più il parsing del testo della label ma usa
lo **stato canonico** `_listener_state` (`health_check.LISTENER_*`), impostato dal
punto unico `_set_listener_state` — la label è SOLO display. Dalla **slice 4c** la
localizzazione si estende alle **finestre secondarie**, a una per volta: la prima è
**📇 Anagrafica Provider** (titolo, testi, bottoni, placeholder e i messaggi di stato
dinamici — questi ultimi via template tradotto + `.format(...)`, così restano
coerenti e non producono UI mista). Le stringhe con variabili usano il template come
chiave di catalogo (es. «➕ Provider «{name}» salvato.»); l'anti-drift (AST) e un test
di parità dei segnaposto garantiscono che le traduzioni restino allineate al codice.
Dalla **slice 4d** è localizzata anche **📁 Profili impostazioni** (stesso schema:
titolo/testi/bottoni + messaggi di stato dinamici via template+`.format`; i messaggi
che mostrano SOLO l'eccezione bubblata dal layer puro `profile_store` restano IT, slice
a parte). Restano IN ITALIANO per ora: la maggior parte dei testi dei **log** dell'app
(diagnostici — localizzati a gruppi, vedi «slice 4j») e le finestre secondarie non ancora
localizzate (**🧰 Strumenti** hub e il pannello **🌳 Mapping guidato**).
*(Ora localizzati, prima esclusi: i banner REALE/COLLAUDO — «slice 4 — banner di modalità» in
fondo a questa sezione — la finestra **🧙 Wizard** — «slice 4h», §6.2-quater — la finestra
**🗺️ Mapping** (Dizionario nomi + mercati) — «slice 4i», vedi §7.5 — e il primo gruppo di **log
di ciclo-vita del bridge** — «slice 4j», in fondo a questa sezione.)*

Dalla **slice 4e** è localizzata la **chrome** di **📡 Chat sorgenti** (finestra del
FILTRO CHAT, safety-critical): titolo, hint, intestazioni colonne (Attiva/Nome/
Modalità/Traduzioni; Chat ID/Provider/Parser già ~universali), bottoni e messaggi di
stato GUI-composti. Restano IN ITALIANO per non toccare logica/contratti: la sentinella
«(predefinito)» (usata in confronti di uguaglianza), il chip «Traduzioni» («Nomi ✓ ·
Mercati —», helper puro asserito verbatim in CI) e gli errori/warning bubblati dal layer
di dominio `editor.apply()`.

Dalla **slice 4f** è localizzata **📒 Diario** (sola lettura): titolo, filtri (Tipo/
Ultimi), bottoni (🔄 Aggiorna/📂 Apri cartella), intestazioni colonne (Quando/Tipo/Dati
redatti) e i conteggi/errori. I due valori-filtro «(tutti i tipi)» e «Tutti» sono display
MA anche chiavi (il primo confrontato in `_selected_types`): tradotti alla COSTRUZIONE e
confrontati con lo stesso valore tradotto (test di coerenza lingua↔confronto). I nomi-tipo
evento (START/STOP/…) restano identificatori di dominio, non tradotti. La finestra
**Strumenti (hub)** è invece rimandata: i suoi titoli-scheda sono chiavi di matching +
contratti IA (localizzazione cross-cutting a parte).

Dalla **slice 4g** è localizzata la **chrome** di **🧩 Parser Personalizzato** (§7.1) —
il pannello più complesso: titolo finestra, etichette campo (Nome parser/Modalità/Sport/
Parser salvati/Catalogo XTrader/Nomi squadra · separatore/Mercati/Messaggio di prova),
header di sezione (🔗 Traduzioni attive · ⚙️ Avanzate · Output multi-riga · Anteprima ·
Diagnostica), bottoni (➕ Provider/🆕 Nuovo/📂 Carica/📑 Duplica/🗑 Elimina/➕ Inserisci
regole fisse/🗺️ Dizionario nomi/🎯 Dizionario mercati/💾 Salva/🧪 Prova messaggio/🧪🧪
Prova più messaggi/📋 Copia diagnostica/➕ Aggiungi mercato/➕ Aggiungi selezione/🗑 Rimuovi/
checkbox Attiva), l'indicatore Traduzioni «— nessuna»/«✓ N attive» (helper puro, ora via
template+`.format`) e — completata la localizzazione della chrome — anche i **messaggi di
stato/conferma GUI-composti** dei metodi d'azione (successo, parziale ed error-prefix: es.
«💾 Salvato in …», «📂 Caricato …», «📑 Duplicato in …», «🗑 Eliminato …», «➕ Regole fisse
inserite: …», «➕ Provider «…» salvato.» / «⚠️ Provider «…» aggiunto solo in memoria …», gli
«⛔ Non salvato: profili di mappatura … mancanti (…)» e i prefissi «❌ Errore salvataggio/
caricamento/duplica/eliminazione: …»), oltre al prompt «Nuovo nome per la copia di …», tutti
via template tradotto + `.format(...)` con il DATO interpolato lasciato invariato. Restano
**IN ITALIANO come esclusioni di sicurezza**: gli interruttori **«MultiMarket (più mercati)»**
e **«MultiSelection (più selezioni)»** (le loro label raddoppiano da semantica di
configurazione), i **VALORI** delle tendine Modalità/Sport/Mercato/Trasformazione/Value-map
(chiavi di config) e il `title="Provider"` del dialog (confrontato come
`rule.target == "Provider"`). Restano IT anche il **testo di dominio bollato in `{exc}`**
(messaggi/errori del `ParserBuilder`/config interpolati nei prefissi qui sopra), i nomi-colonna
della tabella regole/diagnostica e l'hint 💡 estrazione dinamica (slice a parte).

Dalla **slice 4 — banner di modalità** sono localizzati i due **banner persistenti di
sicurezza**: il **banner ROSSO «⚠️ MODALITÀ REALE ATTIVA…»** (`real_mode.BANNER_TEXT`) e il
**banner AMBRA «🔬 MODALITÀ COLLAUDO XTRADER…»** (`bridge_mode.COLLAUDO_BANNER_TEXT`), resi in
`app.py` via `i18n.tr(...)` sulla costante. Traduzioni (catalogo `i18n.py`): EN «⚠️ REAL MODE
ACTIVE …» / «🔬 XTRADER TEST MODE …», ES «⚠️ MODO REAL ACTIVO …» / «🔬 MODO DE PRUEBA XTRADER
…». La **semantica di rischio è preservata** in tutte le lingue: emoji ⚠️/🔬 invariate, colori
banner invariati (rosso REALE ha priorità sull'ambra COLLAUDO), parole-rischio conservate
(REAL/REALES, TEST/PRUEBA). La **decisione** di mostrare il banner (`real_mode.banner_active`
/ `bridge_mode.banners_for`) è invariata: cambia solo il testo mostrato. IT resta il
riferimento (fail-safe: lingua mai scelta → banner in italiano storico). I **messaggi di log**
dell'app (diagnostici) sono localizzati a gruppi coerenti, a partire dalla «slice 4j» qui sotto.

Dalla **slice 4j — log di ciclo-vita del bridge** è localizzato il primo gruppo dei ~105 log
`self._log(...)` di `app.py`, cioè i più visibili all'utente nel pannello **📋 Log**: avvio
(«🚀 Bridge avviato!»), CSV attivo («📄 CSV: …») e auto-clear («⏱️  Auto-clear dopo: …s»),
ascolto («👂 In ascolto su Telegram…»), STOP («🛑 Bridge fermato.»), connessione
(«✅ Connesso a Telegram.»), scadenza segnale («⏱️  Scadenza segnale tra ~…s») e svuotamento
manuale del CSV («🗑️  CSV svuotato manualmente»). Traduzioni EN/ES nel catalogo `i18n.py`
(«bridge»/«Telegram» invariati, come nel resto del catalogo). Il **marker emoji iniziale**
(❌/⚠️/✅/… — usato dal sink `_log` per classificare il livello) è **conservato in ogni lingua**,
quindi il colore/livello della riga di log non cambia. Restano IN ITALIANO, per contratto, i log
che riportano **contenuto di dominio** risalito dai layer puri (`bridge_mode.start_log_text`,
`real_mode.*`, `config_store.save_status_message`, esiti `outcome.*_log`, `warning`) e i restanti
gruppi di log, previsti nelle prossime slice della #343.

Dalla **slice 4k — log CONFIG/CSV user-action** è localizzato il secondo gruppo: i log delle
**azioni utente su configurazione e CSV** nel pannello **📋 Log** — «💾 Configurazione salvata»,
«🎨 Tema: chiaro/scuro», «📄 CSV Path aggiornato e salvato: …», i prefissi d'errore «❌ CSV Path
selezionato ma NON salvato: …»/«❌ Preferenza tema NON salvata: …» e l'intero set di feedback del
pulsante **«📄 Crea CSV»** (bloccato in RUN, creato, file estraneo/segnale attivo non sovrascritti,
annullato dall'utente). «Crea CSV» è tradotto come il **bottone** omonimo (EN «Create CSV», ES
«Crear CSV»); marker emoji e livello conservati. **Restano IT** (documentato): i **messaggi di
stato** del layer puro `config_store.save_status_message` (si traduce solo il prefisso), il dato
`{exc}`, i log di **recovery/clear** con la parola-quando («all'avvio»/«allo stop»/…) — slice a
parte — e, importante per il design, i **dialoghi modali** di «Crea CSV» (`messagebox`/`filedialog`:
titoli, conferme di sovrascrittura): sono una superficie diversa dai log e restano in italiano
finché non arriva la slice dedicata ai **dialoghi GUI** (quindi, temporaneamente, cliccando «Crea
CSV» il **dialogo** è IT ma la **riga di log** risultante è localizzata).

Dalla **slice 4l — log AVVIO/VALIDAZIONE START** è localizzato il terzo gruppo: i messaggi
**safety-critical** che compaiono nel pannello **📋 Log** quando lo **START è bloccato/annullato** —
cioè quelli che spiegano perché il bridge non è partito: «❌ Inserisci il Bot Token prima di
avviare!», «❌ Nessuna chat configurata …», «❌ Nessun Parser Personalizzato configurato …»,
«❌ La Chat notifiche XTrader coincide con una chat sorgente …», «⚠️ Nessuna chat sorgente ATTIVA
…», gli annullamenti di modalità reale/auto-start («⏸️ …»), «▶️ Avvio automatico del listener …»,
«❌ {problem} Avvio annullato.» e «❌ Impossibile inizializzare il CSV ({path}): {exc} …». Marker di
severità (❌/⚠️/⏸️/▶️) conservato in EN/ES → colore/livello della riga invariato. **Restano IT** per
contratto: i log di **puro dominio** `f"❌ {err}"` (errore di validazione) e `f"⚠️ {warn}"` (avvisi
degli store), coi valori interpolati `{err}`/`{problem}`/`{exc}` di dominio; e i **dialoghi modali**
`messagebox` di conferma START in modalità reale (superficie «dialoghi GUI», ancora IT).

Dalla **slice 4m — log ESITO elaborazione messaggio/segnale** è localizzato il quarto gruppo: i log
runtime del pannello **📋 Log** che spiegano **cosa è successo a un messaggio/segnale** durante
l'ascolto (il flusso attorno alle conferme XTrader) — messaggio ignorato perché troppo vecchio, config
live senza filtro chat, conflitto Chat-notifiche/sorgente, «⚠️ Segnale scartato (…)», «❌ Scrittura CSV
fallita: …», la riga di tracciabilità «🧾 Messaggio→CSV | msg: … | riga: …», gli aggiornamenti CSV
falliti dopo conferma/scadenza e «🗑️ N segnale/i scaduto/i rimosso/i dal CSV». Marker (⏳/⚠️/❌/🧾/🗑️)
conservato → colore/livello invariato. **Restano IT** per contratto: i **veri messaggi di ESITO
conferma** (confermato/rifiutato/unmatched/unknown) e le presentazioni di scrittura/scarto costruite
nei layer puri (`outcome.*_log`, `signal_outcome.confirmation_removed_log`/`_ignored_log`,
`multi_signal.blocked_message`) coi dati di dominio interpolati.

Dalla **slice 4n — log RESILIENZA runtime** è localizzato il quinto gruppo: i log del pannello
**📋 Log** legati a **caduta e ripristino della connessione** e al recovery del CSV — «🔄 Riconnesso:
… recuperati …», «🔌 Connessione persa (…): riconnessione tra Ns (tentativo N)…», «❌ Errore non
recuperabile del listener: … Bridge fermato.», «🧹 CSV ripulito al retry dopo lo STOP: …» e «🧹 Rimossi
N file temporanei CSV orfani all'avvio.». Marker (🔄/❌/🔌/🧹) conservato → colore/livello invariato.
**Restano IT** per contratto: i log di recovery con la **parola-quando** («🧹 CSV riportato a solo
header {quando}: …», «⚠️ Impossibile ripulire il CSV {quando} …»), perché `{quando}` è una
**chiave-valore** confrontata nel codice (`== "all'avvio"`) per distinguere un crash-recovery da un
clear normale — la sua localizzazione richiede uno split display↔chiave, rimandato a una slice
dedicata; i valori interpolati `{exc}`/`{error}`/`{path}` restano dominio.

Dalla **slice 4o — log LOG & DIAGNOSTICA** è localizzato il sesto gruppo: i log del pannello **📋 Log**
legati agli **strumenti di logging/diagnostica** — «📂 Cartella log: …» (apertura cartella), «🧾 Audit
modalità reale esportato (N eventi): …», «📋 Diagnostica copiata negli appunti.», i messaggi di
**retention log** («🧹 Retention log: N giorni · N rimossi», «conservo tutto», variante all'avvio),
«🧹 Log svuotati: …» e «🐞 Modalità Debug log: ON/OFF.». Marker (📂/🧾/📋/🧹/🐞/❌/⚠️) conservato →
colore/livello invariato; «Debug»/«ON»/«OFF» restano invariati (stati tecnici). **Restano IT** per
contratto: i **suffissi di stato** del layer puro `config_store.save_status_message` nei due messaggi
«Retention/Debug NON salvata» (si traduce solo il prefisso, come per gli altri error-prefix), i valori
di dominio interpolati e i log `_dbg(…)` di debug verboso (fuori pannello, diagnostica interna).

Dalla **slice 4p — log WIZARD + LINGUA-SELECTOR + PROFILO/SORGENTI** è localizzato il settimo gruppo:
i log del pannello **📋 Log** legati a **wizard**, **selettore lingua** e **profilo/sorgenti** —
apertura wizard fallita, «🧙 Wizard completato: …», «🌐 Selettore lingua rimandato: auto-start
attivo …», «⚠️ Lingua scelta (…) ma salvataggio config FALLITO …», «⚠️ Scheda … non aggiornata dal
profilo …», «📁 Profilo caricato e applicato …» e «📡 Sorgenti multi-chat aggiornate (N).». Marker
conservato → colore/livello invariato. **Restano IT** per contratto: il log di **successo del
cambio-lingua** («🌐 Lingua del bridge impostata: …») — ha una sotto-stringa computata e una nota che
va aggiornata, rimandato a una slice dedicata; il **suffisso di stato** `save_status_message` del
profilo «NON persistito» (solo prefisso tradotto); e — invariante di sicurezza — il log di
apertura-wizard-fallita registra **solo la classe dell'eccezione** (`type(ex).__name__`), mai il
token (che potrebbe comparire nel testo di un'eccezione, review #354).

### 6.2-quater Finestra «🧙 Wizard di prima configurazione» (#311 §3.4)

Toplevel MODALE (grab) lanciato dal bottone **«🧙 Wizard prima configurazione»**
(`#00695c`/hover `#004d40`, accanto a «🧰 Strumenti»). Cinque step con titolo
`N/5 · <nome>`, navigazione **«◀ Indietro» / «Avanti ▶»** (ultimo step: **«Fine ✔»**);
**gate di avanzamento**: «Avanti» è bloccato (messaggio *«⛔ Completa prima la verifica
di questo step.»*) finché la verifica dello step non è ✅. Esiti sotto il corpo:
`✅/⛔ <messaggio>` (verde `#66bb6a` / rosso `#ef5350`), «⏳ Verifica in corso…» durante
le sonde (eseguite in thread: la finestra non si congela). Step: (1) token (campo
mascherato `•`) + «🔌 Prova connessione (getMe)»; (2) Chat ID + «📡 Controlla ora»
(hint: bot admin, messaggio di prova, listener fermo); (3) textbox messaggio reale +
«🧪 Valuta messaggio» (verdetto del tester #350); (4) csv_path + «🔎 Verifica percorso»
e «📄 Scrivi CSV di prova» (mai sovrascrive: riga attiva protetta, file estraneo
rifiutato); (5) checklist ✅/⛔ a 5 voci. Invarianti: il wizard NON attiva mai la
modalità Reale (checklist informativa; i gate restano nella tab 🛡️ Sicurezza); il
token non compare MAI negli esiti/log; «Fine ✔» applica token/chat/csv al form e salva
col percorso esistente (gate inclusi); **singleton** (Fable #354): un secondo click sul
bottone riporta davanti il wizard già aperto, mai due finestre modali; una sonda che
fallisce mostra un esito ⛔ onesto (solo la classe dell'errore) e sblocca subito la
verifica successiva; chiudere la finestra con una sonda in corso è sicuro (l'esito
tardivo viene scartato); **anti esito stantio** (CodeRabbit #354): modificare un campo
DOPO il ✅ invalida la verifica — «Avanti» torna bloccato con *«✏️ Valore modificato
dopo la verifica: ripeti la verifica.»* finché la sonda non viene rieseguita sul valore
nuovo (lo step chat dipende anche dal token, lo step parser anche dalla chat).

**Localizzazione (#343 slice 4h).** La **chrome** del Wizard è ora tradotta EN/ES via
`i18n.tr`: titolo finestra, i **5 titoli step** (`N/5 · <nome>`), i pulsanti nav (◀ Indietro /
Avanti ▶ / Fine ✔) e azione (🔌 getMe / 📡 Controlla ora / 🧪 Valuta messaggio / 🔎 Verifica
percorso / 📄 Scrivi CSV di prova), gli hint dei 5 step e i messaggi GUI-composti (⛔/✏️ di
navigazione, ⏳ verifica, «Nessun Parser attivo», template errore imprevisto `{kind}`). Le label
citate sopra sono **chiavi del catalogo** (verbatim). Restano IT — **esclusione di dominio**,
come le 4e/4g — i `res.message` degli esiti sonda bubblati dal layer puro `wizard.py`
(`check_token`/`check_chat`/`check_parser`/`check_csv`); il wizard prepende solo l'emoji
universale ✅/⛔. Le **invarianti di sicurezza** (mai attivazione REALE, token mai nei log, gate
«Avanti», singleton) sono **invariate**: la localizzazione tocca solo il testo mostrato.

### 6.2-ter Scheda «🚦 Salute» — health check a semafori (#311 §3.3)

Nuova scheda nel Tabview di monitoraggio (fra «📡 Chat ascoltate» e «📡 Stato»): sette
righe-semaforo `🟢/🟡/🔴 <Etichetta>: <dettaglio>` + pulsante **«🔄 Aggiorna»**. Ordine e
etichette verbatim: *Telegram* · *Ultimo messaggio* · *Parser Personalizzato* · *Ultimo
segnale* · *CSV scrivibile* · *Conferme XTrader* · *Modalità*. Colori: verde
`#2e7d32/#66bb6a`, giallo `#e65100/#ffa726`, rosso `#c62828/#ef5350` (le stesse tuple
theme-aware dello stato listener). Semantica: dato assente = MAI verde (giallo onesto);
*Modalità* usa la semantica di rischio dei banner (verde Simulazione, giallo Collaudo,
rosso Reale). Aggiornamento automatico sugli stessi hook della dashboard (START/STOP,
campi «Ultimo …», salvataggio config) + manuale col pulsante. La sonda «CSV scrivibile»
NON apre mai il file (nessun lock che disturbi XTrader); su **Windows**
si ferma a **giallo onesto** su ENTRAMBI i rami — file esistente E file da creare
(«probabilmente scrivibile»: ACL/lock NTFS non rilevabili senza aprire/scrivere —
Fable/Fugu #351), mai un verde non verificabile. Nella scheda «📡 Stato» compare
anche il nuovo campo **«Ultima conferma XTrader»** (fonte unica `_LAST_FIELDS`).

### 6.2-bis Banner modalità COLLAUDO (#311 §3.1)

Banner **AMBRA** persistente (`#e65100` light / `#8a4b00` dark, testo bianco, stessa
posizione del rosso) quando la modalità è **Collaudo XTrader** — testo verbatim:
*«🔬 MODALITÀ COLLAUDO XTRADER — il CSV operativo VIENE scritto: XTrader deve essere in
Modalità Simulazione (nessuna scommessa reale).»* Sticky di sessione come il rosso (resta
finché una sessione partita in collaudo non fa STOP). **Invarianti: il banner ROSSO ha
priorità** (mai due banner insieme, il rischio maggiore vince) **e il ROSSO è mode-aware**
(Fugu #349): si accende SOLO in modalità Reale — in Collaudo, pur con `dry_run=false`,
resta l'AMBRA (mostrare «REALE ATTIVA» durante il collaudo sarebbe fuorviante).

### 6.2 Banner modalità reale
- Visibile **solo** in modalità reale. Barra **rosso scuro** (`#7f1d1d`, testo bianco):
  > ⚠️ MODALITÀ REALE ATTIVA — i segnali validi vengono scritti nel CSV operativo e
  > XTrader può piazzare scommesse REALI.

### 6.3 Tabview Configurazione (altezza ~210)

**Tab ⚙️ Generale** — 5 campi testo:

| Campo (label) | Chiave | Note UI |
|---|---|---|
| 🔑 Bot Token | `bot_token` | campo password (mascherato) |
| 💬 Chat ID | `chat_id` | testo |
| 📄 CSV Path | `csv_path` | testo (percorso file, casella **più corta** delle altre) **+ pulsante «📁 Sfoglia…»** (#284) **+ pulsante «📄 Crea CSV»** (#286) — la riga è compatta perché porta due pulsanti e la finestra ha **larghezza fissa** (720px) |
| ⏱️ Timeout (sec) | `clear_delay` | intero > 0 |
| 🏷️ Provider | `provider` | testo |

- **Segnaposto d'aiuto nei campi (#288 Delta 2):** ogni casella mostra un **placeholder** grigio a
  campo vuoto (es. Chat ID → `es. -1001234567890`, Bot Token → `incolla qui il token del bot`, CSV
  Path → `es. C:\XTrader\segnali.csv`, Timeout → `es. 90`, Provider → `es. TelegramBot`). Il
  placeholder è **solo un aiuto visivo**, NON un valore: un campo lasciato vuoto resta `""` (nessun
  impatto su parsing/salvataggio). Sui campi **sensibili** (token) il placeholder è **generico e
  istruttivo**, mai un segreto plausibile (è mostrato in chiaro anche sui campi mascherati).
- **«📁 Sfoglia…» accanto a CSV Path (#284):** apre il selettore file di sistema (dialog Tk
  `asksaveasfilename`, `.csv`). Alla scelta, il percorso è **scritto nella casella E salvato
  subito in `config.json`** (opzione b: nessun click extra su «Salva Config»). Il salvataggio
  è un **merge sul config vivo** — cambia solo `csv_path`, non tocca gli altri campi
  safety-critical (dry_run/chat/sorgenti) né esegue i gate di modalità REALE. Se l'utente
  annulla il dialog → nessuna modifica. Nota invariante: cambiare il percorso a bridge
  **avviato** non tocca il CSV della sessione attiva (resta quello di START finché STOP/START).
- **«📄 Crea CSV» accanto a CSV Path (#286):** azione complementare a «📁 Sfoglia…» — invece di
  **selezionare** un CSV esistente, **genera** un CSV nuovo **a solo header** nel formato XTrader
  (dialog Tk `asksaveasfilename`, `.csv`) e lo imposta come `csv_path` (stesso salvataggio
  immediato + merge sul config vivo). Il file è **generato dall'app** (dal contratto
  `CSV_HEADER`), mai scaricato o incluso nel repo/EXE. La creazione è **atomica e senza finestra
  TOCTOU** (il check di cosa c'è già e la scrittura avvengono sotto lo stesso lock). Anti data-loss,
  a tre livelli:
  - percorso nuovo, o CSV del bridge **a solo header** → generato/rigenerato senza domande;
  - **file estraneo** (header diverso) o CSV del bridge **con un segnale attivo** → **conferma
    esplicita** (finestra «Sovrascrivere…?») prima di toccarlo, altrimenti nessuna modifica;
  - **bridge AVVIATO su quello stesso CSV** → **bloccato** con avviso «Fai STOP prima di ricrearlo»
    (non si cancella un segnale in volo né si desincronizza la sessione), senza scorciatoie.
  Annullo → nessun file creato.

**Tab 🎯 Riconoscimento** — 1 dropdown:
- **"🎯 Modalità riconoscimento"** → opzioni `ID_ONLY` / `NAME_ONLY` / `BOTH`.

**Tab 🛡️ Sicurezza** — checkbox + campi + dropdown:
- **«🚦 Modalità bridge»** (tendina a 3 stati, #311 §3.1 — sostituisce il checkbox DRY_RUN):
  etichette verbatim *«🧪 Simulazione Bridge — NON scrive il CSV operativo»*, *«🔬 Collaudo
  XTrader — scrive il CSV (XTrader in simulazione)»*, *«⚠️ Reale — scommesse vere (richiede
  conferma)»*. Gate: Sim→Collaudo = conferma **sì/no** (testo `COLLAUDO_CONFIRM_TEXT`);
  QUALSIASI ingresso in Reale (anche Collaudo→Reale) = **frase digitata** (§10); annullo →
  la tendina e la config tornano al modo PRECEDENTE (non sempre Simulazione).
- ☐ **"▶️ Avvio automatico all'apertura (in modalità REALE chiede conferma)"** (`auto_start_listener`)
- ☐ **"🕵️ Logga il testo completo dei messaggi (debug; OFF = solo hash + 1ª riga)"** (`debug_message_payload`)
- Campo **"📅 Limite segnali al giorno"** (`max_per_day`)
- Campo **"🔢 Max segnali attivi (modalità coda multi-riga)"** (`max_active_signals`) — tetto
  sull'accumulo **tra messaggi**; il blocco di un **singolo** messaggio multi-riga non viene mai
  spezzato da questo tetto (auto-raise, #192), quindi le righe attive possono superarlo per un
  blocco intero.
- Dropdown **"🧮 Modalità coda segnali"** (`queue_mode`): `OVERWRITE_LAST` / `APPEND_ACTIVE` / `QUEUE_UNTIL_CONFIRMED`

**Tab ✅ Conferme XTrader** — 4 campi:
- **"💬 Chat notifiche XTrader"** (`xtrader_notification_chat_id`)
- **"⏳ Timeout conferma (sec)"** (`confirmation_timeout`)
- **"✅ Parole conferma (separate da virgola)"** (`confirmation_keywords`)
- **"❌ Parole rifiuto (separate da virgola)"** (`rejection_keywords`)

### 6.4 Barra pulsanti principali
- **"▶  AVVIA"** (verde `#2e7d32`, bold)
- **"■  STOP"** (rosso `#c62828`, bold; disabilitato all'avvio)
- **"🗑️  Svuota CSV ora"**
- **"💾  Salva Config"** (grigio `#37474f`)
- **"🧰  Strumenti"** (viola `#4527a0`) — apre l'hub

### 6.5 Tabview Monitoraggio (area espandibile)

**Tab 📡 Chat ascoltate:**
- Etichetta con l'elenco chat che verranno ascoltate, oppure avviso arancione:
  > ⚠️ Nessuna chat configurata — il bridge non si avvierà finché non imposti una Chat ID
  > o una Chat sorgente.
- Pulsanti: **"🧾 Esporta audit reale"**, **"📂 Apri cartella log"**, **"📋 Copia diagnostica"**.

**Tab 📡 Stato** — 4 righe dinamiche (formato `Prefisso: valore o —`):
- **Ultimo segnale**, **Ultimo messaggio**, **Ultimo CSV**, **Ultimo errore**.

**Tab 📊 Dashboard** — titolo "Contatori dall'avvio" + 7 contatori:
- 📥 Ricevuti · ✅ Scritti · ⚠️ Scartati · ♻️ Duplicati · 🚦 Limitati · 🧪 Simulati · ❌ Errori.

**Tab 📋 Log:**
- Dropdown **"Mostra:"** (filtro livello: `Tutti` / `INFO` / `WARNING` / `ERROR` / `SIGNAL`)
- Dropdown **"Conserva:"** (retention: `Mai`=0 / `5 giorni` / `15 giorni` / `30 giorni`)
- Pulsante **"🧹 Svuota log"**, checkbox **"🐞 Debug"**
- Area log (textbox monospace), righe formato `[HH:MM:SS] [LIVELLO] messaggio`.

---

## 7. Hub Strumenti e finestre secondarie

L'hub **"🧰 Strumenti"** è una finestra a tab caricata su richiesta, **raggruppate per flusso
①..④** (vedi §5). I 10 pannelli:

### 7.1 🧩 Parser Personalizzato (`custom_parser_gui.py`) — il pannello più complesso
Costruttore visuale che definisce **come estrarre ogni colonna del CSV** da un messaggio,
senza toccare il codice. È il cuore della configurazione avanzata. Sezioni:

- **Intestazione:** `Nome parser`, `Modalità` (`(eredita globale)` + opzioni), `Sport`
  (`(non specificato)` / Calcio / Tennis / Basket / Rugby Union), pulsante **"➕ Provider"**.
- **Parser salvati:** dropdown `(nessuno)` + **"🆕 Nuovo"**, **"📂 Carica"**, **"📑 Duplica"**,
  **"🗑 Elimina"**.
- **Catalogo XTrader:** dropdown Mercato + dropdown Selezione + **"➕ Inserisci regole fisse"**.
- **🔗 Traduzioni attive per questo parser (#293):** riquadro etichettato che raggruppa le due
  mappature (prima erano righe sciolte), con un **indicatore di stato ✓/—** per tipo:
  - **Nomi squadra:** separatore (placeholder `v`), **"🗺️ Dizionario nomi"**, indicatore
    (`✓ N attive` verde / `— nessuna` grigio), riga di checkbox-profili (i profili "fantasma"
    mancanti sono marcati `⚠`).
  - **Mercati:** **"🎯 Dizionario mercati"** + indicatore (`✓ N attive` / `— nessuna`) +
    checkbox-profili.
  L'indicatore si aggiorna a ogni spunta/despunta e al caricamento di un parser, e conta **solo i
  profili risolti** (un profilo fantasma `⚠` selezionato ma inesistente non è una traduzione attiva
  → non gonfia il conteggio). Funzione invariata: le checkbox e i pulsanti «apri Dizionario» sono gli
  stessi; cambia solo la presentazione (le mappature stanno accanto al parser, dove si accendono).
- **Output multi-riga (un messaggio → più righe CSV):** checkbox **"MultiMarket (più
  mercati)"** + **"➕ Aggiungi mercato"**; checkbox **"MultiSelection (più selezioni)"** +
  **"➕ Aggiungi selezione"**; ogni riga ha campi Tipo mercato/Mercato/Selezione/Quota/
  BetType/Handicap + checkbox **"Attiva"** + **"🗑 Rimuovi"**.
  **Solo le righe MultiSelection** (#325 slice 2) hanno in coda due campi in più:
  **«Inizia dopo»** e **«Finisce prima»** (larghezza 110px, label size 10 come le altre celle) —
  i delimitatori dell'**estrazione dinamica dei risultati esatti**. Sotto la lista selezioni c'è
  un **hint fisso 💡** (label size 10, testo verbatim): *«Selezione VUOTA + «Inizia dopo/Finisce
  prima» = estrazione dinamica dei risultati esatti dal messaggio (una riga per punteggio
  «N - N»; solo mercati CORRECT_SCORE / HALF_TIME_SCORE).»* Le righe **MultiMarket NON hanno**
  questi campi (invariante di sicurezza: sui mercati i delimitatori sarebbero solo una
  misconfigurazione che il runtime ignora). Nessun altro cambiamento di layout/palette.

  Sotto la sezione c'è un **banner avvisi ⚠** (label arancione `#ffa726`, una riga per avviso,
  prefisso `⚠ `). Oltre agli avvisi storici (entrambi gli interruttori attivi → «righe SEPARATE…»;
  interruttore acceso senza righe abilitate), il banner segnala le **configurazioni ambigue
  per-riga** delle selezioni attive coi delimitatori (follow-up #325/#341), testi verbatim:
  - *«Riga selezione N: c'è una Selezione fissa, quindi i delimitatori «Inizia dopo»/«Finisce
    prima» verranno IGNORATI. Per l'estrazione dinamica dei punteggi lascia la Selezione vuota.»*
  - *«Riga selezione N: estrazione dinamica dei punteggi INATTIVA — il mercato effettivo X non è
    un mercato-punteggio (CORRECT_SCORE, HALF_TIME_SCORE): la riga resta FISSA ed eredita la
    Selezione della riga base.»* (emesso **solo** quando il mercato effettivo è determinabile
    senza messaggio; se dipende dal runtime il banner tace — mai falsi allarmi).
  Il banner si aggiorna su: aggiungi/rimuovi riga, toggle degli interruttori, **uscita da un campo
  della riga** (`<FocusOut>`), casella **«Attiva»**, e a ogni **«🧪 Prova messaggio»**.
  Invariante: sono **avvisi non bloccanti** (il salvataggio non è impedito), il design può dar
  loro più visibilità ma non trasformarli in blocchi.
- **Condizioni di gate (PR-1 — «il parser scatta solo se il messaggio le soddisfa»):** riquadro
  etichettato (titolo in grassetto verbatim **"Condizioni di gate (il parser scatta solo se il
  messaggio le soddisfa)"**) sotto la sezione multi-riga. Una **barra** con etichetta **"Soddisfa:"**
  + una **tendina modo** a due voci — **"TUTTE (E)"** (default) / **"una qualsiasi (O)"** — e il
  pulsante **"➕ Aggiungi condizione"**. Sotto, una lista di **righe dinamiche**; ogni riga è:
  **tendina "contiene" / "NON contiene"** + **entry di testo** (placeholder *"testo da cercare nel
  messaggio"*) + **"🗑 Rimuovi"**. In coda un **hint fisso 💡** (label size 10, testo verbatim):
  *«"contiene"/"NON contiene" un testo; confronto senza maiuscole e tollerante agli spazi. Nessuna
  condizione = nessun filtro. Righe a testo vuoto sono ignorate.»* Semantica: se **non** ci sono
  condizioni (o tutte a testo vuoto) il parser si comporta **come prima** (nessun filtro); con
  condizioni, il parser **scatta solo se** il messaggio le soddisfa (modo E = tutte, modo O = almeno
  una), con *"NON contiene"* per singola riga negata. Il confronto è **case-insensitive e tollerante
  agli spazi** (stessa normalizzazione dei nomi). È un **filtro fail-closed**: un messaggio che non
  soddisfa il gate viene **scartato** (`NO_CONTENT_MATCH`, nessuna riga CSV). Le righe a testo vuoto
  sono scartate al salvataggio (non generano errori di validazione). Serve a far agire un parser
  **solo sui messaggi pertinenti** (es. «un mercato diverso per scenario»). Nessun cambiamento di
  palette; riquadro nello stile delle altre sezioni.
- **Densità (#293 «densità parser»):** sopra la griglia c'è un toggle **"⚙️ Avanzate
  (Trasformazione · Value-map)"** (checkbox). **Di default è SPENTO**: la griglia mostra solo le
  colonne **essenziali** (Colonna · Inizia dopo · Finisce prima · Valore fisso · Obblig.), più
  leggibile. Attivandolo compaiono le due colonne **avanzate** (Trasformazione, Value-map),
  sia nell'intestazione sia in ogni riga. Nascondere le colonne **non cancella** i dati: i valori
  `Trasformazione`/`Value-map` di un parser caricato restano salvati e vengono riscritti invariati
  (le colonne si nascondono, non si azzerano). Funzione di parsing invariata.
- **Griglia regole (14 colonne CSV fisse):** intestazioni essenziali **Colonna · Inizia dopo ·
  Finisce prima · Valore fisso · Obblig.** (+ **Trasformazione · Value-map** solo in modalità
  «Avanzate»). Ogni riga: nome colonna (label), 2 entry delimitatori, **campo «Valore fisso»**
  (vedi sotto), [dropdown Trasformazione, dropdown Value-map — solo se «Avanzate»], checkbox
  **Obblig.**
  - Il campo **«Valore fisso»** varia per colonna: **entry di testo** per la maggior parte;
    **dropdown a scelta fissa** per **Provider** (dall'anagrafica); **tendina EDITABILE**
    (`CTkComboBox`) per **MarketType / MarketName / SelectionName** (#283 PR 13), popolata coi
    valori permanenti del **dizionario locale** **filtrati per lo sport del parser**. La tendina
    editabile suggerisce i valori presenti **ma resta digitabile** (un valore valido non ancora
    nel dizionario è comunque inseribile: niente fail-closed). Si aggiorna al cambio Sport e al
    rientro nell'hub Strumenti. Se un altro strumento tiene il lock del DB non si blocca: mostra
    solo nessun suggerimento (testo libero comunque digitabile). Distinzione visiva: Provider =
    tendina chiusa; i tre termini = tendina con campo di testo (freccia + digitabile).
- **Azioni:** **"💾 Salva"**, **"🧪 Prova messaggio"**, **"🧪🧪 Prova più messaggi
  (separati da ---)"** (#311 §3.2), **"📋 Copia diagnostica"**.
  Il tester multiplo valuta ogni messaggio del box (separatore: riga con solo `---`) e
  riusa l'area «Anteprima righe generate»: per ogni messaggio una **riga-intestazione in
  grassetto** `M<n> · Messaggio · ✅/⛔ · <prima riga del messaggio> → <verdetto con
  motivo>` (rossa `#ef5350` se scartato) seguita dalle sue righe CSV (stesso formato del
  singolo). Verdetto sintetico in cima: *«✅/⚠ Messaggi validi: X/N»* (+ avviso se oltre il
  tetto di 50). Invariante: SOLO anteprima/lettura, mai scritture del CSV operativo.
- **Area di test:** textbox "Messaggio di prova" + verdetto (`✅ Pronto` / `⛔ …`). L'anteprima
  usa lo stesso motore del runtime. **Con «Betfair Sync» rimossa l'arricchimento ID è staccato
  sia dal CSV live sia dall'anteprima** (`id_resolver=None`): l'anteprima resta quindi
  **conservativa** e non mostra `✅ Pronto` su una riga che il live scarterebbe (un `ID_ONLY`
  senza ID risolti → `⛔`, fail-closed). Invariante «anteprima = runtime» preservato. Quando il
  dizionario locale sarà popolato a mano e il seam riattivato, anteprima e live torneranno a
  risolvere gli ID insieme.
  Il verdetto onora anche il **gate di contenuto** del runtime: un parser a soli valori fissi (che
  non estrae nulla dal messaggio) mostra `⛔ Non pronto (NO_CONTENT_MATCH) · nessun contenuto
  estratto dal messaggio` invece di `✅ Pronto`, sia in single-row sia in multi-riga — come lo
  scarterebbe il bridge. Per un `ID_ONLY` **a riga singola** con ID obbligatori lasciati vuoti il
  verdetto resta `⛔ Non pronto` (l'arricchimento ID dal dizionario è funzione multi-riga; coerente
  col runtime che non lo piazzerebbe).
- **Anteprima righe generate (#192):** tabella `# · Tipo (Base/Mercato/Selezione) · Esito ·
  Riga CSV`. È la fonte **autorevole** per l'esito delle righe generate (la tabella diagnostica
  per-colonna qui sotto è a livello della sola riga base). Il riepilogo «Colonna=valore» (colonna
  *Riga CSV* e verdetto `✅ Pronto · …`) mostra i **decimali nel formato della lingua CSV**
  configurata (#342: virgola per IT/ES — «Price=1,50» — punto per EN), cioè **come usciranno nel
  file**: l'operatore vede in anteprima esattamente ciò che XTrader leggerà.
- **Diagnostica per colonna:** tabella `Colonna · Stato (OK/MANCANTE) · Motivo · Inizia
  dopo · Finisce prima · Valore estratto`.

> Questa è la schermata che più beneficerebbe di un redesign: è densa, tabellare, con molte
> colonne e concetti (delimitatori, trasformazioni, value-map, mapping, multi-riga). Vedi §14.

### 7.2 📡 Chat sorgenti (`source_chats_gui.py`)
Titolo **"📡  Chat sorgenti (multi-chat)"**. Tabella con colonne: **Attiva · Nome · Chat ID
· Modalità (PRE/LIVE) · Provider · Parser · Traduzioni** · ✕ (elimina). Pulsanti
**"➕ Aggiungi sorgente"**, **"💾 Salva"**. Riga di stato con esito salvataggio.
- **Colonna «Parser» (PR-2, router multi-parser):** non più una singola tendina, ma un
  **pulsante** che mostra il riassunto dei parser della chat — **«(predefinito)»** se nessuno
  (usa il globale), altrimenti la lista **numerata in ordine di priorità** (es. **«1. A · 2. B»**).
  Cliccandolo si apre il **popup «Parser della chat (in ordine di priorità)»**: hint che spiega
  «il messaggio va a ogni parser in ordine; scattano TUTTI quelli le cui condizioni combaciano
  (una riga CSV per parser che scatta)»; la lista corrente con **↑ / ↓** (riordina) e **✕**
  (togli) per riga; una **tendina + «➕ Aggiungi parser»** per aggiungerne; **«💾 Salva»** per
  confermare. Con **un solo** parser il comportamento è quello storico (override singolo). La
  sentinella `(predefinito)` = «nessun parser per-chat → usa il globale». È la UI del routing
  multi-parser: più bet diversi/disambiguati **dallo stesso canale** in base alle condizioni di
  gate del Parser (§7.1).
- **Colonna «Traduzioni» (#293 slice 6, sola lettura):** per ogni canale un chip
  **`Nomi ✓ · Mercati ✓`** con `✓`/`—` per tipo (es. `Nomi ✓ · Mercati —`), **verde** se almeno una
  mappatura è attiva, **grigio** (`Nomi — · Mercati —`) se nessuna, che mostra a colpo d'occhio se il
  parser di quella chat ha mappature **risolte** attive. Il parser considerato è l'override
  della riga, o — se «(predefinito)» — il parser **globale**. Si aggiorna al cambio del menu Parser
  della riga e quando la scheda torna attiva (nuove mappature/parser). Stessa nozione di «traduzione
  attiva» del **Riepilogo** (`config_summary.parser_translation_flags`): un profilo fantasma `⚠`
  (selezionato ma inesistente) **non** conta come ✓ (fail-closed). Non modifica il salvataggio né la
  logica del parser: è solo un indicatore.

### 7.3 📇 Provider (`provider_gui.py`)
Titolo **"📇  Anagrafica Provider"**. Campo nome + **"➕ Aggiungi"**; lista provider salvati
con **"🗑 Rimuovi"** per riga. Anagrafica riusabile nella colonna Provider dei parser.

### 7.4 📁 Profili (`profiles_gui.py`)
Titolo **"📁  Profili impostazioni"**. Salva/ricarica snapshot di configurazione (il **token
NON** viene salvato nei profili). Campo nome + **"💾 Salva profilo"**; lista con **"↺ Carica"**
(blu) e **"🗑 Elimina"**. Avviso: fermare il bridge (STOP) prima di caricare un profilo.
- **Stati della lista profili** (riga di stato in fondo al pannello, `wraplength` 520):
  - *lista vuota:* placeholder grigio **"(nessun profilo salvato)"**;
  - *elenco non leggibile* (errore filesystem/ACL su `%APPDATA%`): placeholder rosso
    **"(impossibile elencare i profili)"** nella lista **+** riga di stato rossa
    **"❌ Elenco profili non leggibile: &lt;dettaglio&gt;"**. È uno stato d'errore *non
    bloccante*: la finestra resta usabile, non crasha, e si aggiorna al successivo save/delete.
- **Errori d'azione** (riga di stato rossa, non crash): salvataggio fallito
  **"❌ Salvataggio profilo fallito: …"**, caricamento/eliminazione falliti con messaggio
  analogo. Esiti positivi in verde (**"✅ Profilo … salvato/caricato"**).
- **Refresh cross-scheda al caricamento profilo:** applicare un profilo cambia `config.json`,
  quindi le altre schede Strumenti già aperte (Provider, Chat sorgenti, Mapping) vengono
  **ricaricate dal disco** in automatico (`ProviderPanel.refresh()` e simili), così un
  loro Salva successivo non riscrive lo stato vecchio sopra il profilo (per Chat sorgenti
  eviterebbe di reindebolire il filtro chat). Se una scheda **non riesce** a ricaricarsi il
  caricamento del profilo **non** viene bloccato, ma nel log dell'app compare l'avviso
  **"⚠️ Scheda &lt;nome&gt; non aggiornata dal profilo (mostra ancora i valori precedenti): …"**
  — l'utente sa che quella tab è stantia invece di crederla aggiornata.

### 7.5 🗺️ Mapping (`name_mapping_gui.py`) — 3 sotto-tab

**Localizzazione (#343 slice 4i).** La **chrome** dei due pannelli **⚽ Calcio (Dizionario nomi)**
e **🎯 Mercati** è ora tradotta EN/ES via `i18n.tr`: titoli, sottotitoli, **etichette colonna**,
pulsanti (Profilo/Nuovo/Rinomina/Elimina/Aggiungi riga/Precompila da Betfair/Salva profilo),
placeholder e **tutti i messaggi di stato/dialogo** (creato/rinominato/eliminato, save FALLITO,
avvisi `MAPPING_MISSING`/`MARKET_MAPPING_MISSING`, righe incomplete/senza delimitatori). Restano
**IT** — esclusione di **dominio/value-as-key**: le **sentinelle** delle tendine («(tutti gli
sport)»/«(qualsiasi tipo)»/«(tutte le lingue)»/«(nessun profilo)», usate in confronti), i **valori**
Sport/Tipo/Lingua e i nomi **Mercato/Selezione del Catalogo** (canonici), i **tab del container**
(«⚽ Calcio»/«🎯 Mercati»/«🌳 Mapping guidato» = chiavi di matching) e il pannello **🌳 Mapping
guidato** (`guided_mapping_gui.py`, modulo separato — slice futura). La **logica** (persistenza,
gate, dedup, invarianti anti-scommessa-involontaria) è **invariata**: cambia solo il testo mostrato.

- **⚽ Calcio (Dizionario nomi squadra):** profilo (Nuovo/Rinomina/Elimina) + tabella
  **Country · Betfair/XTrader · Come lo scrive il canale · Sport · Tipo · Lingua**. Traduce i nomi del
  canale nei nomi attesi da Betfair/XTrader. La colonna **«Come lo scrive il canale»** (già «Provider»,
  rinominata in **#293** per non collidere con l'anagrafica «Provider» = etichetta CSV; la chiave
  dati resta `provider`) contiene l'alias con cui il canale scrive il nome squadra. La tendina
  **«Lingua»** (epica multilingua **#3 slice 5b**) tagga la riga con la **lingua della fonte**
  (`IT`/`EN`/`ES`) oppure **«(tutte le lingue)»** = agnostica (default): quando la lingua-fonte è
  impostata, le righe della lingua ESATTA hanno priorità sulle agnostiche e quelle di un'altra lingua
  sono saltate (le agnostiche restano sempre valide → i dizionari esistenti continuano a funzionare).
  Come per **Sport**/**Tipo**, «(tutte le lingue)» mappa alla chiave dati vuota. Pulsanti azione:
  **«➕ Aggiungi riga»**, **«📥 Precompila da Betfair»** (blu `#1565c0`), **«💾 Salva profilo»**.
  - **«📥 Precompila da Betfair» (#282 PR 11):** riempie la tabella coi nomi squadra
    **permanenti** presenti nel **dizionario locale** — una riga per nome, **Betfair già scritto**
    nel campo (resta un `CTkEntry` editabile, **niente tendina**), **Sport** impostato, **Tipo**
    `team`, **«Come lo scrive il canale» vuoto** (ci va l'alias del canale) e **«Lingua» =
    «(tutte le lingue)»** (agnostica; l'utente può restringerla). Non distruttivo/idempotente (salta i
    nomi già presenti). Con **dizionario locale vuoto** mostra un avviso e non aggiunge nulla.
    **Se un altro strumento tiene il lock del DB** fa fail-fast con «⏳ Dizionario occupato:
    riprova tra poco» (arancione) **senza congelare la finestra**. La riga di stato riporta
    l'esito (es. «📥 Aggiunti N nomi Betfair… ; M già presenti»).
- **🎯 Mercati (Dizionario mercati):** profilo + tabella **Inizia dopo · Finisce prima ·
  Testo mercato · Mercato (catalogo) · Selezione (catalogo) · Lingua**. Legge il mercato da una
  posizione precisa del messaggio e imposta Mercato/Selezione dal catalogo XTrader. La tendina
  **«Lingua»** (epica multilingua **#3 slice 5c**, speculare alla colonna Lingua del Dizionario
  nomi) tagga la voce con la **lingua della fonte** (`IT`/`EN`/`ES`) oppure **«(tutte le lingue)»**
  = agnostica (default): quando la lingua-fonte è impostata, le voci della lingua ESATTA hanno
  priorità sulle agnostiche e quelle di un'altra lingua sono saltate (le agnostiche restano sempre
  valide → i dizionari mercati esistenti continuano a funzionare). Come per la colonna analoga dei
  nomi, «(tutte le lingue)» mappa alla chiave dati vuota.
- **🌳 Mapping guidato (`guided_mapping_gui.py`):** albero a cascata per costruire il dizionario
  nomi **senza digitare i nomi Betfair a mano**. Controlli, dall'alto:
  riga **Profilo** (destinazione, con **«🆕 Nuovo»**) → riga **Sport** (tendina Calcio/Tennis/
  Basket/Rugby) + **Competizione** (tendina popolata dal dizionario locale) → casella
  **«Filtra squadre»** (con **«Pulisci»**) → tabella a 2 colonne **Squadra Betfair · Come la
  chiama il canale** (una riga editabile per squadra) → **«💾 Salva nel profilo»** (verde
  `#2e7d32`) + riga di stato.
  - **Flusso:** scegli Sport → Competizione; le **squadre** appaiono dall'unione
    `participant_1`/`participant_2` degli eventi di quella competizione. Accanto a ciascuna scrivi
    l'alias del canale; al salvataggio le righe vengono **fuse** nel profilo `name_mappings` scelto
    (stesso store della scheda «⚽ Calcio»), come `entity_type=team`. La **competizione serve solo a
    navigare** (non entra nel mapping: il parser non filtra per competizione).
  - **Pre-compilazione:** gli alias già salvati per una squadra (per-sport) ricompaiono accanto ad
    essa in qualunque competizione, così ri-salvare **aggiorna** senza azzerare mapping condivisi.
  - **Cap di rendering** `500` squadre (come il viewer, Fase 2): competizioni molto popolose non
    bloccano; il modello tiene comunque tutte le squadre (gli alias scritti restano salvati anche se
    non visibili) e «Filtra» restringe. Sopra il cap compare un avviso arancione.
  - **Stati fail-safe:** se un altro strumento tiene il lock del DB le tendine/l'elenco fanno
    fail-fast con **«⏳ Dizionario occupato: riprova tra poco»** (arancione) **senza congelare la
    finestra**; con dizionario vuoto mostra un avviso e non aggiunge nulla.

### 7.6 🔵 Betfair Sync — RIMOSSA
La scheda **«🔵 Betfair Sync»** (login a Betfair, download del catalogo, sync e auto-sync del
dizionario, gestione credenziali) **è stata rimossa**: il bridge non contatta più Betfair, non
fa login e non fa auto-sync. Il **dizionario locale** (`betfair_dictionary.db`) resta ma è
**popolato a mano** dall'utente coi propri campi personalizzati; le schede superstiti (📖
Dizionario, 🧹 Nomi squadra, 🌳 Mapping guidato) lo leggono in sola lettura. Nel gruppo
Strumenti non esiste più una scheda «Betfair Sync».

### 7.7 📖 Dizionario (`dictionary_viewer_gui.py`)
Titolo **"🔵  Dizionario (locale, sola lettura)"**. Browser gerarchico
Sport→Competizioni→Eventi→Mercati→Selezioni con filtro **Livello**, filtro **Sport**,
checkbox **"Solo attivi"**, **"🔄 Aggiorna"**, ricerca (con **"Pulisci"**), riga conteggi,
tabella risultati.
- **Tabella:** griglia **nativa `ttk.Treeview`** (non più una griglia di label CTk) con
  **scrollbar verticale e orizzontale**, intestazioni di colonna e **larghezza per-colonna** →
  colonne allineate (la scrollbar orizzontale serve ai livelli larghi — Eventi ha 8 colonne — per
  raggiungere le colonne di destra come Casa/Trasferta e Attivo senza che la finestra sbordi).
  È **virtualizzata** (renderizza solo le righe visibili) e le righe sono **limitate a `500`**
  (`_ROW_CAP`): così i livelli grandi (Mercati ≈ 3k, Selezioni ≈ 12k) **non bloccano** più la
  finestra (prima costruiva ~88.000 widget → freeze "Non risponde" di minuti). Se un livello
  supera il cap, la riga conteggi lo segnala e invita a restringere con **Sport**/**Cerca**.
- **Stati della riga conteggi** (label sopra la tabella):
  - *normale:* `<Livello>: N totali, M attivi (mostrate K di S righe).` (`K` = righe in tabella,
    `S` = righe che passano i filtri prima del cap);
  - *elenco troncato* (righe filtrate > `500`): alla riga normale si aggiunge
    **"⚠️ Elenco troncato a 500: restringi con «Sport» o «Cerca» per vedere le righe che ti servono."**;
  - *DB non disponibile:* **"⚠️ Dizionario non disponibile (DB locale non apribile)."**;
  - *dizionario occupato* (un altro strumento tiene il lock del DB in quel momento):
    **"⏳ Dizionario in aggiornamento: premi 🔄 Aggiorna tra poco."** — la vista fa
    **fail-fast** e **non** blocca/freeze la GUI;
  - *errore di lettura:* **"⚠️ Errore lettura dizionario: &lt;Tipo&gt;"**.

### 7.8 📒 Diario (`journal_view_gui.py`)
Titolo **"📒  Diario eventi (locale, sola lettura)"**. Vista di consultazione del **diario
eventi** (`event_journal.jsonl`): «cosa ha fatto il bridge» (avvii/arresti, segnali,
conferme XTrader, riconnessioni, pulizie CSV). **Sola lettura**: non scrive né de-redige mai
il ledger (gli eventi sono già redatti sul file: token e `chat_id` mai in chiaro). Riusa la
stessa logica pura della CLI `journal_view`.
- **Barra filtri:** dropdown **"Tipo"** (`(tutti i tipi)` + gli 11 tipi evento), dropdown
  **"Ultimi"** (`50/100/200/500/Tutti`), **"🔄 Aggiorna"**, **"📂 Apri cartella"** (apre la
  cartella che contiene il ledger).
- **Riga conteggi** (sopra la tabella): `Diario: N eventi totali (mostrati M).`; su errore di
  lettura **"⚠️ Errore lettura diario: &lt;Tipo&gt;"** (fail-safe, nessun crash della finestra).
- **Tabella** (griglia di label in `CTkScrollableFrame`): colonne **Quando** (`ts` reso
  leggibile locale) · **Tipo** · **Dati (redatti)** (JSON compatto, chiavi ordinate).
- **Invariante di sicurezza:** la vista mostra i valori **esattamente come sono sul file** —
  mai token/chat in chiaro, mai scrittura sul diario.

### 7.9 🧹 Nomi squadra (`known_teams_gui.py`)
Titolo **"🧹  Nomi squadra noti (permanenti) — ripulitura"**. Gestione dei nomi squadra
**permanenti** del dizionario locale (`betfair_known_teams`, #282): l'unica vista che li
**elimina** (il mark-and-sweep non li tocca, quindi vanno ripuliti a mano quando obsoleti/errati
— squadre retrocesse/rinominate).
- **Barra:** dropdown **"Sport"** (`(tutti gli sport)` + i 4 sport), **"🔄 Aggiorna"**.
- **Riga conteggi:** `N nomi noti.` (o avviso se il dizionario non è disponibile).
- **Elenco** (`CTkScrollableFrame`): una riga per nome = **Sport** · **nome squadra** ·
  **"🗑 Elimina"** (rosso `#c62828`). L'eliminazione è **immediata** (nessun dialogo di
  conferma) e ricarica l'elenco.
- **Stati fail-safe:** se un altro strumento tiene il lock del DB fa fail-fast con
  «⏳ Dizionario occupato: riprova tra poco» **senza congelare** la finestra (probe non
  bloccante sul lock del DB); con dizionario vuoto mostra un avviso e non opera.
- **Non tocca** ID (`MarketId`/`SelectionId`), CSV, o il flusso di piazzamento: agisce solo
  sulla tabella dei nomi permanenti.

### 7.10 📋 Riepilogo configurazione (`config_summary_gui.py`) — #293 slice 3, SOLA LETTURA
Colpo d'occhio su ciò che il bridge farà davvero, senza saltare tra Generale/Betfair/Chat
sorgenti/Parser/Mapping. È il primo passo della **schermata Riepilogo** dell'IA #293 (che a
regime vivrà nel gruppo ④ Impostazioni); per ora è un pannello dell'hub Strumenti. **Non scrive
né modifica nulla**: legge la config viva e lo stato del dizionario locale, riusando gli **stessi predicati
del runtime** (`signal_router`/`parser_manager`/`safety_guard`/`*_mapping_store`) così il
riepilogo non può divergere dal comportamento reale. Logica in `config_summary.py` (modulo puro).
- **Stato globale (in alto):**
  - **Modalità**: **`🔴 MODALITÀ REALE`** (rosso) oppure **`🧪 Simulazione (DRY_RUN)`** (verde).
  - **Dizionario locale**: `Dizionario locale: presente|vuoto` (presente = il DB locale contiene
    almeno un evento attivo). Con la rimozione di «Betfair Sync» non c'è più uno stato di login.
  - **`Canali pronti: N/M`**.
- **Una card per canale** (`CTkScrollableFrame`): intestazione `nome (chat_id)` (o solo l'id, o
  «(canale senza chat_id)»), riga **`Parser: <nome>`** (o `—`; un parser risolto ma **non
  caricabile** — file mancante/invalido — porta un **`⚠`** sulla riga stessa: `Parser: <nome> ⚠`).
  **PR-2 (router multi-parser):** se la chat ha **più** parser, la riga diventa
  **`Parser (N): A, B`** (lista in ordine di priorità). Il **`⚠`** compare se **un qualsiasi**
  parser della lista non è caricabile — **anche un secondario** (un secondario rotto perderebbe
  bet in silenzio, quindi va reso visibile): la chat risulta **non pronta** e la riga «Pronto?»
  elenca i nomi non caricabili. Con un solo parser il testo è invariato.
  riga traduzioni **`Nomi ✓N · Mercati ✓N`** (o `—` se nessuna), e l'indicatore **«Pronto?»**:
  - **`✅ Pronto`** (verde) solo se il canale è ascoltabile (chat_id presente + sorgente attiva),
    ha un parser che **si carica ed è valido**, e **tutte** le mappature selezionate si risolvono.
    **PR-2 (multi-parser):** con più parser per la chat, la readiness copre **TUTTI** i parser
    della lista — un secondario non caricabile **o** con un profilo di mappatura fantasma rende
    il canale **non pronto** (un secondario rotto perderebbe/sbaglierebbe bet in silenzio);
  - **`⚠ <motivo>`** (arancione) altrimenti — motivi: «Manca chat_id», «Sorgente disattivata»,
    «Nessun parser assegnato», «Parser non caricabile: <nome>», «Traduzione mancante: <profili>».
- **«Pronto?» è severo e fail-closed** (scelta del proprietario): un profilo di mappatura
  fantasma `⚠` (selezionato ma inesistente) **non** conta come traduzione attiva e rende il canale
  non pronto — coerente col fail-closed che scarta i segnali con nome/mercato non risolto. Nessun
  falso verde.
- **Aggiornamento**: al **cambio scheda** nell'hub il pannello si ri-legge (`refresh_options`),
  così riflette modifiche fatte in altre schede senza riaprire la finestra.

---

## 8. Stati dinamici e indicatori

Il design deve rappresentare chiaramente questi stati (testi verbatim dal codice):

**Indicatore di stato (header):**
| Stato | Testo | Colore |
|---|---|---|
| Fermo | `⬜  OFFLINE` | rosso `#ef5350` |
| In esecuzione | `⬜  ATTIVO` | verde `#66bb6a` |
| Riconnessione | `⬜  RICONNESSIONE…` | arancione `#ffa726` |

**Righe attive (header):** testo `N/M` in arancione theme-aware (`#e65100` chiaro / `#ffb74d` scuro) — quante scommesse/righe
sono attive ora sul massimo consentito. Rilevante nelle modalità coda multi-riga. Nota (#192,
auto-raise): un **singolo messaggio multi-riga** è un blocco/istruzione **coerente** che non viene
mai spezzato dal tetto — le sue righe entrano tutte insieme anche se superano `M`. Quindi `N` può
temporaneamente **superare `M`** (es. `4/2`); il design non deve trattare `N>M` come errore ma
come "blocco multi intero". Il tetto continua a limitare l'accumulo **tra messaggi distinti**.

**CSV bloccato:** quando XTrader tiene lockato il file e le scritture falliscono più volte,
compare **"🔒 CSV bloccato da XTrader"** (con numero tentativi), poi il recupero.

**Banner reale:** vedi §6.2 — persistente finché la modalità reale è attiva.

**Pulsanti START/STOP:** all'avvio STOP è **disabilitato**; dopo AVVIA si invertono gli stati.

---

## 9. Flussi critici e dialoghi di conferma

Questi flussi hanno **attrito intenzionale**: il design deve preservarne la forza.

### 9.1 Attivazione MODALITÀ REALE (doppia conferma)
Passando da simulazione a reale (o caricando un profilo con `dry_run:false`) appare un
dialogo:
- **Titolo:** `Conferma MODALITÀ REALE`
- **Testo:**
  > ATTENZIONE: stai per attivare la MODALITÀ REALE.
  > XTrader potrà piazzare scommesse REALI.
  >
  > Per confermare digita:  REALE
- L'utente **deve digitare** `REALE` (case-insensitive). Se annulla → resta in simulazione.
- Dopo la conferma: banner rosso persistente + evento `REAL_MODE_ENABLED` nel log.

### 9.2 Attivazione modalità MULTI-segnale (conferma Sì/No)
Passando a `APPEND_ACTIVE` o `QUEUE_UNTIL_CONFIRMED` (più righe/scommesse insieme):
- **Titolo:** `Conferma modalità MULTI-segnale` — dialogo Sì/No. Se No → resta a
  `OVERWRITE_LAST` (un solo segnale attivo).

### 9.3 Avvio in modalità reale (conferma Sì/No a OGNI avvio, automatico e manuale)
In modalità reale ogni avvio del listener chiede una conferma Sì/No (audit #259 C5,
decisione proprietario: un `dry_run:false` già salvato non ripassa dal phrase gate, quindi
serve attrito a ogni avvio):
- **Avvio automatico** (`auto_start_listener` attivo), a ogni apertura:
  - **Titolo:** `Avvio automatico — MODALITÀ REALE`
  - **Testo:**
    > L'avvio automatico è attivo in MODALITÀ REALE: il bridge inizierà a scrivere i segnali
    > nel CSV (scommesse reali) appena ricevuti.
    >
    > Avviare ora il listener?
- **START manuale** (pulsante AVVIA), a ogni pressione:
  - **Titolo:** `START — MODALITÀ REALE`
  - **Testo:**
    > Sei in MODALITÀ REALE: il bridge scriverà i segnali nel CSV (scommesse reali) appena
    > ricevuti.
    >
    > Avviare ora il listener?
  - Se l'utente annulla: log `⏸️ Avvio in modalità reale annullato.` e nessun avvio.

### 9.4 Perché il bridge non parte (errori di preflight) e avvisi non bloccanti
AVVIA è bloccato (con messaggio nel log) se: manca il Bot Token, manca il CSV Path, il
Timeout non è un intero > 0, **nessuna chat/sorgente è configurata**, oppure — **#311-1.3** —
**nessun Parser Personalizzato è configurato** (globale o per-chat): il parser automatico è
disattivato nel live, quindi un listener senza parser sembrerebbe «ATTIVO» ma ignorerebbe
ogni segnale in silenzio. Messaggio verbatim: *«❌ Nessun Parser Personalizzato configurato
(globale o per-chat): il parser automatico è disattivato e il listener ignorerebbe OGNI
segnale. Configura almeno un Parser Personalizzato prima di avviare (scheda 🧩 Parser).
Avvio annullato.»* (prima era un avviso ⚠ non bloccante). Il design deve rendere questi
requisiti **evidenti prima** di premere AVVIA (validazione inline, stati disabilitati, hint).

AVVIA invece **procede ma con avviso ⚠️ nel log eventi** (audit #259) quando:
- **nessuna chat sorgente è ATTIVA** (es. tutte disattivate): il listener parte «sordo» e
  non processerà segnali — l'avvio **automatico** in questo stato è invece bloccato;
- una sorgente ha **`enabled` malformato** (typo): è considerata DISATTIVATA (fail-closed);
- una riga di **mappatura nomi** ha sport/tipo non riconosciuto: è IGNORATA (fail-closed).
Il design può dare a questi avvisi più visibilità (banner/badge), ma non deve trasformarli
in blocchi.

### 9.4-bis Seconda istanza rifiutata all'avvio (#311-1.1)
Il bridge gira in **una sola istanza**. Un secondo avvio mostra — **prima** che qualunque
finestra dell'app venga costruita — un **messagebox di avviso** (`messagebox.showwarning`
su root temporanea) e il processo esce subito:
- **Titolo:** `XTrader Bridge`
- **Testo (verbatim):**
  > XTrader Bridge è già in esecuzione.
  >
  > Chiudi l'altra istanza prima di avviarne una nuova: due istanze attive potrebbero
  > scrivere lo stesso CSV e piazzare scommesse doppie.

**Invariante di sicurezza:** la seconda istanza NON avvia listener, NON scrive né svuota il
CSV dell'istanza attiva. Il lock (mutex di sistema su Windows) si libera da solo a chiusura
o crash: nessun blocco orfano da gestire nella UI. Il design può ristilizzare il dialogo, ma
il messaggio deve restare un **avviso bloccante che chiude la seconda istanza**.

### 9.5 Ciclo di vita di un segnale (per capire cosa mostrare)
`ricevuto → validato → scritto su CSV → (conferma/rifiuto XTrader oppure timeout) →
CSV svuotato`. La UI riflette questo tramite: contatori Dashboard, tab Stato (ultimo
segnale/CSV/errore), log, e (in multi-riga) indicatore N/M.

---

## 10. Palette colori e stile attuale

Tema **scuro** di default (commutabile chiaro/scuro dal toggle nell'header, #288 Delta 1). Dalla
**#288 Delta 3** i colori **semantici di stato** (header, titolo, OFFLINE/ATTIVO/RICONNESSIONE, righe
attive, warning «nessuna chat», banner reale) sono **theme-aware**: tuple CustomTkinter `(light,
dark)` in `app.py` (`_COLOR_*`). La variante **dark è quella storica** (invariata); la variante
**light** è scelta per il contrasto sul relativo sfondo chiaro. La **leggibilità (contrasto WCAG ≥
3.0) in entrambi i temi è verificata automaticamente** da `tests/integration/test_palette.py` (non
più solo smoke manuale). La semantica non cambia (rosso=errore/OFFLINE, verde=attivo, arancione=warning/
riconnessione). I **pulsanti d'azione** (AVVIA/STOP/Strumenti…) restano tinta unita con testo bianco
(leggibili in entrambi i temi) e non sono ancora convertiti a `(light, dark)`; anche i colori
secondari via `_set_last` (ultimo evento) restano hardcoded → follow-up estetico. Colori (light /
dark dove theme-aware; riferimento, non vincolo estetico):

| Ruolo | Colore (light / dark) |
|---|---|
| Sfondo header | `#e8eaf6` / `#1a1a2e` |
| Titolo | `#0d47a1` / `#4fc3f7` (ciano) |
| Stato OFFLINE / errore | `#c62828` / `#ef5350` (rosso) |
| Stato ATTIVO / recupero | `#2e7d32` / `#66bb6a` (verde) |
| Stato RICONNESSIONE | `#e65100` / `#ffa726` (arancione) |
| Warning «nessuna chat» | `#bf360a` / `#ffa726` (arancione) |
| Righe attive | `#e65100` / `#ffb74d` (arancione) |
| Banner reale (sfondo) | `#b71c1c` / `#7f1d1d` (rosso scuro), testo bianco |
| AVVIA | `#2e7d32` / hover `#1b5e20` (verde) |
| STOP / elimina | `#c62828` / hover `#7f0000` (rosso) |
| Pulsanti secondari (Salva/Tools bar) | `#37474f` / hover `#263238` (grigio) |
| Strumenti (primario) | `#4527a0` / hover `#311b92` (viola) |
| Carica profilo | `#1565c0` / hover `#0d47a1` (blu) |
| Testo neutro | `gray` |

**Semantica dei colori** (da preservare): **rosso = pericolo/stop/reale**, **verde =
ok/avvia/attivo**, **arancione = attenzione/transitorio**, **blu/ciano = neutro/azione
informativa**, **viola = strumenti**. Le emoji sono parte integrante del linguaggio visivo
attuale.

---

## 11. Inventario copy / microcopy

La UI comunica molto tramite **log e messaggi**. Alcuni testi chiave (verbatim) utili per
capire tono e contenuti; un redesign può razionalizzarli ma non deve perderne il
significato di sicurezza:

**Avvio/stop:** `🚀 Bridge avviato!` · `🛑 Bridge fermato.` ·
`🧪 DRY_RUN attivo (simulazione): il CSV operativo NON verrà scritto.` ·
`⚠️ Modalità REALE: i segnali validi verranno scritti nel CSV.` ·
`👂 In ascolto su Telegram...`

**Segnali:** `✏️ Messaggio→CSV ...` · `⚠️ Segnale scartato (...)` ·
`🗑️  N segnale/i scaduto/i rimosso/i dal CSV`

**Conferme:** `✅ XTrader ha confermato` · `❌ XTrader ha rifiutato`

**Errori:** `🔒 CSV bloccato da XTrader` ·
`❌ Scrittura CSV fallita: ... Segnale non registrato (riprovabile).` ·
`❌ Inserisci il Bot Token prima di avviare!`

**Connessione:** `✅ Connesso a Telegram.` ·
`🔌 Connessione persa (...): riconnessione tra Ns (tentativo N)…`

**Config:** `💾 Configurazione salvata` ·
`↩️ Attivazione modalità REALE ANNULLATA: il bridge resta in simulazione.`

**Livelli log** (con marker emoji): `INFO` · `WARNING` (⚠️) · `ERROR` (❌) · `SIGNAL` (📱).

> Nota: i **token** sono sempre redatti nei log (`[REDACTED_TOKEN]`); il testo dei messaggi
> di default non è loggato in chiaro (solo hash + 1ª riga). La UI non deve mai esporre
> segreti.

---

## 12. Glossario di dominio

| Termine | Significato |
|---|---|
| **Segnale** | Un messaggio Telegram che indica una scommessa (evento, mercato, selezione, quota, tipo). |
| **Bridge** | Questa app: legge Telegram, scrive il CSV, lo svuota. Non piazza scommesse. |
| **CSV operativo** | Il file (`segnali.csv`, 14 colonne) che XTrader monitora per piazzare. |
| **DRY_RUN / Simulazione** | Modalità sicura: riconosce i segnali ma **non** scrive il CSV. Default ON. |
| **Modalità reale** | `dry_run=false`: scrive davvero il CSV → XTrader può scommettere. |
| **Parser Personalizzato** | Regole (per colonna) che definiscono come estrarre i dati dal messaggio. |
| **Provider** | Etichetta/sorgente del segnale, scritta nella colonna Provider del CSV. |
| **Chat sorgente** | Una chat/canale Telegram da cui accettare segnali (multi-chat). |
| **Chat notifiche XTrader** | Chat separata dove XTrader comunica l'esito (confermato/rifiutato). |
| **Modalità coda** | Quante righe/scommesse tenere attive: `OVERWRITE_LAST` (1, sicuro) / `APPEND_ACTIVE` / `QUEUE_UNTIL_CONFIRMED`. |
| **Righe attive N/M** | Quante scommesse attive ora (N) sul massimo consentito (M). |
| **Modalità riconoscimento** | Come XTrader identifica il segnale: `NAME_ONLY` / `ID_ONLY` / `BOTH`. |
| **Value-map** | Traduce alias (es. `GG`, `OVER 2.5`, `BACK/LAY`) nei valori XTrader (`PUNTA/BANCA`). |
| **Dizionario nomi / mercati** | Tabelle che traducono nomi squadra / frasi-mercato nei valori canonici XTrader. |
| **Dizionario locale** | DB locale sola-lettura (`betfair_dictionary.db`) per arricchire gli ID; popolato a mano dall'utente. Con la rimozione di «Betfair Sync» l'arricchimento nel CSV live è oggi disattivato (seam pronto). |
| **Dedupe** | Anti-duplicato: lo stesso messaggio ravvicinato non viene riscritto. |
| **Timeout / auto-clear** | Dopo N secondi il segnale scade e il CSV torna a solo header. |
| **BetType** | Lato scommessa. Validi indifferentemente `PUNTA`/`BANCA` (IT) e `BACK`/`LAY` (EN) — issue #3; output CSV sempre canonico `PUNTA`/`BANCA`. ES `FAVOR`/`CONTRA` non ancora supportati (rifiutati, fail-closed). |

---

## 13. Invarianti di sicurezza — cosa NON toccare

Il design può cambiare **aspetto e disposizione**, ma NON deve indebolire queste garanzie
(sono il motivo per cui l'app è "noiosa" di proposito):

1. **Distinzione reale vs simulazione sempre inequivocabile** (banner/indicatore forte).
2. **Attivazione modalità reale con attrito** (digitare `REALE`). Non semplificarla in un
   toggle immediato.
3. **Attivazione multi-segnale con conferma** esplicita.
4. **AVVIA bloccato senza chat configurata** (niente segnali da chat arbitrarie).
5. **Un solo segnale attivo di default** (`OVERWRITE_LAST`); l'indicatore N/M nelle
   modalità multi-riga.
6. **Token mai in chiaro nella UI/log**; testo messaggi non loggato di default.
7. **STOP e chiusura finestra fermano davvero** il bridge.
8. **Errori parlanti** sul perché non parte / perché non scrive.
9. **Nessuna automazione "di puntata diretta"** verso Betfair/XTrader dalla UI: l'app scrive
   solo il CSV.

---

## 14. Pain point e opportunità di design

Aree dove un redesign porterebbe più valore (spunti, non requisiti):

- **Densità del Parser Personalizzato (§7.1).** È la schermata più difficile: griglia a 14
  colonne, delimitatori "Inizia dopo/Finisce prima", trasformazioni, value-map, mapping,
  output multi-riga, anteprima e diagnostica. Opportunità: onboarding/wizard, progressive
  disclosure, anteprima live più chiara, esempi inline, riduzione del carico cognitivo.
- **Onboarding "primo avvio".** Oggi l'utente deve capire da sé token→chat→csv→parser. Un
  flusso guidato ridurrebbe gli errori di setup (che bloccano AVVIA).
- **Gerarchia della finestra principale.** Molte tab in poco spazio (larghezza fissa 720).
  Distinguere meglio "operatività quotidiana" (stato, start/stop, log) da "configurazione".
- **Feedback di stato più ricco.** Timeline/animazione del ciclo di vita del segnale;
  visualizzazione più chiara di "riconnessione" e "CSV bloccato".
- **Leggibilità del log.** Oggi è testo monospace filtrabile: opportunità di badge per
  livello, raggruppamenti, evidenza degli errori.
- **Modalità reale ancora più evidente.** Es. cornice/bordo dell'intera finestra, non solo
  banner, per l'uso minimizzato.
- **Coerenza tra i pannelli Strumenti** (molti pattern tabella/profilo simili ma non
  identici: Mapping, Chat sorgenti, Provider, Profili). Un design system unificherebbe.
- **Responsività verticale.** La finestra è ridimensionabile in altezza: definire come
  scalano le aree (log/tabelle) al variare dello spazio.

---

## 15. Deliverable utili al team

Per un handoff efficace, sarebbe utile ricevere dal design (indicativo):

1. **Design system leggero:** palette (con la semantica sicurezza), tipografia, spaziature,
   componenti (bottone primario/secondario/pericolo, input, dropdown, checkbox, tab,
   tabella/griglia, badge di stato, banner, dialoghi di conferma).
2. **Mockup delle schermate chiave:** finestra principale (stati OFFLINE/ATTIVO/RECONNECT/
   REALE), tab Sicurezza, Log, e il Parser Personalizzato ripensato.
3. **Pattern degli stati:** come rappresentare ATTIVO/OFFLINE/RICONNESSIONE, N/M, CSV
   bloccato, banner reale.
4. **Flussi con attrito:** redesign dei 3 dialoghi di conferma (§9) mantenendone la forza.
5. **Note di fattibilità con CustomTkinter** (§3): cosa è realizzabile col toolkit attuale
   e cosa richiederebbe un cambio di tecnologia.

> **Vincoli da tenere sempre presenti:** Windows desktop, italiano, tema scuro di default
> (commutabile chiaro/scuro dal toggle nell'header, #288 Delta 1), CustomTkinter,
> e le **invarianti di sicurezza (§13)**. Il resto è aperto al ridisegno.
