# Somtoday for Home Assistant

An unofficial, community integration for school schedules. Runs inside Home Assistant,
including Home Assistant Green; no separate server, add-on or companion script is needed.
Not affiliated with Somtoday or Topicus. The underlying API is unofficial and may change.

## Features

- School dropdown and browser login (password stays on the school's login page).
- Two source calendars per child: **Name · Rooster** with individual lessons and
  **Name · Schooldag** with one event from the first lesson start through the last lesson end.
- Export one event per school day, from the first lesson to the end of the last lesson.
- Independently export individual active lessons to another calendar, or the same calendar.
- Export every published Somtoday holiday as one multi-day, all-day event.
- Choose all three destination calendars separately **for each child in the account**.
- The account-level **Calendar sync** diagnostic
  sensor reports results, pending writes and errors. A diagnostic **Retry calendar sync**
  button can explicitly clear an uncertain write after the destination has been repaired.
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

1. First configure a writable destination calendar integration in Home Assistant. A Local
   Calendar works directly. For Google, complete the dedicated setup below first.
2. Open **Settings → Devices & services → Somtoday → Configure** (options).
3. Select a child and enable the school-day appointment, individual lesson appointments,
   published holiday appointments, or any combination. Submit to continue.
4. Choose a destination calendar for each enabled export. Only available calendars supporting
   create and delete are offered. Somtoday's own read-only calendars cannot be destinations.
5. Set titles. The literal `{student}` in a title or prefix is replaced with that child's
   first name. In holiday titles, `{holiday}` becomes Somtoday's published holiday name.
   You may enter a distinctive full name yourself if children share a first name.
6. **Write permissions are required** in the destination integration and at the provider.
   Start with **Days ahead = 1** and verify the actual events in your destination calendar.
   Enabled exports perform real writes; there is no Preview only mode.
7. Repeat configuration for other children. Their saved destinations remain intact.
8. Once the one-day test is correct, increase Days ahead as needed. Interval and days-ahead
   apply to the whole account. Options reload the integration; no HA restart is needed.

On startup, exports wait until Home Assistant has started, followed by a two-minute grace
period for destination calendars. The source calendars remain available. Calendar sync shows
`starting` without a Repairs warning during that period, then refreshes automatically.
Persistent failures after that period still produce a Repairs warning. Integration reloads
also receive the two-minute grace period; unloading cancels the scheduled callback.

**Upgrading from 0.5.0:** Preview only has been removed. Previously enabled destinations
will now receive real writes, even if the old Preview setting was enabled. Disable unwanted
exports before upgrading.

All outputs can use the same family calendar. Identity includes account, child, output
type and source appointment/day, so siblings and output types remain separate.

### Automatic school-day title

Optional, disabled by default and configured separately for each child. When enabled,
all active timetable appointments on a day must have exactly the same non-empty title
(ignoring surrounding whitespace). Breaks and cancelled appointments do not count.
The shared title then replaces the normal school-day title in both the HA Schooldag
calendar and the school-day export. Individual lessons and holidays are unchanged.

Text before the first underscore is removed; remaining underscores become spaces,
repeated whitespace is collapsed and capitalization is preserved. For example,
`O&O_GaiaZoo_excursie` becomes `GaiaZoo excursie`. `Sportdag` remains `Sportdag`.
The activity title replaces the entire title, including any configured child-name prefix;
calendar entity names still include the child name. Different or missing titles, or an
empty result after formatting, retain the normal title. A single appointment also qualifies.
This detects a shared title, not a confirmed excursion or special day; a day with only
one subject may qualify too. Begin/end times and event ownership do not change.
You can use the HA Schooldag calendar's event title in existing calendar-trigger automations;
no extra binary sensor is added.

### Google Calendar destination setup

1. Add Home Assistant's built-in
   [Google Calendar integration](https://www.home-assistant.io/integrations/google/) and
   select **read/write** in its options. Read-only calendars are deliberately not offered
   as Somtoday destinations.
2. Google Workspace administrators may also need to open **Admin console → Security →
   Access and data control → API controls → Manage App Access**. Locate the exact Home
   Assistant OAuth client ID used under **HA → Settings → Devices & services → Application
   credentials**. Grant **Specific Google data** access to its requested Google Calendar
   scopes for the relevant organizational unit. **Trusted** also works but grants broader
   access than this integration needs.
3. After changing Workspace policy, reauthorize or reload the Google Calendar integration.
   If its former entities say *This entity is no longer being provided*, make a Home
   Assistant backup, remove only the Google Calendar integration entry, and add it again
   with the same account and read/write access. Google Calendar data is not deleted by
   removing the HA integration. Do not manually delete the orphaned entities first.
4. Verify writes independently under **Developer Tools → Actions** before enabling the
   Somtoday export:

   ```yaml
   action: google.create_event
   target:
     entity_id: calendar.your_calendar
   data:
     summary: Home Assistant write test
     start_date_time: "2026-09-11 20:00:00"
     end_date_time: "2026-09-11 20:30:00"
   ```

Somtoday automatically uses `google.create_event` for Google Calendar entities and
`calendar.create_event` for other writable calendar integrations. Google may take up to
15 minutes to return a newly created event through Home Assistant's local calendar cache;
Somtoday records the write as pending and does not create a duplicate while it waits.

## Synchronization behavior and limits

- Reads from today up to the selected look-ahead boundary. The source may not have
  published that far ahead. It does not fetch historical schedules or promise an entire term.
- Every published holiday overlapping that window becomes one all-day event. Somtoday's
  inclusive final holiday date is converted to the exclusive end date required by calendar
  providers, so the event covers the complete published range without adding a visible day.
- School-day events include gaps/tussenuren between the first and last lesson.
  Breaks do not define the boundaries. Only appointments classified as timetable/mandatory
  and active are exported; homework and personal appointments are not lesson exports.
- An opaque marker in the description identifies managed events. Do not remove that marker.
  Ordinary appointments and other children's disabled outputs are left alone.
- Identical events are not recreated. Changed events are **replaced**: first create and
  verify the new version, then delete the old one. Google Calendar's HA entity currently
  lacks an update operation. Brief overlap is possible; the event ID changes. Do not attach
  guests, custom reminders or personal notes to managed events; those edits are not preserved.
- Each target calendar is queried once before reconciliation and, only when writes occur,
  once afterwards for the whole batch. The number of agenda reads therefore no longer grows
  with the number of lessons or holidays being created.
- Cancelled/removed lessons and empty school days remove corresponding managed events
  inside the current synchronization window. Past days are left intact. A failed source fetch
  or incomplete pagination prevents synchronization.
- **Changing or disabling a destination does not clean the old calendar.** Remove old
  exported events manually if needed. Reducing the look-ahead leaves events beyond the new
  boundary unchanged. Removing the integration also leaves exported events in place.
- If a calendar write times out, the integration records the uncertain operation persistently.
  It waits until that event is visible before retrying, to avoid duplicate creation after restart.
  If it never becomes visible, synchronization needs investigation; do not repeatedly
  reinstall or edit HA storage. After verifying that the destination contains no matching
  Somtoday event, press the diagnostic **Retry calendar sync** button once. This clears
  uncertain writes and immediately requests reconciliation. A definite provider rejection,
  such as an HA permission error, is cleared automatically and can be retried after repair.
- Target failures appear in **Calendar sync**; the source roster is kept available.
  Some calendar providers have delayed read-after-write behavior. Google Calendar and Local
  Calendar are supported routes; automated adapter tests do not prove live account permissions.
  Other providers need create, delete and UID-bearing event-query features.

## Calendar provider compatibility

Somtoday uses Home Assistant's calendar contract wherever possible. It lists available
entities advertising **CREATE_EVENT and DELETE_EVENT**; this is a capability check, not
proof that a remote server will accept a write. Providers check actual permissions during
creation. Somtoday has no access to your other accounts' credentials and does not create
test appointments in every calendar while you open the form.

| Calendar | Route | Setup and limitations |
| --- | --- | --- |
| Google / Workspace | Built-in Google Calendar; `google.create_event` | Enable read/write and grant OAuth Calendar access. Workspace policy may require explicitly permitting this OAuth client. See the Google destination section above. |
| Local Calendar | Built-in Local Calendar; `calendar.create_event` | Add a Local Calendar in HA; no external credentials. Supports full reconciliation. |
| Outlook / Microsoft 365 | [MS365 Calendar](https://github.com/RogerSelwyn/MS365-Calendar); `calendar.create_event` | Install the HA custom integration and follow its authentication instructions. Enable updates and grant `Calendars.ReadWrite`; shared calendars need `Calendars.ReadWrite.Shared` plus mailbox access. See [provider permissions](https://github.com/RogerSelwyn/MS365-Calendar/blob/main/docs/permissions.md). Read-only/basic-calendar configurations are unsuitable. |
| Apple iCloud | Built-in CalDAV | Configure `https://caldav.icloud.com/` with an Apple app-specific password. HA 2026.8.2 CalDAV advertises creation only, without deletion: **not a full-sync destination in this release**. Read-only ICS links also cannot receive writes. |
| Nextcloud / ownCloud / Synology / other CalDAV | Built-in CalDAV | Same deletion limitation as iCloud in HA 2026.8.2. A future or alternative HA calendar integration exposing create/delete and event UIDs will be eligible automatically. |
| Other providers | `calendar.create_event` | Eligible automatically when available and advertising create/delete. Provider-specific cloud behavior still needs testing. |

For Apple and CalDAV connection instructions, see the
[Home Assistant CalDAV guide](https://www.home-assistant.io/integrations/caldav/).
Apple Calendar and Outlook can also display a Google calendar: when choosing an export
destination, select the entity belonging to the underlying calendar service.

Verify a selected calendar in Developer Tools → Actions with `calendar.create_event`
(or `google.create_event` for Google), using a disposable event, then confirm it in the
provider's own app. Remove that test event afterwards. If the provider rejects a write,
repair its authentication/permissions first. Repeated creation attempts can make duplicates.
Google's cache normally refreshes every 15 minutes; this is not a guaranteed maximum during
an outage. A successful write and visibility in HA are separate checks.

Do not revoke a working Google grant as a routine setup step. If reauthentication is
required, use HA's reauthentication prompt first. Recreating an integration is a last resort:
take a backup and record entity IDs, then check automation and Somtoday destinations afterwards.
OAuth scopes shown in Google account settings alone do not establish the cause of a 403.

## Reauthentication, repairs and diagnostics

Expired Somtoday authorization raises HA's native reauthentication flow. Open the prompt
in Settings → Repairs, complete the browser/callback login with the same account, and the
existing config entry is updated in place. Child identities must match; account changes are
rejected to avoid accidentally exporting another child's schedule. Existing entity IDs,
options and event markers are preserved. Temporary token-service/network outages retry
without requesting a fresh login.

Calendar export failures create a Repairs warning with a help link. Repair the destination
connection first. Only use **Retry calendar sync** after checking that an uncertain event
was not created remotely; a generic timeout/error does not prove rejection. Structured HTTP
rejections such as 403 can be retried automatically after permissions are repaired.

**Download diagnostics** contains only allowlisted counts, version and polling
settings. It excludes credentials, identifiers, names, event contents and raw exception text.

## Published holidays and school-free days

Each child has a **Published holiday** binary sensor (`mdi:beach`). It fetches Somtoday's
`/rest/v1/vakanties/leerling/[id]` every six hours and evaluates today's date on every roster
refresh. `on` means today falls inside a published holiday range (inclusive end date).
`off` means no returned range covers today, **not** proof that lessons are published.
`unavailable` means the optional endpoint was inaccessible or returned invalid data.
An empty timetable is never turned into a holiday. Study days are recognized only if the
school publishes them through this endpoint; no inferred weekends or national holidays.

To suppress a routine alarm on published holidays, require the sensor to be `off`; this
also prevents an alarm when holiday data is unavailable. Combine this with an actual
school-day event for alarms that require confirmed lessons. This release does not alter
your automations or remove lessons based on holiday information. Endpoint schema is tested
against the [documented sample](https://github.com/elisaado/somtoday-api-docs#vakanties-get-restv1vakantiesleerlingid);
live availability varies by school and parent/child account.

The same data can be exported through **Configure → Enable published holiday appointments**.
Choose a destination per child and optionally use `{student}` and `{holiday}` in the title.
One published range creates one multi-day all-day event—not one event per vacation day.
If the optional holiday endpoint becomes unavailable, existing exported holiday events are
preserved and no absence is inferred. The next valid Somtoday response resumes reconciliation.
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
