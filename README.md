# 🤖 XTrader Signal Bridge

Converte automaticamente i segnali Telegram (formato P.Bet.) in CSV leggibili da XTrader.

## Come funziona

```
📱 Telegram → 🤖 Bridge → 📄 CSV → ⚙️ XTrader → 🎯 Scommessa piazzata
```

1. Il bridge riceve il messaggio Telegram dal tuo bot
2. Estrae squadre, mercato e quota
3. Scrive il CSV nel formato XTrader
4. Dopo N secondi svuota il CSV (pronto per il prossimo segnale)

## Configurazione

All'avvio dell'app inserisci:

| Campo | Descrizione | Esempio |
|-------|-------------|---------|
| Bot Token | Token del tuo bot Telegram | `123456:AAF...` |
| Chat ID | ID del canale/gruppo sorgente | `-1001234567890` |
| CSV Path | Percorso CSV letto da XTrader | `C:\XTrader\segnali.csv` |
| Timeout | Secondi prima di svuotare il CSV | `90` |
| Provider | Nome provider in XTrader | `TelegramBot` |

## Come trovare il Chat ID

1. Aggiungi il tuo bot al canale/gruppo come amministratore
2. Invia un messaggio nel canale
3. Vai su: `https://api.telegram.org/bot<TOKEN>/getUpdates`
4. Cerca il campo `"chat":{"id":...}` — quello è il tuo Chat ID

## Build EXE

Il file `.github/workflows/build.yml` compila automaticamente l'EXE su GitHub Actions
ad ogni push su `main`. Scarica l'artifact dalla tab **Actions** del tuo repository.

Per creare una Release pubblica, crea un tag:
```
git tag v1.0.0
git push origin v1.0.0
```
