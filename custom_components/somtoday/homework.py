"""Homework normalization and conservative HA to-do synchronization."""
from __future__ import annotations

import asyncio
from datetime import date, datetime
import hashlib

from homeassistant.components.todo import TodoListEntityFeature as Feature
from homeassistant.helpers.storage import Store

from .assessments import _subject
from .export import item_id
from .models import parse_datetime

STATUSES = ("needs_action", "completed")


def compatible(state):
    """Capabilities are not proof of provider/account write permission."""
    if state is None or getattr(state, "state", None) in ("unknown", "unavailable"):
        return False
    features = state.attributes.get("supported_features", 0)
    required = Feature.CREATE_TODO_ITEM | Feature.UPDATE_TODO_ITEM | Feature.SET_DESCRIPTION_ON_ITEM
    return isinstance(features, int) and features & required == required


def completion(assignment, student):
    """Never copy a sibling's completion flag."""
    additional = assignment.get("additionalObjects") or {}
    wrapper = additional.get("swigemaaktVinkjes")
    if isinstance(wrapper, dict) and isinstance(wrapper.get("items"), list):
        matches = [
            value.get("gemaakt") for value in wrapper["items"]
            if isinstance(value, dict) and item_id(value.get("leerling") or {}) == student
            and isinstance(value.get("gemaakt"), bool)
        ]
        if matches:
            return matches[0] if all(value == matches[0] for value in matches) else None
    # Aggregate huiswerkgemaakt may describe another pupil in parent accounts.
    return None


def normalize_homework(assignments, student, first, last):
    """Use only explicit dates; weekly assignments remain undated."""
    result, seen = [], set()
    for assignment in assignments:
        identifier = item_id(assignment)
        study = assignment.get("studiewijzerItem") or {}
        if not identifier or identifier in seen or study.get("huiswerkType") != "HUISWERK":
            continue
        if study.get("tonen") is False:
            continue
        seen.add(identifier)
        source = assignment.get("_somtoday_assignment_kind")
        due = None
        raw = assignment.get("datumTijd")
        if source in ("appointment", "day") and raw:
            try:
                due = parse_datetime(str(raw))
                if source == "day":
                    due = due.date()
            except (ValueError, TypeError):
                due = None
        day = due.date() if isinstance(due, datetime) else due
        if day is not None and not first <= day < last:
            continue
        result.append({
            "id": identifier, "subject": _subject(assignment),
            "topic": str(study.get("onderwerp") or "").strip(),
            "description": str(study.get("omschrijving") or "").strip(),
            "due": due, "made": completion(assignment, student),
        })
    return result


def marker_for(entry, student, assignment):
    digest = hashlib.sha256(f"{entry}:{student}:{assignment}".encode()).hexdigest()
    return f"[somtoday-homework:{digest}]"


def task_fields(value, name, template, marker, features):
    """No fabricated midnight deadline for date-only assignments."""
    title = template
    for key, text in (("student", name), ("subject", value["subject"]), ("topic", value["topic"])):
        title = title.replace("{" + key + "}", text)
    description = value["description"]
    due = value["due"]
    fields = {"description": description + "\n\n" + marker}
    if isinstance(due, datetime) and features & Feature.SET_DUE_DATETIME_ON_ITEM:
        fields["due_datetime"] = due.isoformat()
    elif due is not None and features & Feature.SET_DUE_DATE_ON_ITEM:
        fields["due_date"] = (due.date() if isinstance(due, datetime) else due).isoformat()
        if isinstance(due, datetime):
            fields["description"] = f"{description}\n\nDue: {due.isoformat()}\n\n{marker}"
    else:
        if features & Feature.SET_DUE_DATE_ON_ITEM:
            fields["due_date"] = None
        elif features & Feature.SET_DUE_DATETIME_ON_ITEM:
            fields["due_datetime"] = None
        if due is not None:
            fields["description"] = f"{description}\n\nDue: {due.isoformat()}\n\n{marker}"
    return title.strip(" ·") or value["subject"], fields


class HomeworkSync:
    """Persist intent before writes. Never retry an uncertain creation."""
    def __init__(self, hass, entry, client):
        self.hass, self.entry, self.client = hass, entry, client
        self.store = Store(hass, 1, f"somtoday_homework_{entry.entry_id}")
        self.records = None
        self.lock = asyncio.Lock()

    async def call(self, action, target, **data):
        async with asyncio.timeout(30):
            return await self.hass.services.async_call(
                "todo", action, {"entity_id": target, **data}, blocking=True,
                return_response=action == "get_items",
            )

    async def run(self, students, assignments, first, last):
        async with self.lock:
            if self.records is None:
                self.records = await self.store.async_load() or {}
            counts = {"mode": "disabled", "created": 0, "updated": 0,
                      "unchanged": 0, "waiting": 0, "errors": 0, "source_updated": 0}
            snapshots = {}
            for pupil in students:
                student = item_id(pupil)
                route = self.entry.options.get("exports", {}).get(student, {})
                target = route.get("homework_list")
                if not target:
                    continue
                counts["mode"] = "enabled"
                state = self.hass.states.get(target)
                if not compatible(state) or assignments.get(student) is None:
                    counts["waiting"] += 1
                    continue
                try:
                    if target not in snapshots:
                        response = await self.call("get_items", target)
                        items = response.get(target, {}).get("items") if isinstance(response, dict) else None
                        if not isinstance(items, list):
                            raise ValueError("Invalid task snapshot")
                        snapshots[target] = items
                    for value in normalize_homework(assignments[student], student, first, last):
                        await self.sync_item(student, pupil, route, state, value, snapshots[target], counts)
                except Exception:
                    # Provider exception messages can contain private URLs/content.
                    counts["errors"] += 1
            if counts["errors"]:
                counts["mode"] = "error"
            elif counts["waiting"]:
                counts["mode"] = "waiting"
            return counts

    async def sync_item(self, student, pupil, route, state, value, items, counts):
        target = route["homework_list"]
        marker = marker_for(self.entry.entry_id, student, value["id"])
        key = target + ":" + marker
        matches = [item for item in items if marker in str(item.get("description") or "")]
        if len(matches) > 1:
            counts["errors"] += 1
            return  # Never guess which duplicate is owned/canonical.
        title, fields = task_fields(value, str(pupil.get("roepnaam") or student),
                                   route.get("homework_title", "{student} · {subject} · {topic}"),
                                   marker, state.attributes.get("supported_features", 0))
        record = self.records.get(key)
        if not matches:
            if record is not None:
                counts["waiting"] += 1
                return
            self.records[key] = {"creating": True}
            await self.store.async_save(self.records)
            await self.call("add_item", target, item=title, **fields)
            counts["created"] += 1
            return  # Discover UID and completion on the next snapshot.
        item = matches[0]
        if not item.get("uid") or item.get("status") not in STATUSES:
            counts["errors"] += 1
            return
        if record is None:
            record = {}
            self.records[key] = record
        record.pop("creating", None)
        current = item["status"] == "completed"
        source = value["made"]
        bidirectional = route.get("homework_bidirectional", False)
        if not bidirectional:
            record.pop("source_pending", None)
        if "source_pending" in record:
            if source != record["source_pending"]:
                counts["waiting"] += 1
                return  # Await read-back; do not overwrite with stale source data.
            record.pop("source_pending")
            record["source"] = source
            record["target"] = source
        if "target_pending" in record:
            if current != record["target_pending"]:
                counts["waiting"] += 1
                return
            record.pop("target_pending")
            record["target"] = current
        desired = current
        # Source wins first import and simultaneous changes. Unknown != incomplete.
        if source is not None and ("source" not in record or source != record["source"] or not bidirectional):
            desired = source
        elif bidirectional and source is not None and "target" in record and current != record["target"]:
            record["source_pending"] = current
            await self.store.async_save(self.records)
            await self.client.set_homework_done(student, value["id"], current)
            counts["source_updated"] += 1
            return
        update = {}
        if item.get("summary") != title:
            update["rename"] = title
        if item.get("description") != fields["description"]:
            update["description"] = fields["description"]
        for field in ("due_date", "due_datetime"):
            if field in fields and item.get("due") != fields[field]:
                update[field] = fields[field]
        if desired != current:
            update["status"] = STATUSES[int(desired)]
            record["target_pending"] = desired
        record["source"] = source
        record["target"] = desired
        await self.store.async_save(self.records)
        if update:
            await self.call("update_item", target, item=item["uid"], **update)
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1
