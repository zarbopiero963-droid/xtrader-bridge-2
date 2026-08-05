# Roadmap del sito BetRelay — cosa manca, in ordine

Stato al commit `58905c1`. Capitolato originale: issue **#229**.
Questo documento è la vista **operativa**: cosa resta da fare, perché, e chi lo fa.

> ⚠️ **Distinzione importante.** Le voci marcate 👤 richiedono una **decisione o un'azione del
> proprietario** (registrazioni, credenziali, contenuti da validare, verifiche legali). Le altre
> le può fare l'agente. Nessuna voce 👤 va «risolta» dall'agente tirando a indovinare.

---

## 🔴 Prima di pubblicare — non opzionali

### S1. Pagina privacy 👤 (bozza dell'agente, contenuti da validare)
Il **chatbot invia i messaggi degli utenti all'API di Anthropic** e il **form contatti raccoglie
email**. Oggi il sito non lo dichiara da nessuna parte.

Deve dire almeno: quali dati si raccolgono (testo dei messaggi, email del form, IP per il rate
limit), a chi vanno (Anthropic come responsabile del trattamento, il provider email), per quanto
si conservano, e come si esercitano i diritti. Serve anche il titolare del trattamento — cioè
dati che solo il proprietario può fornire.

Nota tecnica utile per il testo: il rate limit tiene gli IP **in memoria di processo** (`_hits`
in `website/main.py`), quindi si azzerano al riavvio; non c'è database, non c'è profilazione,
non ci sono cookie di tracciamento (solo `localStorage` per la lingua scelta).

### S2. Gioco responsabile / 18+ 👤 — e una verifica legale
Il sito parla di software di scommesse e **non ha una riga in merito**. Va aggiunto un richiamo
18+ e al gioco responsabile, con i riferimenti giusti per il paese.

⚠️ **Da verificare con un professionista prima di pubblicare su dominio italiano**: il
cosiddetto *decreto Dignità* vieta la pubblicità di giochi con vincite in denaro. BetRelay è uno
strumento tecnico e non un operatore di gioco, e la distinzione probabilmente lo colloca fuori
dal divieto — ma «probabilmente» non basta su una materia sanzionabile, e **non è una valutazione
che l'agente possa dare**. Va chiesto a chi di competenza.

Se la risposta fosse restrittiva, le conseguenze toccano il posizionamento del sito, non il
software: il bridge resta un tool per file CSV.

### S3. Contatti veri ✅ indirizzo messo · resta il backend
L'indirizzo del proprietario è in `static/contatti.html`, **spezzato nel sorgente** e ricomposto
in JavaScript: nell'HTML servito la forma `nome@dominio` non compare, quindi i raccoglitori
automatici non la trovano. Non è cifratura — chi apre la pagina lo legge — ma evita la raccolta
di massa. Verificato guidando il form con un browser vero: il `mailto:` generato ha il
destinatario giusto e i caratteri speciali dei campi (`&`, `+`, `%`) correttamente codificati.

Resta da fare, quando il sito sarà pubblico: `/api/contact` con invio dal backend, così
l'indirizzo non passa più dal client dell'utente — e un anti-abuso, visto che sarebbe un
endpoint pubblico.

### S4. Deploy su Railway 👤 (setup) + agente (verifica)
Il sito **non è mai stato visto online**: tutto ciò che è stato verificato gira in locale.
Servono: account Railway, **Root Directory = `website`** (obbligatorio: il Dockerfile sta lì e le
sue `COPY` sono relative a quella cartella), `ANTHROPIC_API_KEY` fra le Variables, dominio
generato.

L'immagine è già preparata per stare su internet: `.dockerignore` tiene fuori segreti e cache,
il processo gira come utente non privilegiato, le dipendenze sono pinnate e la porta ha un
default anche se `PORT` arriva vuota (test: `tests/unit/test_website_deploy.py`). **Non è mai
stata costruita**: Docker non è disponibile nell'ambiente agente, quindi il primo build di
Railway è anche la prima verifica reale.

La verifica poi la faccio io: `python3 tools/e2e/check_site.py --base-url https://<dominio>`
apre il sito con un browser vero e prova pagine, demo, chatbot, favicon e footer (S13).
Quello che **non** posso fare è entrare nel pannello Railway: setup, Variables e collegamento
del dominio restano azioni del proprietario, e la `ANTHROPIC_API_KEY` non deve passarmi mai
davanti.

### S5. Dominio 👤 — acquistato su Railway
Il proprietario ha comprato il dominio direttamente da Railway. Resta da collegarlo al
servizio e da attendere la propagazione DNS; poi va passato all'agente l'URL per il collaudo.

---

## 🟠 Contenuto che manca

### S6. Le tre sezioni per software
*BetRelay per XTrader* · *for BETTINGTOOLKIT.COM* · *para .ES / .LAT*.
Regole in [`policy_lingue_sito.md`](policy_lingue_sito.md).

Materiale: ✅ screenshot **BetRelay** in IT/EN/ES · ❌ screenshot **XTrader** in EN/ES (#266).

Il fallback previsto dalla [regola permanente](policy_lingue_sito.md) è **l'inglese, e solo
l'inglese**, dichiarato in pagina. Oggi gli inglesi non ci sono: le sezioni non-italiane
dipendono quindi da #266. Pubblicarle prima, con schermate italiane, è una decisione del
proprietario da dichiarare in pagina — non un ripiego che l'agente possa prendersi da solo.

### S7. La guida «Collegare BetRelay a XTrader» come pagina web
Il contenuto esiste già in [`xtrader_integration.md`](xtrader_integration.md); manca la pagina.
Oggi la card in `/documentazione` rimanda alla demo con la nota «in preparazione».

### S8. Traduzioni EN/ES mancanti
`guida-bot.html` e le due demo (`/demo`, `/demo/xtrader`) sono solo in italiano. Le pagine
principali sono già trilingui.

### S9. Wizard in EN/ES
Ho solo l'italiano. Generabili subito, un comando per lingua (in shell `|` aprirebbe una
pipe, non è un'alternativa):

```bash
python3 tools/screenshots/wizard_shot.py --lang en
python3 tools/screenshots/wizard_shot.py --lang es
```

Nessuna dipendenza esterna.

---

## 🟡 Tecnica e qualità

### S10. `paths-ignore: website/**` nei workflow
Oggi **ogni push al sito fa girare la CI del bridge**, runner Windows compresi (che costano il
doppio). È il risparmio più immediato disponibile e non tocca il codice del bridge.
Attenzione: i test del sito stanno in `tests/unit/`, quindi il filtro va scritto in modo che
**non** salti la suite quando cambiano quelli.

### S11. SEO e condivisione
Nessuna pagina ha `og:title` / `og:description` / `og:image`: un link condiviso su WhatsApp o
Telegram appare oggi senza anteprima. Mancano anche `robots.txt`, `sitemap.xml` e una **pagina
404**.

### S12. Chatbot mai provato con una API key vera
Verificato solo in modalità demo. Da provare: risposte reali sulla knowledge base, rifiuto del
fuori-tema, rate limit, comportamento in tre lingue.

### S13. Test end-to-end del sito ✅ fatto
[`tools/e2e/check_site.py`](../tools/e2e/check_site.py) ([README](../tools/e2e/README.md))
guida Chromium contro un URL qualsiasi —
locale o Railway — e verifica rotte, footer nelle tre lingue, errori JavaScript, asset, PDF,
404, selettore lingua, i flussi completi delle due demo e il chatbot. **57 controlli, exit code
0/1.** Verificato in locale: 57 PASS.

Sul dominio Railway va lanciato con `--base-url https://<dominio>`. Nell'ambiente agente il
browser richiede tre accorgimenti di rete documentati nel README (proxy come flag, CA nel trust
NSS, ClientHello post-quantum disattivato) — **senza mai** disattivare la verifica TLS.

---

## ⚪ Fuori dal sito, ma collegate

### S14. #269 — quattro stringhe in italiano nell'app EN/ES
Fra cui il **selettore Modalità bridge**. Finché non è risolta, gli screenshot EN/ES mostrano
interfaccia mista — è dichiarato nel README della cartella, ma resta un difetto del prodotto.

### S15. #232 — rebrand
L'app si chiama ancora «XTrader Signal Bridge» nel titolo e ha l'icona standard. Il sito dice
BetRelay, il programma no: chi scarica dopo aver visto il sito trova un nome diverso.

### S16. #266 — screenshot XTrader mancanti
Tre voci P1 dove il sito mostra oggi materiale ricostruito.

---

## Ordine consigliato

1. **S10** (`paths-ignore`) — poco lavoro, risparmia subito
2. **S1 + S2** (privacy, gioco responsabile) — bloccanti per la pubblicazione
3. **S4 + S5** (Railway, dominio) — vedere il sito vivo cambia le priorità successive; appena
   c'è l'URL, il collaudo con browser vero è già pronto (S13)
4. **S7 + S6** (guida e sezioni) — il contenuto che dà valore al sito
5. il resto

Le voci 👤 possono procedere in parallelo: non dipendono dall'agente.
