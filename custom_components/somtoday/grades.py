"""Latest grades from the pupil's progress file (voortgangsdossier).

The pupil portal's "Laatste cijfers" page reads
``/rest/v1/geldendvoortgangsdossierresultaten/leerling/{id}`` with these column
types and sorts by entry date, newest first. Each item carries the formatted
result as shown in the app ("5,8", or a label such as "+"), the weight and
whether it counts as sufficient.
"""

from __future__ import annotations

from typing import Any

GRADE_TYPES = ("Toetskolom", "DeeltoetsKolom", "Werkstukcijferkolom", "Advieskolom")


def grade_params() -> list[tuple[str, str]]:
    params = [("type", value) for value in GRADE_TYPES]
    params += [("additional", "vaknaam"), ("additional", "resultaatkolom")]
    params.append(("sort", "desc-geldendResultaatCijferInvoer"))
    return params


def normalize_grades(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return compact grade dicts, newest first; items without a result are skipped."""
    result = []
    for item in items:
        if not isinstance(item, dict):
            continue
        shown = str(item.get("formattedResultaat") or "").strip()
        if not shown:
            continue
        value = item.get("cijfer")
        result.append({
            "vak": str((item.get("additionalObjects") or {}).get("vaknaam") or ""),
            "resultaat": shown,
            "cijfer": None if item.get("isLabel") or value is None else float(value),
            "voldoende": bool(item.get("isVoldoende", True)),
            "weging": item.get("weging"),
            "omschrijving": str(item.get("omschrijving") or ""),
            "toetscode": item.get("toetscode"),
            "periode": item.get("periode"),
            "herkansing": item.get("herkansing"),
            "datum": item.get("datumInvoerEerstePoging"),
        })
    result.sort(key=lambda grade: str(grade["datum"] or ""), reverse=True)
    return result
