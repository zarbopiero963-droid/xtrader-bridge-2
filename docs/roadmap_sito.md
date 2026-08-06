# Roadmap del sito BetRelay — cosa manca, in ordine

Stato al commit `58905c1`. Capitolato originale: issue **#229**.
Questo documento è la vista **operativa**: cosa resta da fare, perché, e chi lo fa.

> ⚠️ **Distinzione importante.** Le voci marcate 👤 richiedono una **decisione o un'azione del
> proprietario** (registrazioni, credenziali, contenuti da validare, verifiche legali). Le altre
> le può fare l'agente. Nessuna voce 👤 va «risolta» dall'agente tirando a indovinare.

---

## 🔴 Prima di pubblicare — non opzionali

### S1. Pagina privacy ✅ scritta · ⚠️ un dato da completare
La pagina è online su `/privacy`, trilingue, linkata dal footer di ogni pagina. Descrive i
quattro flussi reali verificati nel codice: i messaggi del chatbot inoltrati ad **Anthropic**,
il form contatti che **non invia nulla al sito** (apre il client dell'utente), l'**IP** tenuto
in memoria per il rate limit e cancellato dopo un'ora, e la lingua in `localStorage`. Dice
anche, esplicitamente, che il **programma** non manda niente a noi.

La pagina dichiara anche **finalità**, **tempi di conservazione** (chat: mai conservate; IP:
un'ora; email: finché serve alla richiesta) e il **trasferimento fuori dallo Spazio Economico
Europeo**, perché Anthropic è una società statunitense — un fatto che l'utente ha diritto di
sapere *prima* di scrivere nella chat.

La frase «le conversazioni non vengono salvate» **non è più solo una promessa scritta**:
[`test_website_chat_non_conserva.py`](../tests/unit/test_website_chat_non_conserva.py) la
verifica sul codice. Blocca un `logging`/`print` del messaggio, una globale che lo accumuli, un
errore che lo rimandi indietro, e — lato browser — `chat.js` che salvi la cronologia in
`localStorage`. Rilievo GPT-5.5 sulla #284: un claim privacy senza un test è vero solo finché
nessuno tocca il file. Resta fuori dal test ciò che non dipende da noi e che la pagina dichiara
per quello che è: i log di connessione di Railway e la ritenzione lato Anthropic.

⚠️ **Da chiudere col professionista**, due cose in una sola consulenza:

1. la **base giuridica** di ciascun trattamento (art. 13 GDPR). Le finalità sono descritte, ma
   qualificarle giuridicamente — legittimo interesse, consenso, esecuzione di un contratto — è
   una valutazione legale, non una scrittura tecnica: non l'ho inventata;
2. il **titolare del trattamento**, indicato come «**BetRelay**» per scelta del proprietario,
   che non vuole nome e cognome su una pagina pubblica. Il GDPR però vuole un soggetto identificabile — persona fisica o giuridica — perché
altrimenti non si sa a chi rivolgere una richiesta. È la **stessa consulenza** che serve per il
punto S2: una domanda sola, non due. La soluzione probabile è indicare la ditta/P.IVA quando
esisterà, così il nome personale non compare comunque.

<details><summary>Testo originale del punto (prima che fosse scritta)</summary>
Il **chatbot invia i messaggi degli utenti all'API di Anthropic** e il **form contatti raccoglie
email**. Oggi il sito non lo dichiara da nessuna parte.

Deve dire almeno: quali dati si raccolgono (testo dei messaggi, email del form, IP per il rate
limit), a chi vanno (Anthropic come responsabile del trattamento, il provider email), per quanto
si conservano, e come si esercitano i diritti. Serve anche il titolare del trattamento — cioè
dati che solo il proprietario può fornire.

Nota tecnica utile per il testo: il rate limit tiene gli IP **in memoria di processo** (`_hits`
in `website/main.py`), quindi si azzerano al riavvio; non c'è database, non c'è profilazione,
non ci sono cookie di tracciamento (solo `localStorage` per la lingua scelta).

</details>

### S2. Gioco responsabile / 18+ ✅ fatto · ⚠️ resta la verifica legale
Pagina dedicata `/gioco-responsabile` (trilingue) **più** il richiamo `18+ · Gioca
responsabilmente` nel footer di **ogni** pagina, demo comprese. La pagina dice cosa BetRelay
non fa (non piazza scommesse, non dà pronostici, **non fa vincere**), che l'automazione non
riduce il rischio ma lo **accelera**, i segnali di allarme della dipendenza, e i recapiti di
aiuto reali: Telefono Verde ISS **800 558822**, Ser.D., Giocatori Anonimi, GamCare e la linea
spagnola. Un test verifica che quei recapiti restino identici in tutte e tre le lingue.

⚠️ **La verifica legale resta aperta** — vedi sotto.

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

### S4. Deploy su Railway ✅ ONLINE
Il sito è pubblicato su **https://betrelay.net** e collaudato dal vivo: `check_site.py` contro
il dominio reale ha dato **65 controlli, 65 PASS**. `http://` reindirizza a `https://`.
Configurazione applicata: Root Directory `website`, Builder `Dockerfile`, Watch Paths
`/website/**` (così un push che non tocca il sito non ricostruisce nulla).

Resta da fare: `www.betrelay.net` **non risponde** — va aggiunto come dominio separato in
Railway se lo si vuole; e la `ANTHROPIC_API_KEY` fra le Variables per far uscire il chatbot
dalla modalità demo.

<details><summary>Requisiti originali del deploy (per riferimento)</summary>
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
</details>

### S5. Dominio ✅ collegato
`betrelay.net` è attivo e serve il sito.

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

### S17. Guida «API key Anthropic» ✅ scritta e illustrata · ⏳ manca una sola schermata
Pagina `/guida/api-key-anthropic`, trilingue, linkata da `/documentazione`. Nasce dalla decisione
del 6 agosto: **l'assistente 🤖 va a chi ha il bridge**, non resta strumento del solo proprietario
— quindi ogni utente deve procurarsi una API key Anthropic propria e sapere quanto costa.

Verificato invece che scritto a memoria: la Console **non è più** `console.anthropic.com`, che
oggi risponde `301` verso **`platform.claude.com`**. Le chiavi stanno su
`platform.claude.com/settings/keys`. Una guida scritta a ricordo avrebbe mandato l'utente su un
indirizzo che rimbalza, con screenshot che non combaciano col testo.

La pagina insiste su tre cose che costano soldi o tempo se taciute: che **non è l'abbonamento a
Claude** (si pagherebbe due volte), che **senza credito la chiave non funziona** — errore
`credit balance is too low`, capitato ai reviewer di questo stesso repository — e che la chiave
è **una password che spende**, con la revoca spiegata.

**Le schermate della Console ci sono**: otto, fornite dal proprietario il 6 agosto — io non potevo
farle, la Console è dietro il login e ricostruirla sarebbe fabbricare schermate (§2 della
[policy lingue](policy_lingue_sito.md)). Sono state **oscurate** prima di entrare nel repository:
nome, email, prefissi delle chiavi, carta e cronologia acquisti. Una conteneva una **API key vera
in chiaro**, che il proprietario ha **revocato** — coprirla non sarebbe bastato, una chiave vista
resta spendibile finché è viva. Gli originali non sono mai entrati nel repository.

Le schermate mostrano che la Console **è tradotta** e segue la lingua del browser: quelle del
proprietario sono **in italiano**. La pagina lo dice in tutte e tre le lingue invece di far credere
che l'utente vedrà l'inglese.

⏳ **Manca una sola schermata**: il pannello **«🤖 Assistente» di BetRelay** del passo 6, l'unica
che richiede l'app in esecuzione. È in pagina come riquadro dichiarato.

Sui `.jpg` la guardia è solo automatica — **CodeRabbit esclude le immagini** (`!**/*.jpg`) e i due
reviewer forti saltano i binari — quindi due test le presidiano: lo `sha256` degli otto file
(gira sempre, `hashlib` è standard) e, dove Pillow c'è, i pixel dell'area che copriva la chiave.

### S8. Traduzioni EN/ES — ✅ guida bot fatta · ❌ restano le due demo
`guida-bot.html` è **trilingue** (Issue #287): selettore IT/EN/ES, `i18n.js` caricato — prima non
lo era, quindi i quattro `data-i18n` che il footer già aveva erano **morti** — e tutta la prosa
tradotta, comprese le didascalie.

Le etichette Telegram sono citate **verbatim** con la traduzione fra parentesi — «Amministratori»
(Administrators), «Aggiungi amministratore» (Add administrator): è il §3 della
[regola permanente](policy_lingue_sito.md), e tradurle avrebbe mandato l'utente a cercare a
schermo un pulsante inesistente. Un test unitario **e** un controllo del collaudo live lo
impediscono.

⚠️ **Sugli screenshot resta uno scostamento aperto, e non lo chiudo io.** Il §4 vorrebbe la
schermata *nella lingua richiesta*; queste sono catture **reali** dal telefono del proprietario e
esistono **solo in italiano**. Rifarle significa ricatturarle davvero (lavoro del proprietario),
ricostruirle sarebbe fabbricare schermate — cosa che il §2 vieta — e il ripiego inglese non
esiste. Quello che si poteva rispettare del §4 è stato fatto: **il ripiego non è silenzioso**, la
pagina dichiara in ogni lingua che le schermate sono italiane e che quella del passo 9 è una
ricostruzione. La decisione (ricatturare, oppure approvare l'eccezione) è del proprietario ed è
scritta in [`policy_lingue_sito.md` §9](policy_lingue_sito.md).

Restano **`/demo` e `/demo/xtrader`**. Non sono state fatte in questa PR, e il motivo è
tecnico: il loro testo non sta nel markup ma **dentro il JavaScript** delle simulazioni (~94
stringhe fra le due), quindi tradurle non è aggiungere `data-i18n` ma introdurre una lookup
lato JS e rendere il collaudo e2e consapevole della lingua — un lavoro a sé, con rischio di
rompere i flussi che oggi il collaudo verifica riga per riga.

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

### S13. Test end-to-end del sito ✅ fatto — e usato in produzione
[`tools/e2e/check_site.py`](../tools/e2e/check_site.py) ([README](../tools/e2e/README.md))
guida Chromium contro un URL qualsiasi —
locale o Railway — e verifica rotte, footer nelle tre lingue, errori JavaScript, asset, PDF,
404, selettore lingua, i flussi completi delle due demo e il chatbot. **57 controlli, exit code
0/1.** Verificato in locale e **sul dominio reale**: 65 PASS su 65.

Sul dominio Railway va lanciato con `--base-url https://<dominio>`. Nell'ambiente agente il
browser richiede tre accorgimenti di rete documentati nel README (proxy come flag, CA nel trust
NSS, ClientHello post-quantum disattivato) — **senza mai** disattivare la verifica TLS.

---

## ⚪ Fuori dal sito, ma collegate

### S14. #269 — quattro stringhe in italiano nell'app EN/ES
Fra cui il **selettore Modalità bridge**. Finché non è risolta, gli screenshot EN/ES mostrano
interfaccia mista — è dichiarato nel README della cartella, ma resta un difetto del prodotto.

### S15. #232 — rebrand · ✅ risolto per la parte del NOME (Strato 1)
Era: *«l'app si chiama ancora XTrader Signal Bridge nel titolo; il sito dice BetRelay, il
programma no: chi scarica dopo aver visto il sito trova un nome diverso»*.

Il nome ora combacia: titolo finestra **BetRelay**, header **«📡 BetRelay»**, eseguibile
`BetRelay.exe`. **Resta aperta l'icona**, ancora quella standard — e restano gli
screenshot da rigenerare, che mostrano il titolo vecchio (vedi il README della cartella).

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
