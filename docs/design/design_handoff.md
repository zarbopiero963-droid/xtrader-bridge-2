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

---

## 3. Stack tecnico attuale (vincoli di design)

- **Toolkit GUI:** [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) (`ctk`)
  sopra Tkinter. È un layer di widget "moderni" su Tkinter.
- **Tema attuale:** `set_appearance_mode("dark")` + `set_default_color_theme("blue")` →
  **tema scuro** con accento blu.
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

HUB "🧰 STRUMENTI"  (finestra a tab, caricata su richiesta)
      ├─ 🧩 Parser              → Parser Personalizzato (costruttore regole)
      ├─ 📡 Chat sorgenti       → gestione multi-chat
      ├─ 📇 Provider            → anagrafica nomi Provider
      ├─ 📁 Profili             → profili impostazioni salvabili
      ├─ 🗺️ Mapping             → (sotto-tab: ⚽ Calcio nomi · 🎯 Mercati)
      ├─ 🔵 Betfair Sync        → credenziali + sync dizionario Betfair
      └─ 📖 Dizionario Betfair  → browser sola-lettura del dizionario locale
```

**Frequenza d'uso (per prioritizzare la gerarchia visiva):**
- **Quotidiano / sempre a vista:** stato ATTIVO/OFFLINE, banner reale, righe attive,
  AVVIA/STOP, ultimo errore, log.
- **Setup iniziale (poi raro):** tab Generale (token/chat/csv), Parser Personalizzato,
  Chat sorgenti, Betfair, Mapping.
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
| 📄 CSV Path | `csv_path` | testo (percorso file) |
| ⏱️ Timeout (sec) | `clear_delay` | intero > 0 |
| 🏷️ Provider | `provider` | testo |

**Tab 🎯 Riconoscimento** — 1 dropdown:
- **"🎯 Modalità riconoscimento"** → opzioni `ID_ONLY` / `NAME_ONLY` / `BOTH`.

**Tab 🛡️ Sicurezza** — checkbox + campi + dropdown:
- ☐ **"🧪 Simulazione (DRY_RUN): NON scrive il CSV operativo"** (`dry_run`)
- ☐ **"▶️ Avvio automatico all'apertura (in modalità REALE chiede conferma)"** (`auto_start_listener`)
- ☐ **"🕵️ Logga il testo completo dei messaggi (debug; OFF = solo hash + 1ª riga)"** (`debug_message_payload`)
- Campo **"📅 Limite segnali al giorno"** (`max_per_day`)
- Campo **"🔢 Max segnali attivi (modalità coda multi-riga)"** (`max_active_signals`)
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

L'hub **"🧰 Strumenti"** è una finestra a tab caricata su richiesta. I 7 pannelli:

### 7.1 🧩 Parser Personalizzato (`custom_parser_gui.py`) — il pannello più complesso
Costruttore visuale che definisce **come estrarre ogni colonna del CSV** da un messaggio,
senza toccare il codice. È il cuore della configurazione avanzata. Sezioni:

- **Intestazione:** `Nome parser`, `Modalità` (`(eredita globale)` + opzioni), `Sport`
  (`(non specificato)` / Calcio / Tennis / Basket / Rugby Union), pulsante **"➕ Provider"**.
- **Parser salvati:** dropdown `(nessuno)` + **"🆕 Nuovo"**, **"📂 Carica"**, **"📑 Duplica"**,
  **"🗑 Elimina"**.
- **Catalogo XTrader:** dropdown Mercato + dropdown Selezione + **"➕ Inserisci regole fisse"**.
- **Mappatura nomi:** separatore (placeholder `v`), **"🗺️ Dizionario nomi"**, riga di
  checkbox-profili (i profili "fantasma" mancanti sono marcati `⚠`).
- **Mappatura mercati:** **"🎯 Dizionario mercati"** + checkbox-profili.
- **Output multi-riga (un messaggio → più righe CSV):** checkbox **"MultiMarket (più
  mercati)"** + **"➕ Aggiungi mercato"**; checkbox **"MultiSelection (più selezioni)"** +
  **"➕ Aggiungi selezione"**; ogni riga ha campi Tipo mercato/Mercato/Selezione/Quota/
  BetType/Handicap + checkbox **"Attiva"** + **"🗑 Rimuovi"**.
- **Griglia regole (14 colonne CSV fisse):** intestazioni **Colonna · Inizia dopo ·
  Finisce prima · Valore fisso · Trasformazione · Value-map · Obblig.** Ogni riga: nome
  colonna (label), 2 entry delimitatori, entry/dropdown valore fisso (dropdown Provider se
  colonna = Provider), dropdown Trasformazione, dropdown Value-map, checkbox **Obblig.**
- **Azioni:** **"💾 Salva"**, **"🧪 Prova messaggio"**, **"📋 Copia diagnostica"**.
- **Area di test:** textbox "Messaggio di prova" + verdetto (`✅ Pronto` / `⛔ …`).
- **Anteprima righe generate (#192):** tabella `# · Tipo (Base/Mercato/Selezione) · Esito ·
  Riga CSV`.
- **Diagnostica per colonna:** tabella `Colonna · Stato (OK/MANCANTE) · Motivo · Inizia
  dopo · Finisce prima · Valore estratto`.

> Questa è la schermata che più beneficerebbe di un redesign: è densa, tabellare, con molte
> colonne e concetti (delimitatori, trasformazioni, value-map, mapping, multi-riga). Vedi §14.

### 7.2 📡 Chat sorgenti (`source_chats_gui.py`)
Titolo **"📡  Chat sorgenti (multi-chat)"**. Tabella con colonne: **Attiva · Nome · Chat ID
· Modalità (PRE/LIVE) · Provider · Parser** (override, sentinel `(predefinito)`) · ✕ (elimina).
Pulsanti **"➕ Aggiungi sorgente"**, **"💾 Salva"**. Riga di stato con esito salvataggio.

### 7.3 📇 Provider (`provider_gui.py`)
Titolo **"📇  Anagrafica Provider"**. Campo nome + **"➕ Aggiungi"**; lista provider salvati
con **"🗑 Rimuovi"** per riga. Anagrafica riusabile nella colonna Provider dei parser.

### 7.4 📁 Profili (`profiles_gui.py`)
Titolo **"📁  Profili impostazioni"**. Salva/ricarica snapshot di configurazione (il **token
NON** viene salvato nei profili). Campo nome + **"💾 Salva profilo"**; lista con **"↺ Carica"**
(blu) e **"🗑 Elimina"**. Avviso: fermare il bridge (STOP) prima di caricare un profilo.

### 7.5 🗺️ Mapping (`name_mapping_gui.py`) — 2 sotto-tab
- **⚽ Calcio (Dizionario nomi squadra):** profilo (Nuovo/Rinomina/Elimina) + tabella
  **Country · Betfair/XTrader · Provider · Sport · Tipo**. Traduce i nomi del canale nei
  nomi attesi da Betfair/XTrader.
- **🎯 Mercati (Dizionario mercati):** profilo + tabella **Inizia dopo · Finisce prima ·
  Testo mercato · Mercato (catalogo) · Selezione (catalogo)**. Legge il mercato da una
  posizione precisa del messaggio e imposta Mercato/Selezione dal catalogo XTrader.

### 7.6 🔵 Betfair Sync (`sync_tab_gui.py`)
Titolo **"🔵  Betfair Sync (locale, read-only)"**. Sincronizza un **dizionario Betfair
locale** (sola lettura, nessuna scommessa). Contiene:
- 5 campi credenziali (Delayed App Key, Username, Password, Certificato .crt/.pem, Private
  key .key; i segreti mascherati).
- Selezione **Sport** (checkbox Calcio/Tennis/Basket/Rugby Union), **Giorni avanti**.
- Auto-sync: checkbox **"Auto sincronizza dizionario"** + **"Orario (HH)"** + righe di stato
  (Ultima / Prossima / Stato auto sync).
- Stato login/sync (es. `Stato login: ✅ connesso`).
- Pulsanti: **"💾 Salva credenziali"**, **"🔑 Accedi"**, **"🔄 Sincronizza ora"**,
  **"🚪 Logout"**, **"🗑️ Cancella credenziali salvate"**.

### 7.7 📖 Dizionario Betfair (`dictionary_viewer_gui.py`)
Titolo **"🔵  Dizionario Betfair (locale, sola lettura)"**. Browser gerarchico
Sport→Competizioni→Eventi→Mercati→Selezioni con filtro **Livello**, filtro **Sport**,
checkbox **"Solo attivi"**, **"🔄 Aggiorna"**, ricerca (con **"Pulisci"**), riga conteggi,
tabella risultati.

---

## 8. Stati dinamici e indicatori

Il design deve rappresentare chiaramente questi stati (testi verbatim dal codice):

**Indicatore di stato (header):**
| Stato | Testo | Colore |
|---|---|---|
| Fermo | `⬜  OFFLINE` | rosso `#ef5350` |
| In esecuzione | `⬜  ATTIVO` | verde `#66bb6a` |
| Riconnessione | `⬜  RICONNESSIONE…` | arancione `#ffa726` |

**Righe attive (header):** testo `N/M` in arancione (`#ffb74d`) — quante scommesse/righe
sono attive ora sul massimo consentito. Rilevante nelle modalità coda multi-riga.

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

### 9.3 Avvio automatico in modalità reale (conferma a ogni apertura)
Se `auto_start_listener` è attivo **e** siamo in modalità reale, a ogni apertura:
- **Titolo:** `Avvio automatico — MODALITÀ REALE`
- **Testo:**
  > L'avvio automatico è attivo in MODALITÀ REALE: il bridge inizierà a scrivere i segnali
  > nel CSV (scommesse reali) appena ricevuti.
  >
  > Avviare ora il listener?

### 9.4 Perché il bridge non parte (errori di preflight)
AVVIA è bloccato (con messaggio nel log) se: manca il Bot Token, manca il CSV Path, il
Timeout non è un intero > 0, oppure **nessuna chat/sorgente è configurata**. Il design deve
rendere questi requisiti **evidenti prima** di premere AVVIA (validazione inline, stati
disabilitati, hint).

### 9.5 Ciclo di vita di un segnale (per capire cosa mostrare)
`ricevuto → validato → scritto su CSV → (conferma/rifiuto XTrader oppure timeout) →
CSV svuotato`. La UI riflette questo tramite: contatori Dashboard, tab Stato (ultimo
segnale/CSV/errore), log, e (in multi-riga) indicatore N/M.

---

## 10. Palette colori e stile attuale

Tema **scuro**. Colori usati oggi (riferimento, non vincolo estetico):

| Ruolo | Colore |
|---|---|
| Sfondo header | `#1a1a2e` (blu-grigio scuro) |
| Titolo | `#4fc3f7` (ciano) |
| Stato OFFLINE / errore | `#ef5350` (rosso) |
| Stato ATTIVO / recupero | `#66bb6a` (verde) |
| Stato RICONNESSIONE / warning | `#ffa726` (arancione) |
| Righe attive | `#ffb74d` (arancione chiaro) |
| Banner reale (sfondo) | `#7f1d1d` (rosso scuro), testo bianco |
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
| **Dizionario Betfair** | DB locale sola-lettura per arricchire gli ID (nessuna scommessa). |
| **Dedupe** | Anti-duplicato: lo stesso messaggio ravvicinato non viene riscritto. |
| **Timeout / auto-clear** | Dopo N secondi il segnale scade e il CSV torna a solo header. |
| **BetType** | `PUNTA` (back) o `BANCA` (lay). |

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

> **Vincoli da tenere sempre presenti:** Windows desktop, italiano, tema scuro, CustomTkinter,
> e le **invarianti di sicurezza (§13)**. Il resto è aperto al ridisegno.
