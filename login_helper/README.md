# Somtoday Chrome/Edge login helper (optional)

This **source-only** Manifest V3 extension intercepts Somtoday's native
OAuth callback in your local browser. It stores the short-lived code only in
`chrome.storage.session` for at most five minutes. It does **not** collect
passwords, contact external servers, or request access to every website.

## Install

Download this repository as a ZIP and extract it. Open
`chrome://extensions` (or `edge://extensions`), enable Developer mode,
click **Load unpacked**, and select the `login_helper` folder. The extension
is **not** published in a browser store.

## Use

1. Leave Home Assistant's Somtoday authorization dialog open.
2. Click the sign-in link in that dialog and log in to Somtoday.
3. Return to the **Home Assistant** tab, open the extension and select
   **Invullen en indienen**.
4. If the HA field cannot be found, select **Kopieer callback**, paste it into
   the HA dialog and submit manually.

Do not share a callback URL in a GitHub issue: it contains a temporary
authorization code. A "scheme not registered" browser warning is expected
when no native Somtoday app handler is installed. Chrome may add `:443`
to the custom scheme; the extension handles that.

**Limitations:** Chrome/Edge only. Somtoday school identity providers and
Home Assistant frontend markup can vary; automatic insertion may fail.
The existing Developer Tools fallback remains supported. If Home Assistant
is not selected as the active tab, the helper will not inject anything.
