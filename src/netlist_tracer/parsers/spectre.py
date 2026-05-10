from __future__ import annotations

import os
import re
from typing import Optional

from netlist_tracer.model import Instance, SubcktDef
from netlist_tracer.parsers.includes import expand_includes


def parse_spectre(
    filename: str, include_paths: Optional[list[str]] = None
) -> tuple[dict[str, SubcktDef], list[Instance]]:
    """Parse Spectre netlist file.

    Args:
        filename: Path to Spectre netlist file.
        include_paths: Optional list of additional search directories for includes.

    Returns:
        Tuple of (subckts_dict, instances_list) where subckts_dict maps cell
        names to SubcktDef objects and instances_list is a list of Instance objects.
    """
    # Expand includes first
    expanded_lines = expand_includes(filename, "spectre", include_paths)
    raw_lines = [line_text + "\n" for line_text, _, _ in expanded_lines]

    subckts: dict[str, SubcktDef] = {}
    instances: list[Instance] = []

    # Join backslash-continuation lines and strip bracket escaping
    lines = []
    buf = ""
    for raw in raw_lines:
        raw = raw.rstrip()
        if buf:
            raw = raw.lstrip()
        if raw.endswith("\\"):
            buf += raw[:-1] + " "
        else:
            buf += raw
            lines.append(buf)
            buf = ""
    if buf:
        lines.append(buf)

    # Strip \< and \> bracket escaping
    lines = [line_item.replace("\\<", "<").replace("\\>", ">") for line_item in lines]  # noqa: E741

    skip_prefixes = (
        "simulator",
        "global",
        "parameters",
        "real",
        "model",
        "ends",
        "ahdl_include",
        "saveOptions",
        "save",
    )

    # First pass: collect subckt definitions and body lines
    subckt_bodies: dict[str, list[str]] = {}  # cell_name -> list of body lines
    current_subckt = None
    top_level_lines = []
    # Derive synthetic top-level cell name from filename stem with double-underscore convention
    stem = os.path.splitext(os.path.basename(filename))[0]
    top_cell = f"__{stem}__"

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue

        subckt_match = re.match(r"^subckt\s+(\S+)\s*(.*)", stripped)
        if subckt_match:
            cell_name = subckt_match.group(1)
            pin_text = subckt_match.group(2)
            # Remove optional parentheses around pins
            pin_text = pin_text.strip("()")
            pins = [p for p in pin_text.split() if p]
            subckts[cell_name] = SubcktDef(name=cell_name, pins=pins)
            current_subckt = cell_name
            subckt_bodies[cell_name] = []
            continue

        if re.match(r"^ends\b", stripped):
            current_subckt = None
            continue

        if current_subckt:
            subckt_bodies[current_subckt].append(stripped)
        else:
            top_level_lines.append(stripped)

    # Register top-level cell if it has content (testbench)
    if top_level_lines:
        if top_cell not in subckts:
            subckts[top_cell] = SubcktDef(name=top_cell, pins=[])
        subckt_bodies[top_cell] = top_level_lines

    # Second pass: parse instances in each subckt body
    for cell_name, body_lines in subckt_bodies.items():
        for line in body_lines:
            stripped = line.strip()
            if any(stripped.startswith(p) for p in skip_prefixes):
                continue
            instance = _parse_spectre_instance(stripped, cell_name, subckts)
            if instance:
                instances.append(instance)

    return subckts, instances


def _parse_spectre_instance(
    text: str, parent_cell: str, subckts: dict[str, SubcktDef]
) -> Optional[Instance]:
    """Parse a single Spectre instance line: name (nets) cell_type [params].

    Args:
        text: Instance line text.
        parent_cell: Name of the parent subcircuit.
        subckts: Dictionary of known subcircuit definitions.

    Returns:
        Instance object or None if parsing fails or cell_type is not known.
    """
    m = re.match(r"^(\S+)\s*\(([^)]*)\)\s*(\S+)", text)
    if not m:
        return None
    inst_name = m.group(1)
    nets = m.group(2).split()
    cell_type = m.group(3)
    # Only register instances whose cell_type is a known subckt
    if cell_type not in subckts:
        return None
    return Instance(name=inst_name, cell_type=cell_type, nets=nets, parent_cell=parent_cell)
