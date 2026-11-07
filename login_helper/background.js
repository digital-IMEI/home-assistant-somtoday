import { normalizeCallback } from "./callback.mjs";

const filter = { urls: [
  "https://inloggen.somtoday.nl/*",
  "https://leerling.somtoday.nl/*",
] };

function capture(candidate) {
  const url = normalizeCallback(candidate);
  if (!url) return;
  // Session-scoped browser memory only. No disk sync or outside service.
  void chrome.storage.session.set({
    callback: { url, expiresAt: Date.now() + 5 * 60 * 1000 },
  });
}
chrome.webRequest.onBeforeRedirect.addListener(
  (details) => capture(details.redirectUrl), filter
);
chrome.webRequest.onHeadersReceived.addListener(
  (details) => {
    for (const header of details.responseHeaders || []) {
      if (header.name.toLowerCase() === "location") capture(header.value);
    }
  }, filter, ["responseHeaders"]
);
