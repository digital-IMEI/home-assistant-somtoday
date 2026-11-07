import { validCapture } from "./callback.mjs";

const state = document.getElementById("state");
const fill = document.getElementById("fill");
const copy = document.getElementById("copy");
const clear = document.getElementById("clear");

function message(value) { state.textContent = value; }
async function readCallback() {
  const { callback } = await chrome.storage.session.get("callback");
  const url = validCapture(callback);
  if (!url && callback) await chrome.storage.session.remove("callback");
  return url;
}
async function refresh() {
  const url = await readCallback();
  fill.disabled = !url;
  copy.disabled = !url;
  message(url ? "Callback beschikbaar (maximaal 5 minuten)." :
    "Nog geen geldige callback. Log opnieuw in via de HA-inloglink.");
}
await refresh();

clear.addEventListener("click", async () => {
  await chrome.storage.session.remove("callback");
  await refresh();
});

copy.addEventListener("click", async () => {
  const url = await readCallback();
  if (!url) return refresh();
  try {
    await navigator.clipboard.writeText(url);
    message("Callback gekopieerd. Plak hem in Home Assistant.");
  } catch {
    message("Kopiëren mislukt. Gebruik de handmatige inlogstappen.");
  }
});

fill.addEventListener("click", async () => {
  const url = await readCallback();
  if (!url) return refresh();
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id || !/^https?:\/\//i.test(tab.url || "")) {
    return message("Open het Home Assistant-tabblad met het callback-veld.");
  }
  try {
    const [response] = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: enterIntoHomeAssistant,
      args: [url],
    });
    const result = response?.result;
    if (!result?.filled) return message("Geen Somtoday-veld gevonden. Gebruik Kopieer callback.");
    await chrome.storage.session.remove("callback");
    fill.disabled = true;
    copy.disabled = true;
    message(result.submitted ?
      "Callback ingevoerd en verzonden. Controleer of de aanmelding is gelukt." :
      "Callback ingevuld. Verstuur het formulier nu zelf in Home Assistant.");
  } catch {
    message("Invullen mislukt. Gebruik Kopieer callback of Developer Tools.");
  }
});

// Runs only inside the active tab after an explicit user click on the helper.
function enterIntoHomeAssistant(callbackUrl) {
  if (!document.querySelector("home-assistant")) return { filled: false };
  const roots = [];
  function walk(root) {
    roots.push(root);
    for (const node of root.querySelectorAll("*")) {
      if (node.shadowRoot) walk(node.shadowRoot);
    }
  }
  walk(document);
  let field;
  for (const root of roots) {
    for (const node of root.querySelectorAll("input, ha-textfield, mwc-textfield")) {
      const name = String(node.name || node.getAttribute("name") || node.id || "");
      const label = String(node.getAttribute("label") || node.getAttribute("aria-label") || "");
      if (name.includes("callback_url") || /callback[\s_-]*(url|uri)?/i.test(label)) {
        field = node;
        break;
      }
    }
    if (field) break;
  }
  if (!field) return { filled: false };
  field.value = callbackUrl;
  field.dispatchEvent(new Event("input", { bubbles: true, composed: true }));
  field.dispatchEvent(new Event("change", { bubbles: true, composed: true }));
  // Prefer a submit control in the field's own shadow root, then scan all.
  const commands = /^(submit|next|volgende|verzenden|indienen|bevestigen|voltooien|finish)$/i;
  let submit;
  for (const root of roots) {
    for (const node of root.querySelectorAll("button, mwc-button, ha-button")) {
      const caption = String(node.textContent || node.getAttribute("label") || "").trim();
      if (node.type === "submit" || commands.test(caption)) submit = node;
    }
  }
  if (submit) submit.click();
  return { filled: true, submitted: Boolean(submit) };
}
