/* i18n del sito — IT (default nel markup) + EN + ES.
   Auto-riconoscimento: lingua salvata > lingua del browser (it/es → quella, altro → en). */
(function () {
  "use strict";

  var T = {
    en: {
      "nav.home": "Home", "nav.demo": "Interactive demo", "nav.faq": "FAQ", "nav.contact": "Contact",
      "home.h1": "Your Telegram channel's signals, <em>inside your betting software</em>. Automatically.",
      "home.lead": "The bridge reads messages from the chat you choose, translates them with a custom parser into the CSV your software monitors, and clears the file after the timeout. Configure once; the chain works on its own.",
      "home.cta.demo": "▶ Try the interactive demo", "home.cta.faq": "Read the FAQ",
      "home.sec1": "Why it's not a betting bot",
      "home.sec1p": "The bridge <b>does not place bets</b> and doesn't talk to Betfair: it only writes the CSV file your software monitors. XTrader / Betting Toolkit does the betting — the bridge stays a predictable, verifiable link.",
      "home.card1.tag": "Custom parser", "home.card1.h": "🧩 Reads YOUR channel",
      "home.card1.p": "Every channel writes signals its own way. With the Custom Parser you define how to extract event, market, selection and odds — with preview and diagnostics on a real message before going live.",
      "home.card2.tag": "Safe by design", "home.card2.h": "🛡️ Simulation by default",
      "home.card2.p": "It starts in Simulation: signals recognized, operational CSV never touched. Test mode asks for confirmation; Real mode requires typing the word REALE and shows a persistent red banner.",
      "home.card3.tag": "Never stale signals", "home.card3.h": "🧹 Always-clean CSV",
      "home.card3.p": "One active signal, configurable timeout, automatic clearing, persistent anti-duplicate and crash recovery: your software sees the latest signal or none.",
      "home.card4.tag": "Multi-channel", "home.card4.h": "📡 Multiple source chats",
      "home.card4.p": "Configure several channels, each with its own parser and provider. The chat_id filter is an invariant: messages from unconfigured chats are always ignored.",
      "home.card5.tag": "Closing the loop", "home.card5.h": "✅ Software confirmations",
      "home.card5.p": "By linking the notification chat, a confirmed or rejected bet is removed from the CSV immediately, without waiting for the timeout.",
      "home.card6.tag": "Full visibility", "home.card6.h": "🚦 Health at a glance",
      "home.card6.p": "Seven health lights (Telegram, parser, CSV, mode…), a counters dashboard and a detailed log with colored levels: you always know what's happening.",
      "home.net.h": "Works with the whole Betting Toolkit family",
      "home.net.p": "The bridge was born for <b>XTrader</b> (Italy) and speaks the same CSV as the other products of the same maker. Pick your software's source language in the bridge and the CSV decimal separator aligns automatically.",
      "home.net.it": "Italy", "home.net.world": "World", "home.net.es": "Spain", "home.net.lat": "Latin America",
      "home.safety.h": "Transparency note.",
      "home.safety.p": "The bridge requires 64-bit Windows 10/11 and your betting software installed on the same machine. Settings stay on your PC (<code>%APPDATA%\\XTraderBridge</code>); the Telegram token is stored in the Windows keyring and never appears in logs.",
      "home.sec2": "Want to see it in action?",
      "home.sec2p": "The interactive demo replicates the real app: start the simulated bridge, send a test signal and watch the CSV being written and cleared. With a guided step-by-step tour.",
      "home.cta.open": "▶ Open the demo",
      "footer.tag": "The bridge doesn't place bets: it only writes the CSV your software reads.",
      "footer.contact": "Contact & support",
      "faq.h1": "Frequently asked questions",
      "faq.sub": "Can't find the answer? Ask the <b>support chatbot</b> (bottom right) or write to us from the <a href='/contatti'>Contact page</a>.",
      "faq.s1": "Setup and requirements",
      "faq.q1": "What computer do I need?",
      "faq.a1": "64-bit Windows 10/11 with your betting software (XTrader / Betting Toolkit) installed on the <b>same machine</b>: they communicate through a local CSV file. The EXE includes everything (no Python needed). Any recent PC is fine.",
      "faq.q2": "Can I use a VPS?",
      "faq.a2": "Yes, it's the typical 24/7 choice: a Windows VPS with 2 vCPU, 4 GB RAM and 50 GB SSD is enough. Set up autologon and auto-start, and remember: when leaving RDP just close the window, don't log out. If your account is region-locked (e.g. Betfair.it), prefer a VPS with an IP from that country.",
      "faq.q3": "What do I need before starting?",
      "faq.a3": "A Telegram bot created with <b>@BotFather</b> (it gives you the token), the bot added to the signals chat/channel, that chat's <b>Chat ID</b>, your betting software configured to monitor the CSV, and an active Betfair account.",
      "faq.s2": "Configuration",
      "faq.q4": "How do I do the first configuration?",
      "faq.a4": "Use the <b>🧙 First-configuration Wizard</b>: 5 steps with live checks — token (connection test), Chat ID (test message), parser on a real signal with CSV row preview, CSV path check and final checklist. The wizard never enables Real mode.",
      "faq.q5": "My channel writes signals in its own format: will it work?",
      "faq.a5": "Yes, that's what the <b>🧩 Custom Parser</b> is for: for each field you define how to extract it («Starts after» / «Ends before», fixed values, translations). «🧪 Test message» instantly shows the CSV row that would be generated. The parser never invents data: if a required field is missing, no row is written.",
      "faq.q6": "Can I use several channels at once?",
      "faq.a6": "Yes: from <b>🧰 Tools → 📡 Source chats</b> add more chats, each with its own parser and provider. The bridge listens <b>only</b> to configured chats.",
      "faq.q7": "Where are settings stored?",
      "faq.a7": "In <code>%APPDATA%\\XTraderBridge\\config.json</code>. The Telegram token is stored in the Windows keyring (Credential Manager), not in plain text. Settings survive reinstalling the program.",
      "faq.s3": "Safety and modes",
      "faq.q8": "Does the bridge place bets on its own?",
      "faq.a8": "No. The bridge only writes the CSV your software monitors: the software places the bets. And by default the bridge starts in <b>🧪 Simulation</b>, where the operational CSV isn't even written.",
      "faq.q9": "How do I switch to real mode?",
      "faq.a9": "From the <b>🛡️ Security</b> tab, with intentional friction: switching to <b>🔬 Test mode</b> asks Yes/No; <b>⚠️ Real</b> mode requires typing the word <code>REALE</code>, shows a persistent red banner and asks for confirmation at every listener start.",
      "faq.q10": "Any risk of repeating old bets?",
      "faq.a10": "No: one active signal (default design), configurable timeout, automatic CSV clearing and persistent anti-duplicate. After a crash or blackout, a stale CSV is cleaned at the next startup, before anything can write again.",
      "faq.q11": "What if the connection drops?",
      "faq.a11": "The bridge reconnects on its own with growing delays (2s → 60s) showing <b>RECONNECTING…</b>. Messages older than <code>max_signal_age</code> (default 120s) are ignored: backlogs never become old bets. A non-recoverable error (e.g. invalid token) stops the bridge and shows the error.",
      "faq.s4": "Common issues",
      "faq.q12": "The bridge won't start: why?",
      "faq.a12": "The exact reason is always in the <b>📋 Log</b>. Typical causes: missing Bot Token, missing CSV Path, invalid Timeout, no chat configured, or no active Custom Parser. The <b>🚦 Health</b> tab shows 7 lights with each requirement's status.",
      "faq.q13": "Nothing gets written to the CSV",
      "faq.a13": "If you're in Simulation that's normal: it's the default safety behavior. To really write, switch to Test or Real mode (with the confirmation gates).",
      "faq.q14": "Can I open two instances?",
      "faq.a14": "No: the second instance is refused at startup with a warning. Two instances could write the same CSV and place duplicate bets.",
      "faq.q15": "Do I have to keep the program open?",
      "faq.a15": "Yes, it must run (even minimized) while you want to receive signals. With <code>auto_start_listener</code> it can start by itself — in Real mode it asks for confirmation first.",
      "contact.h1": "Contact",
      "contact.sub": "For quick help try the <b>support chatbot</b> (bottom right) or the <a href='/faq'>FAQ</a> first. For everything else, write to us here.",
      "contact.form.h": "✉️ Write to us", "contact.name": "Name", "contact.email": "Your email",
      "contact.msg": "Message",
      "contact.ph": "Describe the problem or question. NEVER paste your bot token or account data.",
      "contact.send": "Send",
      "contact.sent": "Your email client opens with the pre-filled message.",
      "contact.warn.h": "🔒 Before writing",
      "contact.warn.p": "<b>Never</b> share your Telegram bot token, passwords or Betfair account data: they're not needed for diagnosis. Useful instead: what the <b>📋 Log</b> shows (the reason for a block is always there) and the <b>🚦 Health</b> tab.",
      "contact.time.h": "⏱️ Response times",
      "contact.time.p": "We usually reply within 1–2 working days. The chatbot is available 24/7 for questions covered by the documentation.",
      "chat.title": "Bridge Support", "chat.close": "Close",
      "chat.hello": "Hi! I'm the BetRelay assistant. I can help with setup, configuration, parser, CSV and safety modes — for XTrader and the Betting Toolkit family. What do you need?",
      "chat.ph": "Ask something about the bridge…", "chat.send": "Send",
      "chat.note": "Answers only about BetRelay. Never paste tokens or passwords.",
      "chat.thinking": "typing…", "chat.demo": "demo mode (no API key)",
      "chat.err": "Can't reach the server: check that the site is running."
    },
    es: {
      "nav.home": "Inicio", "nav.demo": "Demo interactiva", "nav.faq": "FAQ", "nav.contact": "Contacto",
      "home.h1": "Las señales de tu canal de Telegram, <em>dentro de tu software de apuestas</em>. Automáticamente.",
      "home.lead": "El bridge lee los mensajes del chat que elijas, los traduce con un parser a medida al CSV que tu software monitorea, y vacía el archivo tras el timeout. Configuras una vez; la cadena trabaja sola.",
      "home.cta.demo": "▶ Prueba la demo interactiva", "home.cta.faq": "Lee las FAQ",
      "home.sec1": "Por qué no es un bot de apuestas",
      "home.sec1p": "El bridge <b>no realiza apuestas</b> y no habla con Betfair: solo escribe el archivo CSV que tu software monitorea. XTrader / Betting Toolkit es quien opera — el bridge es un puente predecible y verificable.",
      "home.card1.tag": "Parser a medida", "home.card1.h": "🧩 Lee TU canal",
      "home.card1.p": "Cada canal escribe las señales a su manera. Con el Parser Personalizado defines cómo extraer evento, mercado, selección y cuota — con vista previa y diagnóstico sobre un mensaje real antes de ir en vivo.",
      "home.card2.tag": "Seguro por diseño", "home.card2.h": "🛡️ Simulación por defecto",
      "home.card2.p": "Arranca en Simulación: señales reconocidas, CSV operativo nunca tocado. El modo Prueba pide confirmación; el modo Real exige escribir la palabra REALE y muestra un banner rojo persistente.",
      "home.card3.tag": "Nunca señales viejas", "home.card3.h": "🧹 CSV siempre limpio",
      "home.card3.p": "Una sola señal activa, timeout configurable, vaciado automático, anti-duplicado persistente y recuperación tras crash: tu software ve la señal más reciente o ninguna.",
      "home.card4.tag": "Multi-canal", "home.card4.h": "📡 Varios chats fuente",
      "home.card4.p": "Configura varios canales, cada uno con su parser y proveedor. El filtro chat_id es una invariante: los mensajes de chats no configurados se ignoran siempre.",
      "home.card5.tag": "El círculo se cierra", "home.card5.h": "✅ Confirmaciones del software",
      "home.card5.p": "Vinculando el chat de notificaciones, una apuesta confirmada o rechazada se elimina del CSV al instante, sin esperar el timeout.",
      "home.card6.tag": "Todo bajo control", "home.card6.h": "🚦 Salud de un vistazo",
      "home.card6.p": "Siete semáforos (Telegram, parser, CSV, modo…), panel de contadores y log detallado con niveles de color: siempre sabes qué está pasando.",
      "home.net.h": "Compatible con toda la familia Betting Toolkit",
      "home.net.p": "El bridge nació para <b>XTrader</b> (Italia) y habla el mismo CSV que los demás productos del mismo fabricante. Elige el idioma fuente de tu software en el bridge y el separador decimal del CSV se alinea automáticamente.",
      "home.net.it": "Italia", "home.net.world": "Mundo", "home.net.es": "España", "home.net.lat": "Latinoamérica",
      "home.safety.h": "Nota de transparencia.",
      "home.safety.p": "El bridge requiere Windows 10/11 de 64 bits y tu software de apuestas instalado en la misma máquina. La configuración queda en tu PC (<code>%APPDATA%\\XTraderBridge</code>); el token de Telegram se guarda en el keyring de Windows y nunca aparece en los logs.",
      "home.sec2": "¿Quieres verlo en acción?",
      "home.sec2p": "La demo interactiva replica la app real: arranca el bridge simulado, envía una señal de prueba y mira el CSV escribirse y vaciarse. Con tour guiado paso a paso.",
      "home.cta.open": "▶ Abrir la demo",
      "footer.tag": "El bridge no realiza apuestas: solo escribe el CSV que tu software lee.",
      "footer.contact": "Contacto y soporte",
      "faq.h1": "Preguntas frecuentes",
      "faq.sub": "¿No encuentras la respuesta? Pregunta al <b>chatbot de soporte</b> (abajo a la derecha) o escríbenos desde la <a href='/contatti'>página de Contacto</a>.",
      "faq.s1": "Instalación y requisitos",
      "faq.q1": "¿Qué ordenador necesito?",
      "faq.a1": "Windows 10/11 de 64 bits con tu software de apuestas (XTrader / Betting Toolkit) instalado en la <b>misma máquina</b>: se comunican mediante un archivo CSV local. El EXE lo incluye todo (no hace falta Python). Cualquier PC reciente sirve.",
      "faq.q2": "¿Puedo usar un VPS?",
      "faq.a2": "Sí, es la opción típica para 24/7: un VPS Windows con 2 vCPU, 4 GB de RAM y 50 GB SSD basta. Configura autologon y arranque automático, y recuerda: al salir de RDP cierra solo la ventana, sin cerrar sesión. Si tu cuenta tiene bloqueo regional, prefiere un VPS con IP de ese país.",
      "faq.q3": "¿Qué necesito antes de empezar?",
      "faq.a3": "Un bot de Telegram creado con <b>@BotFather</b> (te da el token), el bot añadido al chat/canal de señales, el <b>Chat ID</b> de ese chat, tu software configurado para monitorear el CSV, y una cuenta Betfair activa.",
      "faq.s2": "Configuración",
      "faq.q4": "¿Cómo hago la primera configuración?",
      "faq.a4": "Usa el <b>🧙 Asistente de primera configuración</b>: 5 pasos con verificaciones en vivo — token (prueba de conexión), Chat ID (mensaje de prueba), parser sobre una señal real con vista previa de la fila CSV, verificación de la ruta CSV y checklist final. El asistente nunca activa el modo Real.",
      "faq.q5": "Mi canal escribe las señales en su propio formato: ¿funcionará?",
      "faq.a5": "Sí, para eso está el <b>🧩 Parser Personalizado</b>: para cada campo defines cómo extraerlo («Empieza después» / «Termina antes», valores fijos, traducciones). «🧪 Probar mensaje» muestra al instante la fila CSV que se generaría. El parser nunca inventa datos: si falta un campo obligatorio, no se escribe ninguna fila.",
      "faq.q6": "¿Puedo usar varios canales a la vez?",
      "faq.a6": "Sí: desde <b>🧰 Herramientas → 📡 Chats fuente</b> añade más chats, cada uno con su parser y proveedor. El bridge escucha <b>solo</b> los chats configurados.",
      "faq.q7": "¿Dónde se guarda la configuración?",
      "faq.a7": "En <code>%APPDATA%\\XTraderBridge\\config.json</code>. El token de Telegram se guarda en el keyring de Windows (Credential Manager), no en texto plano. La configuración sobrevive a la reinstalación.",
      "faq.s3": "Seguridad y modos",
      "faq.q8": "¿El bridge apuesta por su cuenta?",
      "faq.a8": "No. El bridge solo escribe el CSV que tu software monitorea: es el software quien apuesta. Y por defecto el bridge arranca en <b>🧪 Simulación</b>, donde el CSV operativo ni siquiera se escribe.",
      "faq.q9": "¿Cómo paso al modo real?",
      "faq.a9": "Desde la pestaña <b>🛡️ Seguridad</b>, con fricción intencional: pasar a <b>🔬 Prueba</b> pide Sí/No; el modo <b>⚠️ Real</b> exige escribir la palabra <code>REALE</code>, muestra un banner rojo persistente y pide confirmación en cada arranque del listener.",
      "faq.q10": "¿Riesgo de repetir apuestas viejas?",
      "faq.a10": "No: una sola señal activa (diseño por defecto), timeout configurable, vaciado automático del CSV y anti-duplicado persistente. Tras un crash o apagón, un CSV obsoleto se limpia en el siguiente arranque.",
      "faq.q11": "¿Y si se cae la conexión?",
      "faq.a11": "El bridge se reconecta solo con esperas crecientes (2s → 60s) mostrando <b>RECONEXIÓN…</b>. Los mensajes más viejos que <code>max_signal_age</code> (120s por defecto) se ignoran: los atrasados nunca se convierten en apuestas viejas. Un error no recuperable (token inválido) detiene el bridge y muestra el error.",
      "faq.s4": "Problemas comunes",
      "faq.q12": "El bridge no arranca: ¿por qué?",
      "faq.a12": "El motivo exacto está siempre en el <b>📋 Log</b>. Causas típicas: falta el Bot Token, falta la ruta CSV, Timeout inválido, ningún chat configurado, o ningún Parser Personalizado activo. La pestaña <b>🚦 Salud</b> muestra 7 semáforos con el estado de cada requisito.",
      "faq.q13": "No escribe nada en el CSV",
      "faq.a13": "Si estás en Simulación es normal: es el comportamiento de seguridad por defecto. Para escribir de verdad pasa a Prueba o Real (con las puertas de confirmación).",
      "faq.q14": "¿Puedo abrir dos instancias?",
      "faq.a14": "No: la segunda instancia se rechaza al arrancar con un aviso. Dos instancias podrían escribir el mismo CSV y duplicar apuestas.",
      "faq.q15": "¿Debo mantener el programa abierto?",
      "faq.a15": "Sí, debe ejecutarse (aunque minimizado) mientras quieras recibir señales. Con <code>auto_start_listener</code> puede arrancar solo — en modo Real pide confirmación antes.",
      "contact.h1": "Contacto",
      "contact.sub": "Para ayuda rápida prueba primero el <b>chatbot de soporte</b> (abajo a la derecha) o las <a href='/faq'>FAQ</a>. Para todo lo demás, escríbenos aquí.",
      "contact.form.h": "✉️ Escríbenos", "contact.name": "Nombre", "contact.email": "Tu email",
      "contact.msg": "Mensaje",
      "contact.ph": "Describe el problema o la pregunta. NUNCA pegues el token del bot ni datos de la cuenta.",
      "contact.send": "Enviar",
      "contact.sent": "Se abre tu cliente de correo con el mensaje precompilado.",
      "contact.warn.h": "🔒 Antes de escribir",
      "contact.warn.p": "No compartas <b>nunca</b> el token del bot de Telegram, contraseñas ni datos de la cuenta Betfair: no hacen falta para el diagnóstico. Útil en cambio: lo que muestra el <b>📋 Log</b> y la pestaña <b>🚦 Salud</b>.",
      "contact.time.h": "⏱️ Tiempos de respuesta",
      "contact.time.p": "Solemos responder en 1–2 días laborables. El chatbot está disponible 24/7 para las preguntas cubiertas por la documentación.",
      "chat.title": "Soporte Bridge", "chat.close": "Cerrar",
      "chat.hello": "¡Hola! Soy el asistente de BetRelay. Puedo ayudarte con instalación, configuración, parser, CSV y modos de seguridad — para XTrader y la familia Betting Toolkit. ¿Qué necesitas?",
      "chat.ph": "Pregunta algo sobre el bridge…", "chat.send": "Enviar",
      "chat.note": "Responde solo sobre BetRelay. Nunca pegues tokens ni contraseñas.",
      "chat.thinking": "escribiendo…", "chat.demo": "modo demo (sin API key)",
      "chat.err": "No se puede contactar el servidor: verifica que el sitio esté en marcha."
    }
  };

  function detect() {
    try {
      var saved = localStorage.getItem("site_lang");
      if (saved === "it" || saved === "en" || saved === "es") return saved;
    } catch (e) { /* storage bloccato: si usa il browser */ }
    var nav = (navigator.language || "en").toLowerCase();
    if (nav.indexOf("it") === 0) return "it";
    if (nav.indexOf("es") === 0) return "es";
    return "en";
  }

  function apply(lang) {
    window.SITE_LANG = lang;
    document.documentElement.lang = lang;
    try { localStorage.setItem("site_lang", lang); } catch (e) { /* ok */ }
    var els = document.querySelectorAll("[data-i18n]");
    for (var i = 0; i < els.length; i++) {
      var el = els[i], key = el.getAttribute("data-i18n");
      if (el.dataset.i18nOrig === undefined) el.dataset.i18nOrig = el.innerHTML;
      var v = (T[lang] || {})[key];
      el.innerHTML = (lang === "it" || v === undefined) ? el.dataset.i18nOrig : v;
    }
    var phs = document.querySelectorAll("[data-i18n-ph]");
    for (var j = 0; j < phs.length; j++) {
      var p = phs[j], k = p.getAttribute("data-i18n-ph");
      if (p.dataset.i18nPhOrig === undefined) p.dataset.i18nPhOrig = p.getAttribute("placeholder") || "";
      var pv = (T[lang] || {})[k];
      p.setAttribute("placeholder", (lang === "it" || pv === undefined) ? p.dataset.i18nPhOrig : pv);
    }
    var btns = document.querySelectorAll(".lang-sw button");
    for (var b = 0; b < btns.length; b++) {
      btns[b].setAttribute("aria-pressed", btns[b].dataset.lang === lang ? "true" : "false");
    }
    document.dispatchEvent(new CustomEvent("langchange", { detail: { lang: lang } }));
  }

  window.SITE_T = function (key) {
    var lang = window.SITE_LANG || "it";
    if (lang === "it") return null;
    return (T[lang] || {})[key] || null;
  };
  window.SITE_SET_LANG = apply;

  document.addEventListener("DOMContentLoaded", function () {
    var sw = document.querySelectorAll(".lang-sw button");
    for (var i = 0; i < sw.length; i++) {
      sw[i].addEventListener("click", function () { apply(this.dataset.lang); });
    }
    apply(detect());
  });
})();
