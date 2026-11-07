import test from "node:test";
import assert from "node:assert/strict";
import { normalizeCallback, validCapture } from "./callback.mjs";

const good = "somtoday://nl.topicus.somtoday.leerling/oauth/callback?code=abc&state=xyz";

test("accept canonical callback", () => {
  assert.equal(normalizeCallback(good), good);
});
test("strip Chromium inserted port", () => {
  assert.equal(normalizeCallback(good.replace("/oauth/", ":443/oauth/")), good);
});
test("reject noncallback, other origins, and missing state", () => {
  assert.equal(normalizeCallback("https://leerling.somtoday.nl/oauth/callback?code=x&state=y"), null);
  assert.equal(normalizeCallback("somtoday://evil/oauth/callback?code=x&state=y"), null);
  assert.equal(normalizeCallback(good.replace("&state=xyz", "")), null);
  assert.equal(normalizeCallback(null), null);
});
test("expiry is enforced", () => {
  assert.equal(validCapture({ url: good, expiresAt: 1001 }, 1000), good);
  assert.equal(validCapture({ url: good, expiresAt: 999 }, 1000), null);
});
