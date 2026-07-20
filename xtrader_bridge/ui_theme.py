"""Palette e token del tema UI — fonte UNICA dei colori/geometria (design system v1).

Redesign UI/UX (handoff di Claude-design, `docs/design/integration_kit.md`): centralizza
qui i ~20+ HEX prima sparsi nei moduli GUI, così il tema è coerente e commutabile
dark/chiaro in un solo punto. I valori derivano 1:1 dal design system verificato contro i
mockup (`docs/design/prototype/`).

**Modulo PURO** (nessun import customtkinter/tkinter): importabile headless e testabile in
CI. CustomTkinter accetta per ogni proprietà colore o un singolo valore o la coppia
`(light, dark)`; i token qui sono coppie `(light, dark)` — stessa convenzione già usata dal
codice — così i widget seguono il tema attivo senza codice extra.

**Semantica di sicurezza BLOCCATA (§13 handoff):** i ruoli semantici (SUCCESS=AVVIA/ATTIVO,
DANGER=STOP/REALE, WARN=riconnessione/scarti, ecc.) NON vanno rimappati: il colore È parte
del segnale di sicurezza. In particolare la distinzione reale/simulazione deve restare
inequivocabile — vedi i token `*_BANNER` qui sotto.
"""

# ── Superfici ────────────────────────────────────────────────────────────────
WIN         = ("#eef1f7", "#0e131c")   # sfondo finestra
TITLEBAR    = ("#e4e9f1", "#0b0f17")   # barra titolo / testa tab / header
SURFACE     = ("#ffffff", "#131a25")   # card / pannelli
SURFACE2    = ("#f4f7fb", "#19212f")
SURFACE3    = ("#eaeff6", "#212b3c")   # bottone secondario
BORDER      = ("#d6ddea", "#28313f")

# ── Testo ────────────────────────────────────────────────────────────────────
TEXT        = ("#172234", "#e7edf5")
TEXT2       = ("#586376", "#93a1b4")
TEXT3       = ("#8895a7", "#5d6a7b")

# ── Semantici — significato di SICUREZZA (non decorativi) ───────────────────
ACCENT      = ("#2563eb", "#3d8bff")   # primario / info / focus
ACCENT_HOV  = ("#1d4ed8", "#2f6fd0")
SUCCESS     = ("#0ca678", "#2bcf86")   # AVVIA / ATTIVO / OK
SUCCESS_HOV = ("#09835f", "#22a86c")
DANGER      = ("#e03546", "#ff5468")   # STOP / distruttivo (bottoni, semaforo)
DANGER_HOV  = ("#b81f2f", "#d83a4c")
WARN        = ("#dc8a06", "#ffb02e")   # riconnessione / scarti / righe attive / CSV bloccato
INFO        = ("#0e9bd6", "#38bdf8")   # etichette locale/read-only
PURPLE      = ("#6d4aff", "#7c5cff")   # Strumenti
PURPLE_HOV  = ("#5a37e0", "#684ae0")
TEAL        = ("#0d9488", "#12a594")   # Wizard prima configurazione
TEAL_HOV    = ("#0b7c72", "#0f8b7d")

# ── Testo di STATO su superficie (header/frame) — WCAG-safe in ENTRAMBI i temi ──
# I colori semantici brillanti sopra sono pensati come RIEMPIMENTO (testo bianco sopra:
# bottoni/badge). Usati invece come TESTO colorato su una superficie CHIARA (semafori di
# stato, righe attive, titolo) i valori-brand chiari scendono sotto la soglia WCAG di
# leggibilità (verificata da `tests/integration/test_palette.py`, ≥3.0). Perciò le versioni
# "testo" usano il valore design nel DARK (tema primario, resa piena) e una variante CHIARA
# più scura nel light. Semantica invariata (verde=ok, rosso=errore, arancio=warn).
TITLE_TEXT   = ("#0d47a1", "#3d8bff")   # titolo app (accent leggibile su header chiaro)
STATUS_OK    = ("#0f7a52", "#2bcf86")   # ⬤ ATTIVO
STATUS_ERR   = ("#c62828", "#ff5468")   # ⬤ OFFLINE / errore
STATUS_WARN  = ("#b5560a", "#ffb02e")   # ⬤ RICONNESSIONE / righe attive / warning chat

# ── Sfondi BANNER a testo bianco (invariante §13: leggibilità = sicurezza) ──
# I banner MODALITÀ REALE / COLLAUDO hanno testo BIANCO su fondo pieno esteso: richiedono un
# rosso/arancio PROFONDO per il contrasto (il `DANGER`/`WARN` brillante dei bottoni, con testo
# bianco su banner grande, scenderebbe sotto la soglia WCAG e INDEBOLIREBBE il segnale reale).
# Perciò gli sfondi-banner usano token dedicati e profondi — non `DANGER`/`WARN` diretti.
DANGER_BANNER = ("#b71c1c", "#7f1d1d")  # banner MODALITÀ REALE (testo bianco)
WARN_BANNER   = ("#e65100", "#8a4b00")  # banner COLLAUDO XTrader (testo bianco)

# ── Geometria ────────────────────────────────────────────────────────────────
RADIUS_CTRL = 8    # bottoni, entry, dropdown
RADIUS_CARD = 10   # frame / card
RADIUS_WIN  = 13   # finestre / toplevel
H_CTRL      = 34   # altezza compatta controlli
H_ACTION    = 40   # bottoni barra azioni

# ── Font (con fallback Windows) ─────────────────────────────────────────────
FONT_UI   = "Segoe UI"     # design: Hanken Grotesk
FONT_MONO = "Consolas"     # design: IBM Plex Mono
