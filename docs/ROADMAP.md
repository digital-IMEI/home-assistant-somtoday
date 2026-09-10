# Community roadmap — researched 10 September 2026

This separates implemented functionality from candidates. Endpoint availability is not a
guarantee of access for every school, pupil or guardian. No additional hardware/software
outside Home Assistant should be required.

| Priority | Candidate | Community value | Evidence / remaining work |
| --- | --- | --- | --- |
| 1 | Tomorrow's start/end, next lesson and school-day binary sensor | Alarms, departure reminders, dashboards | Derivable from the existing schedule; test timezone transitions and missing days |
| 1 | Timetable-change events | Notify only when a first/last lesson or classroom changes | Persist prior snapshots; establish baseline without notification spam; no real-time push is known |
| Implemented 0.4.0 | Reauthentication, repairs and redacted diagnostics | Recover without removing/recreating an account | Native reauth updates credentials in place; destination Repairs warning; allowlisted diagnostics |
| 1 | Calendar sync recovery UI and destination migration | Recover uncertain writes and retire an old destination safely | Needs explicit preview/confirmation and exact event ownership checks; current version deliberately retains old destinations |
| 2 | Tests/homework calendar and HA to-do list | Preparation reminders and a family dashboard | API docs describe appointment/day/week study-guide assignments; all three must be combined and deduplicated |
| Implemented 0.4.0 | Published holidays | Suppress routine alarms | Per-child holiday sensor; unavailable on endpoint failure; empty roster never implies holiday. Live school/account availability remains to be verified. |
| 2 | Optional new-grade indicator | Family notification without exposing a full report | `/rest/v1/resultaten/huidigVoorLeerling/[id]` documented; opt-in and respect guardian visibility, publication state and weighting |
| 3 | Absence overview | Explain a missed lesson | Absence endpoints documented; sensitive data, require opt-in and confirm actual status meanings |
| 3 | Message count | Indicate unread school communication | Conversation endpoint documented; unread semantics and parent access need live verification |
| Defer | Mark homework done | Two-way to-do synchronization | Write endpoints are documented, but conflicts and shared-account effects require explicit design |
| Defer | Report absences / enroll in KWT | School administration actions | Consequential writes, school-specific validation and permissions; not appropriate for an initial community release |

## Not promised

- No bypass for a school's account permissions or disabled data access.
- No guaranteed instantaneous changes: the source is polled, not subscribed to push notifications.
- No reliable prediction of dismissal time from unpublished lessons.
- No arbitrary OAuth redirect URL or guaranteed fully automatic browser callback: the native
  client uses a registered `somtoday://` scheme; browser Developer Tools remain necessary in
  some setups. Avoid external callback collectors that would receive authentication data.
- No grade-average reconstruction without verified school weighting rules.
- No universal calendar-provider compatibility. The first adapter uses HA calendar entities
  with create/delete and UID-bearing reads; provider caches and permissions can differ.

## Sources

- [Somtoday API community documentation](https://github.com/elisaado/somtoday-api-docs):
  schedule, students, results, holidays, assignments, messages and absence endpoint examples.
- [School Buddy's API implementation](https://github.com/joepjoosten/school-buddy/blob/main/apps/daemon/src/Somtoday.ts):
  contemporary PKCE endpoint, rotating refresh tokens, pagination and assignment parsing.
- [Home Assistant calendar entity contract](https://developers.home-assistant.io/docs/core/entity/calendar/):
  supported read/create/update/delete methods and feature flags.
- [Home Assistant Google Calendar source](https://github.com/home-assistant/core/blob/dev/homeassistant/components/google/calendar.py):
  create/delete support, permissions and event UID conversion.
- [Home Assistant Google Calendar setup](https://www.home-assistant.io/integrations/google/).

Test first with anonymized fixtures and HA 2026.8.2, then a disposable writable calendar.
Automated checks are not evidence that every browser, school and live provider works.
