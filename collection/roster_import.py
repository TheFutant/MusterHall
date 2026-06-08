"""Roster-file import parser and planner.

This module is the **isolation seam** for roster importing. It is pure Python —
no Django imports — so the format-specific logic lives in one swappable place and
is trivial to unit-test. When the new edition changes the export format, replace
``parse_roster`` (dispatching on the captured app/data version if needed) and the
rest of the app keeps working.

Pipeline:
  text --parse_roster--> ParsedRoster --plan_import(+match_fn)--> [ImportRow]
``plan_import`` stays pure too: the database-backed faction matching and the set
of already-owned names are injected by the caller (see ``collection.views``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Current known format. Captured app/data versions give a future dispatch hook.
FORMAT = "newrecruit-text-v1"

# Roster faction labels that map to a different canonical Faction name in our
# shared reference data. Kept tiny and obvious; extend via admin/data later.
FACTION_ALIASES = {
    "space marines": "Adeptus Astartes",
}

NAME_MAX_LENGTH = 200  # mirrors CollectionEntry.name max_length

# (N points) appears on the force header, the strike-force line AND every unit
# header, so classification is positional/stateful, not regex alone.
_UNIT_HEADER = re.compile(r"^(?P<name>\S.*?)\s*\((?P<points>\d+)\s*points?\)\s*$", re.IGNORECASE)
_BULLET = re.compile(r"^(?P<indent>\s*)[•\-\*]\s+(?P<content>.*)$")
_NX = re.compile(r"^(?P<n>\d+)\s*x\s+(?P<label>.+)$", re.IGNORECASE)
_FOOTER = re.compile(r"^Exported with App Version", re.IGNORECASE)
_VERSIONS = re.compile(r"App Version:\s*(?P<app>[^,]+).*?Data Version:\s*(?P<data>\S+)", re.IGNORECASE)


@dataclass
class ParsedUnit:
    name: str
    points: int | None
    section: str
    models: int
    warlord: bool = False
    enhancement: str | None = None
    loadout: list[str] = field(default_factory=list)
    raw_block: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ParsedRoster:
    list_name: str | None = None
    total_points: int | None = None
    faction_text: str | None = None
    subfaction_text: str | None = None
    game_size: str | None = None
    points_limit: int | None = None
    detachment_text: str | None = None
    app_version: str | None = None
    data_version: str | None = None
    units: list[ParsedUnit] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ImportRow:
    name: str
    quantity: int
    models_total: int
    section: str
    faction: object | None
    subfaction: object | None
    notes: str
    warnings: list[str] = field(default_factory=list)
    skip: bool = False


def _normalize(text: str) -> str:
    text = text.replace("﻿", "")          # BOM
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(" ", " ")          # non-breaking space
    text = text.replace("×", "x").replace("✕", "x").replace("✖", "x")  # × variants
    return text


def _is_section(line: str) -> bool:
    """ALL-CAPS line with no points/parens, e.g. CHARACTERS, OTHER DATASHEETS."""
    return bool(line) and "(" not in line and line == line.upper() and bool(re.search(r"[A-Z]", line))


def _parse_block(header_line: str, body_lines: list[str], section: str) -> ParsedUnit:
    m = _UNIT_HEADER.match(header_line)
    name = m.group("name").strip()
    points = int(m.group("points"))

    warlord = False
    enhancement = None
    entries: list[tuple[int, str, bool, int]] = []  # (indent, content, is_nx, n)

    for line in body_lines:
        if not line.strip():
            continue
        bm = _BULLET.match(line)
        if bm:
            indent = len(bm.group("indent"))
            content = bm.group("content").strip()
        else:
            indent = len(line) - len(line.lstrip(" "))
            content = line.strip()

        if content == "Warlord":
            warlord = True
            continue
        if content.lower().startswith("enhancement:"):
            enhancement = content.split(":", 1)[1].strip()
            continue

        nx = _NX.match(content)
        if nx:
            entries.append((indent, content, True, int(nx.group("n"))))
        else:
            entries.append((indent, content, False, 0))

    models = 1
    loadout: list[str] = []
    if entries:
        min_indent = min(e[0] for e in entries)

        def has_child(idx: int) -> bool:
            return idx + 1 < len(entries) and entries[idx + 1][0] > entries[idx][0]

        top = [(i, e) for i, e in enumerate(entries) if e[0] == min_indent]
        # A top-level "Nx" bullet with nested wargear is a model line; a vehicle's
        # top-level "Nx" bullets are weapons (no children) -> single model.
        model_lines = [e for i, e in top if e[2] and has_child(i)]
        models = sum(e[3] for e in model_lines) if model_lines else 1
        loadout = [e[1] for _, e in top if e[2]]

    return ParsedUnit(
        name=name,
        points=points,
        section=section,
        models=models,
        warlord=warlord,
        enhancement=enhancement,
        loadout=loadout,
        raw_block=[line.rstrip() for line in body_lines if line.strip()],
    )


def _parse_metadata(roster: ParsedRoster, metadata: list[str]) -> None:
    leftovers: list[str] = []
    for line in metadata:
        m = _UNIT_HEADER.match(line)
        if m and roster.game_size is None:
            roster.game_size = m.group("name").strip()
            roster.points_limit = int(m.group("points"))
        else:
            leftovers.append(line)
    if leftovers:
        roster.faction_text = leftovers[0]
    if len(leftovers) > 1:
        roster.subfaction_text = leftovers[1]
    if len(leftovers) > 2:
        roster.detachment_text = leftovers[2]


def parse_roster(text: str) -> ParsedRoster:
    """Parse roster export text into a structured, un-merged result. Never raises
    on malformed input — unclassifiable lines are ignored or kept in raw_block."""
    roster = ParsedRoster()
    seen_force = False
    in_units = False
    current_section = ""
    metadata: list[str] = []
    header_line: str | None = None
    body: list[str] = []

    def flush_unit() -> None:
        nonlocal header_line, body
        if header_line is not None:
            roster.units.append(_parse_block(header_line, body, current_section))
        header_line, body = None, []

    for line in _normalize(text or "").split("\n"):
        if not line.strip():
            continue

        stripped = line.strip()
        if _FOOTER.match(stripped):
            vm = _VERSIONS.search(stripped)
            if vm:
                roster.app_version = vm.group("app").strip()
                roster.data_version = vm.group("data").strip()
            break

        top_level = not line.startswith(" ")

        if not seen_force:
            hm = _UNIT_HEADER.match(stripped)
            if hm and top_level:
                roster.list_name = hm.group("name").strip()
                roster.total_points = int(hm.group("points"))
                seen_force = True
            continue  # ignore anything before the force header

        if top_level and _is_section(stripped):
            flush_unit()
            current_section = stripped
            in_units = True
            continue

        if in_units and top_level and _UNIT_HEADER.match(stripped):
            flush_unit()
            header_line, body = stripped, []
            continue

        if not in_units and top_level:
            metadata.append(stripped)
            continue

        if header_line is not None:
            body.append(line)

    flush_unit()
    _parse_metadata(roster, metadata)

    if not roster.units:
        roster.warnings.append("No units were found — check that this is a roster text export.")
    return roster


def build_notes(roster: ParsedRoster, unit: ParsedUnit, faction_matched: bool) -> str:
    """Compact, human-readable notes preserving the list-level data we don't model."""
    lines: list[str] = []
    if roster.list_name:
        total = f" ({roster.total_points} pts)" if roster.total_points else ""
        lines.append(f'Imported from list "{roster.list_name}"{total}.')

    bits: list[str] = []
    if unit.points is not None:
        bits.append(f"{unit.points} pts")
    if unit.models and unit.models > 1:
        bits.append(f"{unit.models} models")
    if unit.section:
        bits.append(unit.section.title())
    if bits:
        lines.append("Unit: " + " · ".join(bits))

    if roster.detachment_text:
        det = roster.detachment_text
        ctx = [c for c in (roster.game_size, f"{roster.points_limit} pts" if roster.points_limit else None) if c]
        if ctx:
            det += f" ({', '.join(ctx)})"
        lines.append(f"Detachment: {det}")

    if unit.warlord:
        lines.append("Warlord")
    if unit.enhancement:
        lines.append(f"Enhancement: {unit.enhancement}")
    if unit.loadout:
        lines.append("Loadout: " + ", ".join(unit.loadout))

    if not faction_matched and (roster.faction_text or roster.subfaction_text):
        raw = " / ".join(x for x in (roster.faction_text, roster.subfaction_text) if x)
        lines.append(f"Faction (unmatched): {raw}")

    return "\n".join(lines)


def plan_import(roster, *, match_fn, existing_names, merge=True, skip_existing=False):
    """Turn a parsed roster into the rows that will be created.

    ``match_fn(unit) -> (faction, subfaction, matched: bool, warnings: list)``
    is injected so this stays DB-free. ``existing_names`` is the caller's set of
    already-owned entry names (owner-scoped). Merge groups identical units and
    sets ``quantity`` to the number of datasheets (not models); skip flags rows
    whose name is already owned. Order: match -> merge -> skip.
    """
    owned = {n.casefold() for n in existing_names}
    rows: list[ImportRow] = []
    index: dict[tuple, int] = {}

    for unit in roster.units:
        faction, subfaction, matched, fwarnings = match_fn(unit)
        warnings = list(unit.warnings) + list(fwarnings)

        name = unit.name
        if len(name) > NAME_MAX_LENGTH:
            name = name[:NAME_MAX_LENGTH].rstrip()
            warnings.append(f"Name truncated to {NAME_MAX_LENGTH} characters.")

        notes = build_notes(roster, unit, matched)
        key = (name.casefold(), getattr(faction, "pk", None), getattr(subfaction, "pk", None))

        if merge and key in index:
            row = rows[index[key]]
            row.quantity += 1
            row.models_total += unit.models
            row.warnings.extend(warnings)
        else:
            index[key] = len(rows)
            rows.append(
                ImportRow(
                    name=name,
                    quantity=1,
                    models_total=unit.models,
                    section=unit.section,
                    faction=faction,
                    subfaction=subfaction,
                    notes=notes,
                    warnings=warnings,
                )
            )

    if skip_existing:
        for row in rows:
            if row.name.casefold() in owned:
                row.skip = True
                row.warnings.append("Already in your collection — skipped by default.")

    return rows
