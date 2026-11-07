/** Only accept the exact native-client callback; do not log its code. */
export function normalizeCallback(candidate) {
  if (typeof candidate !== "string") return null;
  const match = /^somtoday:\/\/nl\.topicus\.somtoday\.leerling(?::443)?\/oauth\/callback\?([^#]+)$/i.exec(candidate.trim());
  if (!match) return null;
  const params = new URLSearchParams(match[1]);
  if (!params.get("code") || !params.get("state")) return null;
  return "somtoday://nl.topicus.somtoday.leerling/oauth/callback?" + match[1];
}

export function validCapture(record, now = Date.now()) {
  return record && typeof record === "object" && record.expiresAt > now
    ? normalizeCallback(record.url)
    : null;
}
