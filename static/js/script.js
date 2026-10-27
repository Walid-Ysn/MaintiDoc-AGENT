(() => {
  const STORAGE_KEY = "maintidoc.conversationId";
  const newId = () => crypto.randomUUID();
  let conversationId = localStorage.getItem(STORAGE_KEY) || newId();
  localStorage.setItem(STORAGE_KEY, conversationId);
  const output = document.querySelector("#gpt-output");
  const form = document.querySelector("#prompt-form");
  const sendButton = form.querySelector('button[type="submit"]');
  const notice = document.querySelector("#notice");
  const specialty = document.querySelector("#specialty");
  const converter = new showdown.Converter();

  function showNotice(message, error = false) {
    notice.textContent = message;
    notice.classList.remove("hidden", "border-amber-300", "bg-amber-50", "border-red-300", "bg-red-50");
    notice.classList.add(error ? "border-red-300" : "border-amber-300", error ? "bg-red-50" : "bg-amber-50");
  }
  function clearNotice() { notice.textContent = ""; notice.classList.add("hidden"); }
  function appendMessage(role, text) {
    const block = document.querySelector("#chat-template").cloneNode(true);
    block.removeAttribute("id"); block.classList.remove("hidden");
    block.dataset.role = role;
    const body = block.querySelector(".message");
    body.innerHTML = role === "assistant" ? DOMPurify.sanitize(converter.makeHtml(text)) : "";
    if (role === "user") body.textContent = text;
    block.insertAdjacentHTML("afterbegin", `<div class="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">${role === "user" ? "Vous" : "MaintiDoc"}</div>`);
    output.appendChild(block); block.scrollIntoView({ behavior: "smooth", block: "end" });
    return body;
  }
  function currentMessages() {
    return Array.from(output.querySelectorAll("[data-role]")).map(el => ({ role: el.dataset.role, content: el.querySelector(".message").innerText }));
  }
  function displayMessages(messages) {
    output.replaceChildren();
    messages.forEach(m => appendMessage(m.role, m.content));
  }
  async function loadHistory() {
    try {
      const r = await fetch(`/api/conversations/${conversationId}`);
      if (!r.ok) throw new Error("Chargement impossible.");
      const data = await r.json(); displayMessages(data.messages || []); specialty.value = data.specialty || "maintenance";
    } catch (e) { showNotice("Impossible de charger l’historique enregistré.", true); }
  }
  async function sendPrompt(text) {
    appendMessage("user", text);
    const assistant = appendMessage("assistant", "");
    const response = await fetch("/prompt", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ conversation_id: conversationId, specialty: specialty.value, messages: currentMessages().filter(m => m.content.trim()) }) });
    if (!response.ok) {
      const data = await response.json().catch(() => ({})); throw new Error(data.error || `Erreur serveur (${response.status}).`);
    }
    if (!response.body) throw new Error("Le serveur n’a pas retourné de réponse.");
    const reader = response.body.getReader(); const decoder = new TextDecoder(); let textSoFar = "";
    while (true) {
      const { done, value } = await reader.read(); if (done) break;
      textSoFar += decoder.decode(value, { stream: true });
      if (textSoFar.includes("[ERREUR]")) throw new Error(textSoFar.replace(/\[ERREUR\]/g, "").trim());
      assistant.innerHTML = DOMPurify.sanitize(converter.makeHtml(textSoFar));
    }
    textSoFar += decoder.decode(); assistant.innerHTML = DOMPurify.sanitize(converter.makeHtml(textSoFar));
  }
  form.addEventListener("submit", async event => {
    event.preventDefault(); clearNotice();
    const text = form.elements.prompt.value.trim(); if (!text || sendButton.disabled) return;
    form.reset(); sendButton.disabled = true;
    try { await sendPrompt(text); } catch (e) { showNotice(e.message || "Impossible d’obtenir une réponse.", true); }
    finally { sendButton.disabled = false; }
  });
  document.querySelector("#clear-button").addEventListener("click", async () => {
    clearNotice();
    try {
      const r = await fetch(`/api/conversations/${conversationId}`, { method: "DELETE" });
      if (!r.ok) throw new Error("Suppression impossible.");
      output.replaceChildren(); conversationId = newId(); localStorage.setItem(STORAGE_KEY, conversationId); showNotice("Conversation effacée.");
    } catch (e) { showNotice(e.message, true); }
  });
  document.querySelector("#export-button").addEventListener("click", async () => {
    clearNotice();
    try {
      const r = await fetch(`/api/conversations/${conversationId}/export`);
      if (!r.ok) { const d = await r.json().catch(() => ({})); throw new Error(d.error || "Export impossible."); }
      const blob = await r.blob(); const url = URL.createObjectURL(blob); const a = document.createElement("a");
      a.href = url; a.download = "conversation-maintidoc.md"; a.click(); URL.revokeObjectURL(url);
    } catch (e) { showNotice(e.message, true); }
  });
  document.querySelector("#summarize-button").addEventListener("click", async event => {
    clearNotice(); const file = document.querySelector("#file-input").files[0];
    if (!file) { showNotice("Choisissez d’abord un fichier.", true); return; }
    const button = event.currentTarget; button.disabled = true; button.textContent = "Résumé en cours…";
    const data = new FormData(); data.append("file", file); data.append("specialty", specialty.value); data.append("conversation_id", conversationId);
    try {
      const r = await fetch("/api/summarize", { method: "POST", body: data }); const result = await r.json();
      if (!r.ok) throw new Error(result.error || "Résumé impossible.");
      appendMessage("user", `Résumé du fichier « ${file.name} » demandé.`); appendMessage("assistant", result.summary);
      document.querySelector("#file-input").value = "";
    } catch (e) { showNotice(e.message || "Échec du traitement du fichier.", true); }
    finally { button.disabled = false; button.textContent = "Insérer / résumer"; }
  });
  specialty.addEventListener("change", () => { clearNotice(); showNotice("La spécialité sera appliquée aux prochains messages."); });
  loadHistory();
})();
