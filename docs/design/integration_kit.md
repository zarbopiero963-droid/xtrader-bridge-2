# XTrader Signal Bridge — Kit di integrazione (design → CustomTkinter)

> **Cos'è.** Un deliverable **di design**: fa da ponte 1:1 tra i mockup HTML e il codice
> CustomTkinter esistente. Contiene i valori pronti (colori, dimensioni, mappa widget) così
> l'applicazione delle patch è meccanica. **Non modifica il codice dell'app**: il merge resta
> manuale del proprietario (vincolo del brief). Riferimenti al design: `XTrader Design System.dc.html`,
> `XTrader States Mockup.dc.html`, prototipo `XTrader Bridge.dc.html`.

---

## 0. Come usarlo

1. Aggiungi un modulo tema centralizzato (§1) — un solo punto di verità per i colori.
2. Sostituisci gli HEX hardcoded con le costanti (tabella §2 — **mappa storica**: in `app.py` è
   già applicata, vedi «Stato applicazione»).
3. Applica lo spec widget-per-widget (§3) e la mappa schermata→file (§4, con file:riga attuali).
4. Prima di toccare label visibili, leggi la nota i18n (§5).

Gli HEX della §2 sono la **provenienza** della migrazione già applicata: oggi `app.py` non contiene
più quei valori grezzi, ma li instrada tramite gli alias `_COLOR_*` → token `ui_theme` (`app.py`
~240-248). I token restano verificati contro il design system.

> **Stato applicazione.** **PR-1** (branch `claude/ui-redesign-pr1-theme`) ha creato il modulo
> `xtrader_bridge/ui_theme.py` (§1) e applicato la migrazione colori di **`app.py`** (§2) — con i
> token "testo di stato" e "banner" WCAG-safe aggiunti oltre allo snippet originale (vedi §1). Un
> guard test (`tests/integration/test_palette.py::test_app_py_migrato_ai_token…`) blocca ogni
> re-hardcode. **PR-2** (branch `claude/ui-redesign-pr2-name-mapping`) ha applicato **`name_mapping_gui.py`**
> (47 HEX → token, pannelli Nome + Mercato) con lo stesso pattern e un guard dedicato
> (`tests/integration/test_name_mapping_palette_pr2.py`, che blocca il re-hardcode e la semantica
> dei pulsanti). Le **PR successive** applicano i restanti moduli GUI (guided_mapping_gui,
> profiles_gui, custom_parser_gui, source_chats_gui, provider_gui, journal_view_gui, …) con gli
> stessi token. **PR-3** (branch `claude/ui-redesign-pr3-gui-modules`) ha applicato **8 moduli GUI**
> (`guided_mapping_gui`, `profiles_gui`, `source_chats_gui`, `provider_gui`, `custom_parser_gui`,
> `known_teams_gui`, `tools_gui`, `config_agent_gui`) + `signal_outcome` (63 HEX), con guard
> parametrizzato `tests/integration/test_gui_palette_pr3.py` e un nuovo token `WARN_WEAK` (vedi §1).
>
> **Allineamento §2/§4 al codice attuale (aggiornato):** i riferimenti `file:riga` della §4 sono
> stati riportati sull'`app.py` corrente (~4200 righe). La tab e il modulo **«Betfair Sync»**
> (`betfair/sync_tab_gui.py`) sono stati **rimossi** e non compaiono più nella mappa. Il **Dizionario**
> esiste ancora ma **non** è più una finestra Betfair a sé: è la scheda «📖 Dizionario» dentro l'hub
> **🧰 Strumenti** (`tools_gui.py`), alimentata da `betfair/dictionary_viewer_gui.py`. La tabella §2
> resta come **mappa storica** della migrazione colori di `app.py` (i suoi numeri di riga sono quelli
> della vecchia `app.py` pre-migrazione, tenuti solo come provenienza).

---

## 1. Modulo tema (nuovo file `xtrader_bridge/ui_theme.py`)

CustomTkinter accetta per ogni proprietà colore o un singolo valore o la coppia
`[light, dark]`. Centralizzare evita i ~20 HEX sparsi oggi in `app.py`.

```python
# xtrader_bridge/ui_theme.py — palette unica (design system v1). [dark, light] dove serve.
# Semantica di sicurezza BLOCCATA (§13 handoff): non rimappare questi ruoli.

# Superfici (CTk usa [light, dark] internamente; qui esposte esplicite)
WIN        = ("#eef1f7", "#0e131c")   # sfondo finestra
TITLEBAR   = ("#e4e9f1", "#0b0f17")   # barra titolo / testa tab
SURFACE    = ("#ffffff", "#131a25")   # card / pannelli
SURFACE2   = ("#f4f7fb", "#19212f")
SURFACE3   = ("#eaeff6", "#212b3c")   # bottone secondario
BORDER     = ("#d6ddea", "#28313f")

TEXT       = ("#172234", "#e7edf5")
TEXT2      = ("#586376", "#93a1b4")
TEXT3      = ("#8895a7", "#5d6a7b")

# Semantici — significato di sicurezza (NON decorativi)
ACCENT     = ("#2563eb", "#3d8bff")   # primario / info / focus
ACCENT_HOV = ("#1d4ed8", "#2f6fd0")
SUCCESS    = ("#0ca678", "#2bcf86")   # AVVIA / ATTIVO / OK
SUCCESS_HOV= ("#09835f", "#22a86c")
DANGER     = ("#e03546", "#ff5468")   # STOP / REALE / distruttivo
DANGER_HOV = ("#b81f2f", "#d83a4c")
WARN       = ("#dc8a06", "#ffb02e")   # riconnessione / scarti / CSV bloccato
INFO       = ("#0e9bd6", "#38bdf8")   # etichette locale/read-only
PURPLE     = ("#6d4aff", "#7c5cff")   # Strumenti / Wizard
PURPLE_HOV = ("#5a37e0", "#684ae0")
TEAL       = ("#0d9488", "#12a594")   # Wizard prima configurazione
TEAL_HOV   = ("#0b7c72", "#0f8b7d")

# Testo di STATO su superficie chiara — WCAG-safe (aggiunto in PR-1). I colori-brand chiari
# sopra vanno bene come RIEMPIMENTO (testo bianco sopra: bottoni/badge), ma come TESTO su
# header chiaro scendono sotto la soglia WCAG: questi usano il valore design nel dark e una
# variante chiara più scura. Semantica invariata (verde=ok, rosso=errore, arancio=warn).
TITLE_TEXT  = ("#0d47a1", "#3d8bff")   # titolo app
STATUS_OK   = ("#0f7a52", "#2bcf86")   # ⬤ ATTIVO
STATUS_ERR  = ("#c62828", "#ff5468")   # ⬤ OFFLINE / errore
STATUS_WARN = ("#b5560a", "#ffb02e")   # ⬤ RICONNESSIONE / righe attive / warning chat

# Sfondi BANNER a testo bianco — rosso/arancio PROFONDI (leggibilità = invariante §13):
# il banner REALE NON usa il DANGER brillante dei bottoni (bianco su di esso < soglia WCAG).
DANGER_BANNER = ("#b71c1c", "#7f1d1d")  # banner MODALITÀ REALE
WARN_BANNER   = ("#e65100", "#8a4b00")  # banner COLLAUDO XTrader
WARN_WEAK     = ("#fff3cd", "#4d3f00")  # (PR-3) barra warning TENUE, testo scuro (non banner)

# Geometria
RADIUS_CTRL = 8    # bottoni, entry, dropdown
RADIUS_CARD = 10   # frame/card
RADIUS_WIN  = 13   # finestre/toplevel
H_CTRL      = 34   # altezza compatta controlli (36 = comfortable)
H_ACTION    = 40   # bottoni barra azioni

# Font (con fallback Windows)
FONT_UI   = "Segoe UI"     # design: Hanken Grotesk
FONT_MONO = "Consolas"     # design: IBM Plex Mono
```

**Setup globale** — sostituisci (`app.py:93-94`):

```python
# PRIMA
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# DOPO — dark di default, ma commutabile (toggle richiesto dal §15.1)
ctk.set_appearance_mode("dark")          # o "system"; toggle via set_appearance_mode("light"/"dark")
ctk.set_default_color_theme("blue")       # base; gli accent li impostiamo esplicitamente dai token
```

> **Toggle tema.** CTk cambia dark/chiaro con `ctk.set_appearance_mode(...)`. Poiché i token
> sono coppie `[light, dark]`, i widget che li usano seguono il tema senza codice extra.
> Aggiungere un CTkSwitch nell'header (o in Sicurezza) che chiama `set_appearance_mode`.

---

## 2. Migrazione colori — HEX (storici) → token

> **Mappa storica — già applicata in `app.py`.** Questa tabella documenta la migrazione colori di
> `app.py` così com'era **prima** del refactor: i numeri di riga si riferiscono alla vecchia `app.py`
> e restano solo come provenienza. Nel codice attuale ogni pulsante usa già i token via gli alias
> `_COLOR_*` (`app.py` ~240-248) e `ui_theme.*` (es. AVVIA=`SUCCESS`, STOP=`DANGER`, Svuota CSV=`ACCENT`,
> Strumenti=`PURPLE`, Wizard=`TEAL`). Nessun HEX grezzo va più sostituito qui.

| Dove (file:riga, vecchia app.py) | Elemento | HEX (storico) | → Token |
|---|---|---|---|
| app.py:590 | Header frame | `#1a1a2e` | `SURFACE` (o `TITLEBAR`) |
| app.py:611 | Banner REALE (bg) | `#7f1d1d` | `DANGER` |
| app.py:697-699 | AVVIA | `#2e7d32` / hover `#1b5e20` | `SUCCESS` / `SUCCESS_HOV` |
| app.py:704-706 | STOP | `#c62828` / hover `#7f0000` | `DANGER` / `DANGER_HOV` |
| app.py:717-719 | Salva Config | `#37474f` / hover `#263238` | `SURFACE3` + `BORDER` (secondario) |
| app.py:728-730 | Strumenti | `#4527a0` / hover `#311b92` | `PURPLE` / `PURPLE_HOV` |
| app.py:762-770 | Copia diagnostica / Apri log / Esporta audit | `#37474f`/`#263238` | `SURFACE3` (secondari) |
| app.py:815-817 | Svuota log | `#37474f`/`#263238` | `SURFACE3` |

> Il pulsante **Svuota CSV** — richiesto **primario blu** dal design — usa già
> `fg_color=ACCENT, hover_color=ACCENT_HOV` nel codice attuale (`app.py:1342-1344`). Voce risolta.

---

## 3. Spec widget-per-widget

| Componente design | Widget CTk | Proprietà chiave | Fattibilità |
|---|---|---|---|
| Bottone primario | `CTkButton` | `fg_color=ACCENT, hover_color=ACCENT_HOV, corner_radius=8, height=40` | ✔ nativo |
| Bottone AVVIA/STOP | `CTkButton` | `SUCCESS`/`DANGER`; STOP parte `state="disabled"` | ✔ nativo |
| Bottone secondario | `CTkButton` | `fg_color=SURFACE3, hover_color=BORDER, text_color=TEXT` | ✔ nativo |
| Bottone pericolo | `CTkButton` | `fg_color=DANGER, hover_color=DANGER_HOV` | ✔ nativo |
| Campo testo / token | `CTkEntry` | `corner_radius=8, height=34`; token `show="●"` | ✔ nativo |
| Dropdown | `CTkOptionMenu` | `fg_color=SURFACE, button_color=SURFACE3` | ✔ nativo |
| Checkbox | `CTkCheckBox` | `fg_color=ACCENT` | ✔ nativo |
| Badge di stato | `CTkLabel` | `fg_color=<sem>_weak, text_color=<sem>, corner_radius=20` | ✔ nativo |
| Banner | `CTkFrame`+`CTkLabel` | REALE persistente (§13) | ✔ nativo |
| Tab a workflow numerato | `CTkSegmentedButton` o barra `CTkButton` | `CTkTabview` ha look diverso | ◐ adattato |
| Griglia/tabella densa | griglia `CTkLabel/CTkEntry` in `CTkScrollableFrame` | nessun DataGrid nativo | ◐ adattato |
| Cornice rossa finestra REALE | `border_color=DANGER, border_width=3` sul frame radice | + banner esistente | ◐ adattato |
| Dialogo conferma "REALE" | `CTkInputDialog` o `CTkToplevel` custom | copy §9 invariata | ◐ adattato |

**Nota transitoria (icone):** i mockup usano icone SVG a tratto. Nel codice attuale i controlli
usano emoji (▶ ■ 🗑️ 💾 🧰). Per allinearsi al look pulito del design, valutare un set di
PNG/ICO monocromatici caricati via `CTkImage` — è ◐ adattato, opzionale.

---

## 4. Mappa schermata → file:widget

> Riferimenti allineati all'`app.py` corrente (~4200 righe). I numeri possono spostarsi di poche
> righe a ogni patch: usa gli **àncora simbolici** (nomi di metodo/label) come guida primaria.

| Schermata (mockup) | File | Punto di ancoraggio |
|---|---|---|
| Finestra principale, header + banner REALE | `app.py` | `_build_ui` :1176 · header `hdr` :1178 · titolo :1181 · banner `_real_banner` :1207-1208 |
| Barra azioni AVVIA/STOP/Svuota/Salva | `app.py` | `btn_frame` :1324 → AVVIA :1328 · STOP :1335 · Svuota CSV :1343 · Salva Config :1349 |
| Barra Strumenti/Wizard | `app.py` | `tools_frame` :1357 → 🧰 Strumenti :1360 · 🧙 Wizard :1365 |
| Tab config — 4 tab (⚙️ Generale / 🎯 Riconoscimento / 🛡️ Sicurezza / ✅ Conferme XTrader) | `app.py` | `CTkTabview` :1220 · `add()` :1226-1229 |
| Tab monitor — 6 tab (📡 Chat ascoltate / 🚦 Salute / 📡 Stato / 📊 Dashboard / 📋 Log / 🤖 Assistente) | `app.py` | `CTkTabview` `mon` :1377 · `add()` :1379-1384 |
| **Parser Personalizzato** (priorità §7.1) | `custom_parser_gui.py` | intera finestra |
| **🧰 Strumenti** (hub a schede: Sorgenti/Provider/Parser/Mapping/Dizionario/Diario/Nomi squadra/Profili/Riepilogo) | `tools_gui.py` | `ToolsWindow` + `build_tool_panels` (9 pannelli, gruppi ①-④) |
| Scheda «📖 Dizionario» (dentro l'hub Strumenti) | `betfair/dictionary_viewer_gui.py` | pannello dizionario |

> **Nota storica:** la tab «Betfair Sync» (`betfair/sync_tab_gui.py`) è stata **rimossa** e non è più
> nella mappa. Il Dizionario **non** è più una finestra Betfair a sé: è una scheda dell'hub Strumenti.

Ordine consigliato: (1) `ui_theme.py` + setup, (2) barra azioni e header di `app.py`
(massima resa visiva), (3) tab config/monitor, (4) `custom_parser_gui.py` (la più densa).

---

## 5. i18n — leggere prima di toccare le label

Le label italiane **sono le chiavi** di traduzione (value-as-key): cambiare il testo di una
label impatta i cataloghi EN/ES. Questo kit **non cambia label**: rimappa solo colori/geometria.
Se durante l'integrazione una label va cambiata:
1. segnalalo esplicitamente nella PR;
2. aggiorna le chiavi nei cataloghi EN/ES;
3. mantieni invariata la copy dei gate di sicurezza §9 (es. la parola **REALE**).

---

## 6. Checklist invarianti (§13) — nessuna patch deve violarle

- [ ] Reale vs simulazione sempre inequivocabile (banner + cornice rossa 3px).
- [ ] Attivazione reale con parola digitata «REALE» — non un toggle immediato.
- [ ] Multi-segnale con conferma esplicita Sì/No.
- [ ] AVVIA bloccato senza chat configurata.
- [ ] Default OVERWRITE_LAST + indicatore Righe attive N/M.
- [ ] Token mai in chiaro; testo messaggi non loggato di default.
- [ ] STOP e chiusura fermano davvero il bridge.
- [ ] Errori parlanti; nessuna puntata automatica (solo scrittura CSV).
