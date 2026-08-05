# Collaudo end-to-end del sito con un browser vero

`check_site.py` apre il sito con **Chromium** (Playwright), clicca, scorre, legge il DOM e
salva screenshot. Serve a verificare quello che i test unitari non possono vedere: che le
pagine rispondano davvero, che il JavaScript non esploda nel browser, che i flussi delle due
demo arrivino in fondo e che il footer di non-affiliazione sia **a schermo**, non solo nel
sorgente.

Funziona contro qualsiasi URL: locale o produzione.

```bash
# 1. il sito in piedi
cd website && python3 -m uvicorn main:app --host 127.0.0.1 --port 8010 &

# 2. il collaudo
python3 tools/e2e/check_site.py --base-url http://127.0.0.1:8010 --out /tmp/shots

# in produzione, quando il dominio Railway sarà attivo
python3 tools/e2e/check_site.py --base-url https://<dominio> --out /tmp/shots
```

Exit code **0** = tutto verde, **1** = almeno un controllo rosso (l'elenco dei falliti è
stampato in fondo). `--skip-chat` salta il chatbot: utile in produzione con una API key vera,
dove ogni prova costa.

## Cosa controlla (57 controlli oggi)

| Area | Controlli |
|---|---|
| Rotte | le 7 pagine di `_PAGES` → HTTP 200, titolo non vuoto, screenshot |
| Footer | clausola di non-affiliazione presente **e completa** su ogni pagina, in IT/EN/ES |
| JavaScript | nessun errore in console né eccezione, su ogni pagina e durante i flussi |
| Endpoint | `/api/health`, `/favicon.ico`, il PDF della guida XTrader (header `%PDF-`), 404 su rotta inesistente |
| Asset | ogni `img`/`script`/`stylesheet` della home risponde < 400 |
| Lingue | i tre pulsanti IT/EN/ES cambiano lingua, e la scelta sopravvive al reload |
| Demo BetRelay | AVVIA → stato ATTIVO → segnale di prova contato → STOP → OFFLINE |
| Demo XTrader | le 3 schede, creazione fonte, segnale **valido** (verde), **non valido** (rosso), spiegazione, svuotamento del CSV allo scadere del timeout |
| Chatbot | il pannello si apre, la domanda riceve una risposta nel merito |

La logica pura (clausola del disclaimer, flag del browser, allineamento delle rotte con
`website/main.py`) è coperta da `tests/unit/test_e2e_check_site.py`, che gira nella suite
normale senza bisogno di un browser.

## Ambiente agente: le tre cose che lo bloccano

Chromium **non** eredita la configurazione di rete dell'ambiente come fa `curl`. Senza questi
tre accorgimenti non esce affatto, e l'errore (`ERR_CONNECTION_RESET`) non dice perché:

1. **Il proxy va passato come flag** — `--proxy-server=$HTTPS_PROXY`. Lo script lo fa da solo
   quando l'URL non è locale.
2. **La CA del proxy va nel trust NSS del browser**, una volta per macchina:
   ```bash
   apt-get install -y libnss3-tools
   certutil -d sql:$HOME/.pki/nssdb -A -t "C,," -n ccr-agent-proxy -i /root/.ccr/agent-proxy-ca.crt
   ```
   Senza questo: `ERR_CERT_AUTHORITY_INVALID`.
3. **Il ClientHello post-quantum di Chromium fa resettare la connessione dal tunnel**: si
   disattiva con `--disable-features=PostQuantumKyber` + `--ssl-version-max=tls1.2`.

⚠️ Quello che **non** si fa: `--ignore-certificate-errors` / `ignore_https_errors`. Un
certificato non valido in produzione è proprio ciò che il collaudo deve scoprire, e un test
verifica che quei due interruttori non compaiano nello script.

## Limiti dichiarati

- **Non testa Windows, il bridge o XTrader**: naviga un sito e basta.
- Le demo sono simulazioni: qui si verifica che la simulazione funzioni, non il comportamento
  reale del bridge (quello sta nella suite del bridge).
- Il chatbot in locale risponde in **modalità demo** (senza API key): il collaudo verifica il
  flusso, non la qualità delle risposte del modello.
- Il browser headless si dichiara `en-US`; lo script forza `locale="it-IT"` per esercitare il
  testo scritto nel markup, e passa dal selettore per le altre due lingue.
