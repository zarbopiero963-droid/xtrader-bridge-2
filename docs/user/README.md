# Guide utente — XTrader Signal Bridge

Guide pensate per **chi usa** il bridge (non per chi lo sviluppa). Spiegano in linguaggio semplice
come configurarlo e usarlo in sicurezza.

## Indice

- **[Primi passi](getting_started.md)** — dalla prima apertura al primo AVVIA in Simulazione: lingua,
  token/chat/CSV, il Wizard di prima configurazione, START/STOP e il passaggio (solo se vuoi) alla
  modalità reale.
- **[Assistente di configurazione (🤖)](assistente.md)** — la chat che ti aiuta a configurare il
  bridge: cosa manca per partire, cosa può proporre (con la tua conferma) e cosa non può fare.

## Principi di sicurezza (validi sempre)

- Il bridge parte in **Simulazione**: il CSV operativo **non** viene scritto finché non passi tu, con
  conferma esplicita, a modalità reale (tab **🛡️ Sicurezza**).
- La **API key** dell'assistente sta **solo nel keyring** del sistema; il **bot token** sta nel keyring
  (con fallback in chiaro **solo** se manca un keyring, e con avviso nel log).
- Il bridge ascolta **solo** le chat che configuri; il CSV contiene **solo** il segnale attivo previsto
  e viene **svuotato** dopo il timeout.

## Documentazione tecnica (per sviluppatori)

- [`docs/custom_parser.md`](../custom_parser.md) — il Parser Personalizzato.
- [`docs/xtrader_csv_contract.md`](../xtrader_csv_contract.md) — il contratto del CSV per XTrader.
- [`docs/internal/config_agent.md`](../internal/config_agent.md) — architettura dell'assistente (#41).

> 📸 Gli **screenshot** delle guide vanno in [`docs/assets/screenshots/`](../assets/screenshots/) e
> vanno catturati su Windows (l'app è Windows-first). Finché non ci sono, le guide usano segnaposto
> «\[screenshot: …\]».
