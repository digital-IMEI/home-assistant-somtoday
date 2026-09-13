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
- Export published Somtoday holidays using one of three all-day event layouts.
- View explicit Somtoday tests per child, automate reminders and optionally export them.
- Choose all four destination calendars separately **for each child in the account**.
- The account-level **Calendar sync** diagnostic
  sensor reports results, pending writes and errors. A diagnostic **Retry calendar sync**
  button can explicitly clear an uncertain write after the destination has been repaired.
- Adjustable look-ahead (1–60 days; default 14) and polling (5–120 minutes, default 15).
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

On a full Home Assistant start, Somtoday waits until HA is running and checks configured
destination calendars every five seconds. Reconciliation begins as soon as they are ready;
only an unavailable destination can consume the two-minute maximum startup grace period.
The source calendars remain available and Calendar sync shows `starting` without a Repairs
warning while waiting. A normal options reload starts reconciliation immediately because the
other calendar platforms are already running. Persistent destination failures still produce a
Repairs warning.
Rotated Somtoday tokens are saved without reloading the integration, so calendar entities do
not briefly become unavailable during normal polling. Changing Configure options still reloads
the integration once so the new settings and entities are applied.

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
`PREFIX_Special_activity` becomes `Special activity`. `Sports day` remains `Sports day`.
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
`calendar.create_event` for other writable calendar integrations. Google may take time to
return a newly created event through Home Assistant's local calendar cache. A successful
write is completed immediately: Somtoday records it persistently, removes an outdated
version straight away and does not create a duplicate while HA's cache catches up.

## Synchronization behavior and limits

- Reads from today up to the selected look-ahead boundary. The source may not have
  published that far ahead. It does not fetch historical schedules or promise an entire term.
- Every published holiday overlapping that window uses the selected holiday layout. Somtoday's
  inclusive final holiday date is converted to the exclusive end date required by calendar
  providers, so the event covers the intended dates without adding a visible day.
- School-day events include gaps/tussenuren between the first and last lesson.
  Breaks do not define the boundaries. Only appointments classified as timetable/mandatory
  and active are exported; homework and personal appointments are not lesson exports.
- An opaque marker in the description identifies managed events. Do not remove that marker.
  Ordinary appointments and other children's disabled outputs are left alone.
- Identical events are not recreated. Changed events are **replaced**: the new version is
  created first and the old one is deleted as soon as the write action succeeds. Google
  Calendar's HA entity currently lacks an update operation. The event ID changes. Do not attach
  guests, custom reminders or personal notes to managed events; those edits are not preserved.
- Each target calendar is queried only once per synchronization. A slow provider cache is not
  queried again immediately after writing and therefore cannot hold up reconciliation. After
  a successful batch, Somtoday requests one delayed `homeassistant.update_entity` refresh in
  the background so HA can pick up provider changes sooner without blocking the export.
- Cancelled/removed lessons and empty school days remove corresponding managed events
  inside the current synchronization window. Past days are left intact. A failed source fetch
  or incomplete pagination prevents synchronization.
- **Changing or disabling a destination does not clean the old calendar.** Remove old
  exported events manually if needed. Reducing the look-ahead leaves events beyond the new
  boundary unchanged. Removing the integration also leaves exported events in place.
- Successful writes may temporarily report `awaiting_visibility` in the diagnostic sensor while
  Home Assistant still returns a stale provider cache. This does not delay or fail synchronization.
  If a calendar write times out, the integration records the uncertain operation persistently.
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
Choose one of these layouts:

- **One event · Somtoday dates:** one continuous event from Somtoday's published first date
  through its published final date. This normally excludes the adjacent weekends. A continuous
  multi-week event necessarily still covers weekends inside that range.
- **One event · include surrounding weekends:** expands the published range to the Saturday
  before it and the Sunday after it.
- **One all-day event per Somtoday date:** creates a separate all-day event for every date in
  the published range.

Changing layout replaces managed events in the current synchronization window. It does not
touch ordinary calendar events.
Changing Somtoday options starts reconciliation immediately. During a full Home Assistant start,
Somtoday checks destination readiness every five seconds and starts as soon as all configured
calendars are available. Only an unavailable destination can consume the full two-minute safety
window before a repair is raised.
If the optional holiday endpoint becomes unavailable, existing exported holiday events are
preserved and no absence is inferred. The next valid Somtoday response resumes reconciliation.

## Tests and reminders

Each child receives three assessment-focused entities in addition to the timetable and
school-day calendars:

- **Tests** calendar (`mdi:clipboard-text-clock-outline`) with Somtoday items explicitly typed
  `TOETS` or `GROTE_TOETS`;
- **Next test** timestamp sensor with subject, type, topic, days remaining, all-day state,
  completed state and the number of test assignments for which Somtoday has not published an
  exact date;
- **Test change** event entity (`added`, `changed`, `removed`) for automations that should react
  when the school changes an assignment.

The integration never classifies an item by searching its title for words such as “test”.
Homework is excluded. An appointment assignment is timed only when its date/time and subject
match an actual timetable lesson exactly. Other dated assignments become all-day events. A
week assignment without an exact date is counted and can trigger a change event, but is not put
on a guessed calendar date.

The Somtoday tests calendar is read-only and updates its active HA calendar subscribers after
every successful Somtoday refresh. It is available when the study-guide endpoints are
available. To copy tests to Google Calendar, Outlook or another writable provider, enable
**Export tests to another calendar** per child. The export title supports `{student}`,
`{subject}`, `{type}` and `{topic}`.

Use the HA tests calendar for reminders. For example, this triggers two days before each dated
test; select your own notification action in the UI:

```yaml
triggers:
  - trigger: calendar
    event: start
    entity_id: calendar.seth_toetsen
    offset: "-2 00:00:00"
mode: queued
```

For an all-day test this fires at midnight two days earlier. Use `-1 06:00:00` to fire at
18:00 on the preceding day. Calendar triggers are preferable to watching the calendar's `on`
state because attributes represent only the next event. Home Assistant normally reads calendar
triggers every 15 minutes, so do not create a test event less than 15 minutes before it starts
when validating a reminder.

- Multiple children require the API to identify which child each appointment belongs to.
  If this metadata is missing, the integration pauses rather than mixing school days.
  Newly added children require an integration reload to create their entities.
- Existing first-child entity IDs are retained where possible. Additional entities use stable
  child IDs internally; first-name changes do not change event ownership.

## Privacy and support

Tokens are stored in the HA configuration, never in this repository. Treat backups as private.
Export sends titles, lesson times, child names and locations to your chosen calendar provider.
Grades and messages are not fetched by this version. Ordinary homework may be present in the
study-guide response used to find tests, but is filtered out and is not exposed or exported.

For an issue include integration/HA version, browser, school organization, selected output
mode, sanitized error and whether source times match. Redact names, locations and all auth data.
Do not include raw diagnostics or HAR files. The integration remains experimental while
multi-school and live calendar-provider compatibility are being established.

See [community roadmap](docs/ROADMAP.md) for researched follow-up features and limitations.
