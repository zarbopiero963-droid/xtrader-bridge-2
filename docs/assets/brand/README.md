# BetRelay — pacchetto brand (logo & icona)

Direzione scelta dal proprietario: **D1 — Trasmettitore** (nodo che trasmette, onde,
barra ricevente). Stessa grafica per **icona dell'app** e **logo**, come richiesto.

## Colori

| Ruolo | Hex | Note |
|---|---|---|
| Sfondo icona | `#1a1a2e` | identico all'header dell'app e del sito |
| Trasmettitore + onde | `#4fc3f7` | ciano del brand (titolo app, link sito) |
| Barra ricevente | `#ffb74d` | ambra (stessa famiglia di «Righe attive») |
| Testo lockup (scuro) | `#e8ecf3` + `#4fc3f7` | «Bet» chiaro, «Relay» ciano |
| Testo lockup (chiaro) | `#16324a` + `#0d7fc0` | versione per fondi chiari |

## File

```text
svg/
  betrelay-icon.svg          icona completa (arte piena) — sorgente principale
  betrelay-icon-32.svg       arte semplificata per 32 px (una sola onda)
  betrelay-icon-16.svg       arte semplificata per 16/24 px (masse più grandi)
  betrelay-mark.svg          solo marchio, sfondo trasparente
  betrelay-mono.svg          monocromatico (usa `currentColor`) per stampa/1 colore
  betrelay-lockup.svg        icona + «BetRelay» (fondo scuro)
  betrelay-lockup-light.svg  icona + «BetRelay» (fondo chiaro)
png/
  betrelay-{16,24,32,48,64,128,256,512}.png    icona con sfondo
  betrelay-mark-{128,256,512}.png              marchio trasparente
  betrelay-lockup-{520,1040}.png               lockup scuro
  betrelay-lockup-light-{520,1040}.png         lockup chiaro
ico/
  betrelay.ico    multi-taglia 16/24/32/48/64/128/256 — per l'EXE Windows
  favicon.ico     16/32/48 — per il sito
```

## Perché tre varianti di arte

A 16 px i dettagli spariscono: la seconda onda diventa una macchia. Perciò le taglie
piccole usano una versione **semplificata** (meno elementi, tratti più spessi) — è la
prassi delle icone di sistema. Il `.ico` incorpora l'arte giusta per ogni taglia, non
un semplice ridimensionamento.

## Uso

- **EXE Windows:** `ico/betrelay.ico` (PyInstaller: `--icon=...`; Nuitka:
  `--windows-icon-from-ico=...`). Vedi issue #232, Strato 1 del rebrand.
- **Finestra dell'app:** `png/betrelay-64.png` (Tk `iconphoto`) o l'`.ico` (`iconbitmap`
  su Windows).
- **Sito:** `ico/favicon.ico` + `png/betrelay-256.png` come icona social; nella nav il
  lockup o l'icona da sola al posto dell'emoji 📡.
- **Avatar (Telegram/social):** `png/betrelay-512.png`.

## Regole minime

- Non ricolorare il marchio fuori dalla palette qui sopra (la coppia ciano→ambra è ciò
  che lo rende leggibile in piccolo).
- Non aggiungere ombre o effetti: l'icona deve restare piatta.
- Spazio libero attorno al marchio: almeno quanto il diametro del nodo ciano.
- Su fondi chiari usare `betrelay-lockup-light.svg` (il quadrotto scuro resta invariato).

## Come rigenerare

I PNG sono ridotti con Pillow (LANCZOS) da render a 1024 px degli SVG (Chromium
headless non scende sotto una dimensione minima di finestra: renderizzare
direttamente a 16/32 px produce immagini vuote). L'`.ico` è costruito impacchettando
i PNG per-taglia con payload PNG (supportato da Windows Vista+).
