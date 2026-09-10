# Somtoday for Home Assistant

An unofficial, community integration for school schedules. Runs inside Home Assistant,
including Home Assistant Green; no separate server, add-on or companion script is needed.
Not affiliated with Somtoday or Topicus. The underlying API is unofficial and may change.

## Features

- School dropdown and browser login (password stays on the school's login page).
- Separate **Name · Rooster** calendar and **Name · Schooldag** sensor for each child.
- Export one event per school day, from the first lesson to the end of the last lesson.
- Independently export individual active lessons to another calendar, or the same calendar.
- Choose both destination calendars separately **for each child in the account**.
- Preview counts before enabling writes; account-level Calendar sync sensor reports results/errors.
- Adjustable look-ahead (1–30 days) and polling (5–120 minutes, default 15).
- Default titles include the child's name: `School · Seth`, `Seth · Mathematics`.

## Installation and updates

In HACS, add `https://github.com/digital-IMEI/home-assistant-somtoday` as a custom
repository, category **Integration**. Download the latest numbered release and restart
Home Assistant. Add **Somtoday** under **Settings → Devices & services**.
For manual installation, copy `custom_components/somtoday` into your HA configuration.
After updates restart HA and reload the browser if setup text is cached.

## Signing in — read this before opening the login link

Use a desktop browser (Chrome, Edge or Firefox) for initial setup. A phone may open
the Somtoday app before you can copy the return URL.

1. Select the organization from the dropdown. Some schools appear under a school group
   rather than their location name. Do not assume all Sophianum or LVO users use the same tenant.
2. Click **Open the Somtoday sign-in page** in a new tab. Leave the HA setup dialog open.
3. **Before logging in**, open the browser's Developer Tools with **F12**.
   This means the browser tools, not Home Assistant's Developer Tools menu.
4. Open **Network**, enable **Preserve log** (Firefox: **Persist Logs**), and select **All**.
   Clear existing requests if helpful. Then complete the school login normally.
5. The server redirects to a URL beginning
   `somtoday://nl.topicus.somtoday.leerling/oauth/callback?code=…&state=…`.
   A browser may not display this in its address bar. That is expected.
6. In Network, inspect the final redirect requests. In **Headers → Response Headers**,
   find **Location** containing the `somtoday://` URL. Copy the **entire header value**.
   Depending on the browser it may instead appear as a failed request URL, or in a
   **Console** message reporting that the custom protocol cannot be opened.
7. Paste that complete URL into the HA **callback URL** field and submit.

The callback must contain both `code=` and `state=` from the current HA setup attempt.
Do not enter the fixed callback prefix, the web timetable URL, a test link's callback,
or the authorization request URL. Codes are temporary and single-use.
If requests were not preserved, repeat login using the link in the still-open HA dialog;
if you restarted setup, use its new link. Never export or share a HAR, cookies, tokens,
passwords or callback URLs. A callback is a temporary credential.

If you only see a bare `callback_url` field with no login link, check your installed
version, restart HA and refresh the browser. English and Dutch translations are bundled
and tested. The callback flow has been verified by a Sophianum user; browser behavior
and other schools' identity providers may differ.

## Configure calendar export

1. First configure your destination calendar integration in Home Assistant. For Google,
   use the built-in [Google Calendar integration](https://www.home-assistant.io/integrations/google/)
   and grant write access. A Local Calendar also works through the same entity interface.
2. Open **Settings → Devices & services → Somtoday → Configure** (options).
3. Select a child, then choose the school-day calendar and/or the lessons calendar.
   **Disabled** leaves that output off. Only available calendars supporting create and
   delete are offered. Somtoday's own read-only calendars cannot be destinations.
4. Set titles. The literal `{student}` in a title or prefix is replaced with that child's
   first name. You may enter a distinctive full name yourself if children share a first name.
5. Keep **Preview only** enabled and save. Inspect **Calendar sync** in Developer Tools → States:
   `create`, `replace`, `delete`, `unchanged` report the planned operation counts.
6. Repeat configuration for other children. Their saved destinations remain intact.
7. Once the preview is correct, switch **Preview only** off and save. This enables export
   for **all configured children in this account**. Interval and days-ahead also apply to
   the whole account. Options reload the integration; no HA restart is needed.

Both outputs can use the same family calendar. Identity includes account, child, output
type and source appointment/day, so siblings and output types remain separate.

## Synchronization behavior and limits

- Reads from today up to the selected look-ahead boundary. The source may not have
  published that far ahead. It does not fetch historical schedules or promise an entire term.
- School-day events include gaps/tussenuren between the first and last lesson.
  Breaks do not define the boundaries. Only appointments classified as timetable/mandatory
  and active are exported; homework and personal appointments are not lesson exports.
- An opaque marker in the description identifies managed events. Do not remove that marker.
  Ordinary appointments and other children's disabled outputs are left alone.
- Identical events are not recreated. Changed events are **replaced**: first create and
  verify the new version, then delete the old one. Google Calendar's HA entity currently
  lacks an update operation. Brief overlap is possible; the event ID changes. Do not attach
  guests, custom reminders or personal notes to managed events; those edits are not preserved.
- Cancelled/removed lessons and empty school days remove corresponding managed events
  inside the current synchronization window. Past days are left intact. A failed source fetch
  or incomplete pagination prevents synchronization.
- **Changing or disabling a destination does not clean the old calendar.** Remove old
  exported events manually if needed. Reducing the look-ahead leaves events beyond the new
  boundary unchanged. Removing the integration also leaves exported events in place.
- If a calendar write times out, the integration records the uncertain operation persistently.
  It waits until that event is visible before retrying, to avoid duplicate creation after restart.
  If it never becomes visible, synchronization needs investigation; do not repeatedly
  reinstall or edit HA storage. Report the sanitized sync status and version.
- Target failures appear in **Calendar sync**; the source roster is kept available.
  Some calendar providers have delayed read-after-write behavior. Google and Local Calendar
  are the intended initial targets; live write behavior must still be verified in your setup.
- Multiple children require the API to identify which child each appointment belongs to.
  If this metadata is missing, the integration pauses rather than mixing school days.
  Newly added children require an integration reload to create their entities.
- Existing first-child entity IDs are retained where possible. Additional entities use stable
  child IDs internally; first-name changes do not change event ownership.

## Privacy and support

Tokens are stored in the HA configuration, never in this repository. Treat backups as private.
Export sends titles, lesson times, child names and locations to your chosen calendar provider.
Grades, messages and homework are not fetched by this version.

For an issue include integration/HA version, browser, school organization, selected output
mode, sanitized error and whether source times match. Redact names, locations and all auth data.
Do not include raw diagnostics or HAR files. The integration remains experimental while
multi-school and live calendar-provider compatibility are being established.

See [community roadmap](docs/ROADMAP.md) for researched follow-up features and limitations.
