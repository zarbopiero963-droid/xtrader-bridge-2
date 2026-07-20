# XTrader Signal Bridge — Kit di integrazione (design → CustomTkinter)

> **Cos'è.** Un deliverable **di design**: fa da ponte 1:1 tra i mockup HTML e il codice
> CustomTkinter esistente. Contiene i valori pronti (colori, dimensioni, mappa widget) così
> l'applicazione delle patch è meccanica. **Non modifica il codice dell'app**: il merge resta
> manuale del proprietario (vincolo del brief). Riferimenti al design: `XTrader Design System.dc.html`,
> `XTrader States Mockup.dc.html`, prototipo `XTrader Bridge.dc.html`.

---

## 0. Come usarlo

1. Aggiungi un modulo tema centralizzato (§1) — un solo punto di verità per i colori.
2. Sostituisci gli HEX hardcoded con le costanti (tabella §2, con file:riga attuali).
3. Applica lo spec widget-per-widget (§3) e la mappa schermata→file (§4).
4. Prima di toccare label visibili, leggi la nota i18n (§5).

Tutti gli HEX qui sono verificati contro il codice attuale (`git grep` di `fg_color`) e contro il design system.

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

**Setup globale** — sostituisci (`app.py:65-66`):

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

## 2. Migrazione colori — HEX attuali → token

| Dove (file:riga) | Elemento | HEX attuale | → Token |
|---|---|---|---|
| app.py:590 | Header frame | `#1a1a2e` | `SURFACE` (o `TITLEBAR`) |
| app.py:611 | Banner REALE (bg) | `#7f1d1d` | `DANGER` |
| app.py:697-699 | AVVIA | `#2e7d32` / hover `#1b5e20` | `SUCCESS` / `SUCCESS_HOV` |
| app.py:704-706 | STOP | `#c62828` / hover `#7f0000` | `DANGER` / `DANGER_HOV` |
| app.py:717-719 | Salva Config | `#37474f` / hover `#263238` | `SURFACE3` + `BORDER` (secondario) |
| app.py:728-730 | Strumenti | `#4527a0` / hover `#311b92` | `PURPLE` / `PURPLE_HOV` |
| app.py:762-770 | Copia diagnostica / Apri log / Esporta audit | `#37474f`/`#263238` | `SURFACE3` (secondari) |
| app.py:815-817 | Svuota log | `#37474f`/`#263238` | `SURFACE3` |

> Il pulsante **Svuota CSV** (app.py:712) oggi non ha `fg_color` → eredita il blu tema.
> Nel design è **primario blu**: impostare `fg_color=ACCENT, hover_color=ACCENT_HOV`.

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

| Schermata (mockup) | File | Punto di ancoraggio |
|---|---|---|
| Finestra principale, header + banner REALE | `app.py` | `_build_ui` :588 · header :590 · banner :610 |
| Barra azioni AVVIA/STOP/Svuota/Salva/Strumenti | `app.py` | :694-731 |
| Tab config (Generale/Riconoscimento/Sicurezza/Conferme) | `app.py` | `CTkTabview` :617-692 |
| Monitor (Chat/Stato/Dashboard/Log + Salute) | `app.py` | `CTkTabview` :741-820 |
| **Parser Personalizzato** (priorità §7.1) | `custom_parser_gui.py` | intera finestra |
| Betfair Sync | `betfair/sync_tab_gui.py` | intera tab |
| Dizionario Betfair | `betfair/dictionary_viewer_gui.py` | intera finestra |

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
