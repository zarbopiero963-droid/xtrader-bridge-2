/* Widget chatbot di supporto — parla solo con /api/chat (mai con l'API diretta).
   Multilingue: usa SITE_T/SITE_LANG di i18n.js e manda la lingua al backend. */
(function () {
  "use strict";
  var history = [];

  function t(key, fallback) {
    var v = window.SITE_T ? window.SITE_T(key) : null;
    return v || fallback;
  }

  var fab = document.createElement("button");
  fab.id = "chat-fab";

  var panel = document.createElement("div");
  panel.id = "chat-panel";
  panel.hidden = true;
  panel.innerHTML =
    '<div id="chat-head"><b></b><span id="chat-mode"></span>' +
    '<button id="chat-close">✕</button></div>' +
    '<div id="chat-msgs" aria-live="polite"></div>' +
    '<form id="chat-form"><input id="chat-input" autocomplete="off" maxlength="1000">' +
    '<button id="chat-send" type="submit"></button></form>' +
    '<div id="chat-note"></div>';

  document.body.appendChild(fab);
  document.body.appendChild(panel);

  var msgs = panel.querySelector("#chat-msgs");
  var input = panel.querySelector("#chat-input");
  var send = panel.querySelector("#chat-send");
  var modeEl = panel.querySelector("#chat-mode");
  var headB = panel.querySelector("#chat-head b");
  var note = panel.querySelector("#chat-note");
  var closeBtn = panel.querySelector("#chat-close");
  var demoMode = false;

  function paintUi() {
    fab.textContent = "💬 " + t("chat.title", "Supporto BetRelay");
    fab.setAttribute("aria-label", t("chat.title", "Supporto BetRelay"));
    headB.textContent = t("chat.title", "Supporto BetRelay");
    closeBtn.setAttribute("aria-label", t("chat.close", "Chiudi"));
    input.setAttribute("placeholder", t("chat.ph", "Chiedi qualcosa sul bridge…"));
    input.setAttribute("aria-label", t("chat.ph", "Chiedi qualcosa sul bridge…"));
    send.textContent = t("chat.send", "Invia");
    note.textContent = t("chat.note",
      "Risponde solo su BetRelay. Non incollare mai token o password.");
    modeEl.textContent = demoMode ? t("chat.demo", "modalità demo (senza API key)") : "";
  }
  document.addEventListener("langchange", paintUi);
  paintUi();

  function add(role, text, extra) {
    var d = document.createElement("div");
    d.className = "cmsg " + role + (extra ? " " + extra : "");
    d.textContent = text;
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
    return d;
  }

  function open() {
    panel.hidden = false;
    fab.hidden = true;
    if (!msgs.childElementCount) {
      add("bot", t("chat.hello",
        "Ciao! Sono l'assistente di BetRelay. Posso aiutarti su installazione, " +
        "configurazione, parser, CSV e modalità di sicurezza — per XTrader e la famiglia " +
        "Betting Toolkit. Cosa ti serve?"));
    }
    input.focus();
  }
  function close() { panel.hidden = true; fab.hidden = false; }

  fab.addEventListener("click", open);
  closeBtn.addEventListener("click", close);

  panel.querySelector("#chat-form").addEventListener("submit", function (e) {
    e.preventDefault();
    var text = input.value.trim();
    if (!text || send.disabled) return;
    input.value = "";
    add("user", text);
    history.push({ role: "user", content: text });
    send.disabled = true;
    var thinking = add("bot", t("chat.thinking", "sto scrivendo…"), "thinking");

    fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        lang: window.SITE_LANG || "it",
        history: history.slice(0, -1).slice(-6)
      })
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        thinking.remove();
        var reply = (data && data.reply) ? data.reply :
          "Errore inatteso: riprova / Unexpected error: retry.";
        add("bot", reply);
        history.push({ role: "assistant", content: reply });
        demoMode = !!(data && data.demo);
        paintUi();
      })
      .catch(function () {
        thinking.remove();
        add("bot", t("chat.err", "Non riesco a contattare il server: verifica che il sito sia avviato."));
      })
      .finally(function () { send.disabled = false; input.focus(); });
  });
})();
