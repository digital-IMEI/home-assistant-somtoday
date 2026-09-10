# Somtoday for Home Assistant

Experimental Home Assistant integration for retrieving a student's Somtoday schedule.

> This project uses an unofficial API and is not affiliated with Topicus or Somtoday.

## Current prototype

- Finds the Somtoday school organization.
- Uses the school's advertised SSO provider with OAuth 2.0 PKCE.
- Stores refresh/access tokens in the Home Assistant config entry; it never asks Home Assistant to store the school password.
- Verifies the login by fetching the students visible to the account.
- Fetches active schedule appointments every 15 minutes.
- Creates a Home Assistant calendar entity with the individual appointments.
- Calculates a school-day sensor from the first to the last active, mandatory timetable appointment.

Google Calendar synchronization is intentionally not enabled in this first authentication prototype. It will only be added after Sophianum's live SSO callback and schedule payload have been verified.

## Installation for testing

1. Copy `custom_components/somtoday` into Home Assistant's `config/custom_components` directory.
2. Restart Home Assistant.
3. Add the **Somtoday** integration.
4. Search for `Sophianum`. If Somtoday lists the school under its board instead, search for `LVO` and select the organization used by the account.
5. After login, copy the entire `somtodayleerling://...` callback URL into Home Assistant.

## Status

This is version `0.1.0`, intended to validate Sophianum's live authentication flow and response format before Google Calendar write support is added.

## Privacy and security

The school password is entered only on the school's own identity-provider page. Home Assistant stores the resulting OAuth refresh/access tokens in its config entry. Treat Home Assistant backups as sensitive.
