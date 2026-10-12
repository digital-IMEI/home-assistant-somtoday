from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.somtoday.live_activity import activity_view, subject_icon
from custom_components.somtoday.switch import SomtodayLiveActivitySwitch, async_setup_entry

TZ = ZoneInfo("Europe/Amsterdam")


def at(clock, day="2026-10-12"):
    return datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=TZ)


def lesson(start, end, subject="Wiskunde", room="B104", **extra):
    return {
        "beginDatumTijd": at(start).isoformat(),
        "eindDatumTijd": at(end).isoformat(),
        "additionalObjects": {"vak": {"naam": subject}},
        "afspraakType": {"categorie": "Rooster"},
        "locatie": room,
        **extra,
    }


SCHEDULE = [lesson("09:45", "10:35"), lesson("10:40", "11:30", "Engels", "C203")]


@pytest.mark.parametrize("clock,phase,next_time,room", [
    ("09:29:59", "idle", "09:30", ""),
    ("09:30", "before_school", "09:45", "B104"),
    ("09:45", "lesson", "10:30", "C203"),
    ("10:12", "lesson", "10:30", "C203"),
    ("10:30", "leaving", "10:35", "C203"),
    ("10:35", "break", "10:40", "C203"),
    ("10:40", "lesson", "11:25", "—"),
    ("11:30", "finished", "11:40", "—"),
    ("11:40", "idle", "00:00", ""),
])
def test_exact_school_day_boundaries(clock, phase, next_time, room):
    view = activity_view(SCHEDULE, at(clock))
    assert view.phase == phase
    assert view.room == room
    assert view.next_change.strftime("%H:%M") == next_time
    assert view.next_change > at(clock)


def test_option_one_content_and_five_minute_emphasis():
    assert activity_view(SCHEDULE, at("10:12")).message == (
        "Nu: Wiskunde · lokaal B104 · tot 10:35\nHierna: Engels · om 10:40"
    )
    assert activity_view(SCHEDULE, at("10:30")).message == (
        "Nu: Wiskunde · lokaal B104 · tot 10:35\nHierna: Engels · om 10:40"
    )
    assert activity_view(SCHEDULE, at("10:35")).message == (
        "Pauze tot 10:40\nHierna: Engels · om 10:40"
    )


def test_cancelled_break_invalid_and_other_day_entries_are_not_destinations():
    tomorrow = lesson("10:40", "11:30", "Tomorrow", "X999")
    for key in ("beginDatumTijd", "eindDatumTijd"):
        tomorrow[key] = tomorrow[key].replace("2026-10-12", "2026-10-13")
    schedule = [SCHEDULE[0],
        lesson("10:40", "11:30", "Cancelled", "X998", afspraakStatus="VERVALLEN"),
        lesson("10:35", "10:40", "Pauze", "X997"),
        lesson("11:30", "11:00", "Invalid", "X996"),
        {"beginDatumTijd": "bad"},
        {"beginDatumTijd": "2026-10-12T10:40", "eindDatumTijd": "2026-10-12T11:30"},
        tomorrow,
    ]
    view = activity_view(schedule, at("10:12"))
    assert view.room == "—"
    assert view.message.endswith("Laatste les vandaag")
    assert activity_view(schedule, at("10:35")).phase == "finished"


def test_utc_dates_are_compared_in_local_timezone():
    # UTC Sunday is already Monday in the student's local timezone.
    schedule = [{"beginDatumTijd": "2026-10-11T22:10:00Z", "eindDatumTijd": "2026-10-11T23:00:00Z", "titel": "Late lesson", "locatie": "A1", "afspraakType": {"categorie": "Rooster"}}]
    view = activity_view(schedule, at("00:05"))
    assert view.phase == "before_school"
    assert view.room == "A1"


def test_empty_weekend_and_room_unknown():
    assert activity_view([], at("10:12")).message is None
    assert activity_view(SCHEDULE, at("10:12", "2026-10-17")).message is None
    view = activity_view([lesson("09:45", "10:35", room="")], at("09:30"))
    assert view.room == "—"
    assert "onbekend" in view.message


def test_english_card():
    view = activity_view(SCHEDULE, at("10:12"), "en")
    assert view.message == "Now: Wiskunde · room B104 · until 10:35\nNext: Engels · at 10:40"


def make_switch(monkeypatch, now="10:12", targets=None):
    coordinator = SimpleNamespace(last_update_success=True, data={"appointments_by_student": {"a": list(SCHEDULE)}})
    entry = SimpleNamespace(entry_id="entry", options={"exports": {"a": {
        "live_activity_targets": targets or ["notify.mobile_app_seth"],
    }}})
    switch = SomtodayLiveActivitySwitch(coordinator, entry, {"links": [{"id": "a"}], "roepnaam": "Seth"})
    switch.hass = SimpleNamespace(data={}, services=SimpleNamespace(async_call=AsyncMock()))
    switch.async_write_ha_state = Mock()
    switch._schedule = Mock()
    monkeypatch.setattr("custom_components.somtoday.switch.dt_util.now", lambda: at(now))
    return switch


@pytest.mark.asyncio
async def test_switch_off_clears_and_no_duplicate_pushes(monkeypatch):
    switch = make_switch(monkeypatch)
    await switch.async_turn_on()
    notify = switch.hass.services.async_call
    assert notify.await_count == 1
    payload = notify.call_args.args[2]
    assert payload["title"] == "Seth · Volgend lokaal"
    assert payload["message"].startswith("Nu: Wiskunde")
    assert payload["data"]["critical_text"] == "C203"
    assert payload["data"]["live_update"] is True
    assert payload["data"]["url"] == "somtoday://"
    assert payload["data"]["background_color"] == "transparent"
    assert "text_color" not in payload["data"]
    assert payload["data"]["notification_icon"] == "mdi:calculator-variant"
    assert "progress" not in payload["data"]
    assert "chronometer" not in payload["data"]
    assert "silent" not in payload["data"]
    assert switch._schedule.call_args.args[0] == 18 * 60
    await switch._async_refresh()
    assert notify.await_count == 1
    await switch.async_turn_off()
    assert notify.await_count == 2
    assert notify.call_args.args[2] == {"message": "clear_notification", "data": {"tag": switch.tag}}
    assert switch.is_on is False
    await switch._async_refresh()
    assert notify.await_count == 2


@pytest.mark.asyncio
async def test_clock_transition_does_not_wait_for_api_and_room_changes_push(monkeypatch):
    switch = make_switch(monkeypatch)
    await switch.async_turn_on()
    monkeypatch.setattr("custom_components.somtoday.switch.dt_util.now", lambda: at("10:35"))
    await switch._timer_fired(None)
    assert switch.hass.services.async_call.call_args.args[2]["message"].startswith("Pauze")
    switch.coordinator.data["appointments_by_student"]["a"][1] = lesson("10:40", "11:30", "Engels", "C204")
    await switch._async_refresh()
    assert switch.hass.services.async_call.call_args.args[2]["data"]["critical_text"] == "C204"


@pytest.mark.asyncio
async def test_failed_device_retries_without_resending_successful_device(monkeypatch):
    switch = make_switch(monkeypatch, targets=["notify.mobile_app_seth", "notify.mobile_app_ivo"])
    notify = switch.hass.services.async_call
    notify.side_effect = [None, HomeAssistantError("Delivery failed")]
    await switch.async_turn_on()
    assert switch.extra_state_attributes["failed_targets"] == 1
    assert switch._schedule.call_args.args[0] == 60
    notify.side_effect = None
    await switch._async_refresh()
    assert notify.await_count == 3
    assert notify.call_args.args[1] == "mobile_app_ivo"
    assert switch.extra_state_attributes["failed_targets"] == 0


@pytest.mark.asyncio
async def test_source_failure_removes_stale_destination_and_recovers(monkeypatch):
    switch = make_switch(monkeypatch)
    await switch.async_turn_on()
    switch.coordinator.last_update_success = False
    await switch._async_refresh()
    payload = switch.hass.services.async_call.call_args.args[2]
    assert payload["data"]["critical_text"] == "—"
    assert "niet beschikbaar" in payload["message"]
    switch.coordinator.last_update_success = True
    await switch._async_refresh()
    assert switch.hass.services.async_call.call_args.args[2]["data"]["critical_text"] == "C203"


@pytest.mark.asyncio
async def test_source_failure_does_not_start_new_activity(monkeypatch):
    switch = make_switch(monkeypatch)
    switch.coordinator.last_update_success = False
    await switch.async_turn_on()
    assert switch.hass.services.async_call.call_args.args[2]["message"] == "clear_notification"


@pytest.mark.asyncio
async def test_source_outage_does_not_keep_card_alive_after_school(monkeypatch):
    switch = make_switch(monkeypatch)
    await switch.async_turn_on()
    switch.coordinator.last_update_success = False
    monkeypatch.setattr("custom_components.somtoday.switch.dt_util.now", lambda: at("11:40"))
    await switch._async_refresh()
    assert switch.hass.services.async_call.call_args.args[2]["message"] == "clear_notification"


@pytest.mark.asyncio
async def test_all_cancelled_lessons_clear_active_card(monkeypatch):
    switch = make_switch(monkeypatch)
    await switch.async_turn_on()
    switch.coordinator.data["appointments_by_student"]["a"] = []
    await switch._async_refresh()
    assert switch.hass.services.async_call.call_args.args[2]["message"] == "clear_notification"
    assert switch.is_on  # Remains armed for the next school day.


@pytest.mark.asyncio
async def test_long_day_renews_near_ios_expiry(monkeypatch):
    switch = make_switch(monkeypatch, now="08:00")
    switch.coordinator.data["appointments_by_student"]["a"] = [lesson("08:00", "18:00")]
    await switch.async_turn_on()
    assert switch._schedule.call_args.args[0] == (7 * 60 + 55) * 60
    monkeypatch.setattr("custom_components.somtoday.switch.dt_util.now", lambda: at("15:55"))
    await switch._async_refresh()
    calls = switch.hass.services.async_call.call_args_list
    assert len(calls) == 3
    assert calls[1].args[2]["message"] == "clear_notification"
    assert calls[2].args[2]["data"]["live_update"]


@pytest.mark.asyncio
async def test_per_child_switches_only_exist_for_configured_children():
    coordinator = SimpleNamespace(data={"students": [
        {"links": [{"id": "a"}], "roepnaam": "Seth"},
        {"links": [{"id": "b"}], "roepnaam": "Other"},
    ]})
    hass = SimpleNamespace(data={"somtoday": {"entry": coordinator}})
    entry = SimpleNamespace(entry_id="entry", options={"exports": {"a": {"live_activity_targets": ["notify.mobile_app_seth"]}}})
    added = Mock()
    await async_setup_entry(hass, entry, added)
    assert len(added.call_args.args[0]) == 1
    assert added.call_args.args[0][0].unique_id == "entry_a_live_activity"
    other = SomtodayLiveActivitySwitch(coordinator, entry, {"links": [{"id": "b"}]})
    assert other.tag != added.call_args.args[0][0].tag


@pytest.mark.asyncio
async def test_failed_clear_remains_retryable_when_off(monkeypatch):
    switch = make_switch(monkeypatch)
    await switch.async_turn_on()
    notify = switch.hass.services.async_call
    notify.side_effect = HomeAssistantError("No network")
    await switch.async_turn_off()
    assert not switch.is_on
    assert switch._schedule.call_args.args[0] == 60
    notify.side_effect = None
    await switch._async_refresh()
    assert notify.call_args.args[2]["message"] == "clear_notification"
    assert switch.extra_state_attributes["failed_targets"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("previous,on", [(None, False), ("on", True), ("off", False)])
async def test_switch_restores_state_and_registers_lifecycle_hooks(monkeypatch, previous, on):
    from homeassistant.helpers.restore_state import RestoreEntity

    switch = make_switch(monkeypatch)
    monkeypatch.setattr(RestoreEntity, "async_added_to_hass", AsyncMock())
    switch.async_get_last_state = AsyncMock(return_value=SimpleNamespace(state=previous) if previous else None)
    switch.async_on_remove = Mock()
    unsubscribe = Mock()
    switch.coordinator.async_add_listener = Mock(return_value=unsubscribe)
    await switch.async_added_to_hass()
    assert switch.is_on is on
    assert switch._restart_targets == (set(switch.targets) if on else set())
    switch.coordinator.async_add_listener.assert_called_once_with(switch._source_updated)
    assert switch.async_on_remove.call_args_list[0].args == (unsubscribe,)
    switch._schedule.assert_called_once_with(1)


@pytest.mark.asyncio
async def test_unload_cancels_timer_and_clears_without_changing_restored_switch_state(monkeypatch):
    from homeassistant.helpers.restore_state import RestoreEntity

    switch = make_switch(monkeypatch)
    monkeypatch.setattr(RestoreEntity, "async_will_remove_from_hass", AsyncMock())
    await switch.async_turn_on()
    cancel = Mock()
    switch._cancel_timer = cancel
    await switch.async_will_remove_from_hass()
    cancel.assert_called_once()
    assert switch.is_on
    assert switch.hass.services.async_call.call_args.args[2]["message"] == "clear_notification"
    count = switch.hass.services.async_call.await_count
    await switch._async_refresh()
    assert switch.hass.services.async_call.await_count == count


def register_phone(switch, service, os_name, webhook="phone"):
    mobile_app = switch.hass.data.setdefault("mobile_app", {})
    mobile_app.setdefault("notify", SimpleNamespace(registered_targets={})).registered_targets[service] = webhook
    mobile_app.setdefault("config_entries", {})[webhook] = SimpleNamespace(data={"os_name": os_name})


@pytest.mark.asyncio
async def test_android_payload_contains_next_room_and_silent_persistent_channel(monkeypatch):
    switch = make_switch(monkeypatch)
    register_phone(switch, "mobile_app_seth", "Android")
    await switch.async_turn_on()
    payload = switch.hass.services.async_call.call_args.args[2]
    assert payload["message"] == "Nu: Wiskunde · lokaal B104 · tot 10:35\nHierna: Engels · om 10:40 · lokaal C203"
    data = payload["data"]
    assert data["critical_text"] == "C203"
    assert data["live_update"] is True
    assert data["persistent"] is True
    assert data["sticky"] is True
    assert data["alert_once"] is True
    assert data["importance"] == "low"
    assert data["channel"] == "Somtoday timetable"
    assert data["clickAction"] == "app://nl.topicus.somtoday.leerling"
    assert data["priority"] == "high" and data["ttl"] == 0
    assert not {"push", "background_color", "text_color", "chronometer", "progress"}.intersection(data)
    await switch._async_refresh()
    assert switch.hass.services.async_call.await_count == 1
    await switch.async_turn_off()
    clear = switch.hass.services.async_call.call_args.args[2]
    assert clear == {"message": "clear_notification", "data": {"tag": switch.tag, "priority": "high", "ttl": 0}}


@pytest.mark.asyncio
async def test_mixed_android_ios_targets_receive_their_own_payloads(monkeypatch):
    switch = make_switch(monkeypatch, targets=["notify.mobile_app_seth", "notify.mobile_app_ivo"])
    register_phone(switch, "mobile_app_seth", "Android", "android-phone")
    register_phone(switch, "mobile_app_ivo", "iOS", "ios-phone")
    await switch.async_turn_on()
    android, ios = [call.args[2] for call in switch.hass.services.async_call.call_args_list]
    assert android["message"].endswith(" · lokaal C203")
    assert ios["message"].endswith(" · om 10:40")
    assert "push" in ios["data"] and "channel" not in ios["data"]
    assert android["data"]["tag"] == ios["data"]["tag"]
    await switch._async_refresh()
    assert switch.hass.services.async_call.await_count == 2


@pytest.mark.asyncio
async def test_android_long_day_does_not_restart_at_ios_expiry(monkeypatch):
    switch = make_switch(monkeypatch, now="08:00")
    register_phone(switch, "mobile_app_seth", "Android")
    switch.coordinator.data["appointments_by_student"]["a"] = [lesson("08:00", "18:00")]
    await switch.async_turn_on()
    assert switch._schedule.call_args.args[0] == (9 * 60 + 55) * 60
    monkeypatch.setattr("custom_components.somtoday.switch.dt_util.now", lambda: at("15:55"))
    await switch._async_refresh()
    assert switch.hass.services.async_call.await_count == 1


def test_platform_is_resolved_by_registered_target_not_phone_name(monkeypatch):
    switch = make_switch(monkeypatch)
    register_phone(switch, "mobile_app_iphone_named_android", "iOS", "1")
    register_phone(switch, "mobile_app_iphone", "Android", "2")
    assert switch._platform("notify.mobile_app_iphone_named_android") == "ios"
    assert switch._platform("notify.mobile_app_iphone") == "android"
    assert switch._platform("notify.mobile_app_missing") == "unknown"


def test_android_missing_next_room_is_explicit_in_message():
    schedule = [SCHEDULE[0], lesson("10:40", "11:30", "Engels", "")]
    view = activity_view(schedule, at("10:12"), include_next_room=True)
    assert view.message.endswith("Hierna: Engels · om 10:40 · Lokaal onbekend")
    assert view.room == "—"


@pytest.mark.parametrize("subject,expected", [
    ("Nederlandse taal", "mdi:book-open-page-variant"),
    ("Latijnse taal en letterkunde", "mdi:pillar"),
    ("lichamelijke opvoeding", "mdi:run"),
    ("digitale geletterdheid", "mdi:laptop"),
    ("geschiedenis", "mdi:pillar"),
    ("Onbekend vak", "mdi:book-open-page-variant"),
])
def test_subject_icons_cover_full_school_names(subject, expected):
    assert subject_icon(subject) == expected


def test_main_icon_changes_with_phase_and_individual_appointments_are_not_lessons():
    individual = lesson("10:12", "15:00", "proefwerk Nederlands", "Wrong room", afspraakType={"categorie": "Individueel"})
    schedule = SCHEDULE + [individual]
    assert activity_view(schedule, at("10:12")).icon == "mdi:calculator-variant"
    assert activity_view(schedule, at("10:30")).icon == "mdi:translate"
    assert activity_view(schedule, at("10:35")).icon == "mdi:coffee-outline"
    assert activity_view(schedule, at("09:30")).icon == "mdi:bag-personal"
    assert activity_view(schedule, at("11:30")).icon == "mdi:check-circle-outline"
    assert 'Wrong room' not in activity_view(schedule, at("10:12")).message
    assert activity_view([individual], at("10:12")).phase == "idle"


@pytest.mark.asyncio
async def test_old_static_title_is_restarted_once_without_repeated_pushes(monkeypatch):
    switch = make_switch(monkeypatch)
    switch._attr_is_on = True
    switch._restart_targets = set(switch.targets)
    assert switch.extra_state_attributes["layout"] == "pending"
    await switch._async_refresh()
    calls = switch.hass.services.async_call.call_args_list
    assert len(calls) == 2
    assert calls[0].args[2]["message"] == "clear_notification"
    assert calls[1].args[2]["title"] == "Seth · Volgend lokaal"
    assert switch.extra_state_attributes["layout"] == "next_room_v1"
    await switch._async_refresh()
    assert switch.hass.services.async_call.await_count == 2


@pytest.mark.asyncio
async def test_failed_title_migration_retries_before_creating_new_card(monkeypatch):
    switch = make_switch(monkeypatch)
    switch._attr_is_on = True
    switch._restart_targets = set(switch.targets)
    notify = switch.hass.services.async_call
    notify.side_effect = [HomeAssistantError("offline"), None, None]
    await switch._async_refresh()
    assert switch.extra_state_attributes["layout"] == "pending"
    assert notify.await_count == 1
    await switch._async_refresh()
    assert notify.await_count == 3
    assert switch.extra_state_attributes["layout"] == "next_room_v1"


def test_text_has_consistent_current_and_next_lines_without_decorative_icons():
    view = activity_view(SCHEDULE, at("10:30"))
    assert view.message.splitlines() == [
        "Nu: Wiskunde · lokaal B104 · tot 10:35", "Hierna: Engels · om 10:40"]
    assert view.room == "C203"
    assert activity_view(SCHEDULE, at("10:35")).message == "Pauze tot 10:40\nHierna: Engels · om 10:40"
    assert activity_view(SCHEDULE, at("11:30")).message == "Klaar voor vandaag"
