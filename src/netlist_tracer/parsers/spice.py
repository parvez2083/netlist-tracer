from __future__ import annotations

import logging
import os
import re
from typing import Optional

from netlist_tracer.model import Instance, SubcktDef
from netlist_tracer.parsers.includes import expand_includes

_logger = logging.getLogger(__name__)


def parse_spice(
    filename: str, include_paths: Optional[list[str]] = None
) -> tuple[dict[str, SubcktDef], list[Instance]]:
    """Parse SPICE/CDL netlist file.

    Args:
        filename: Path to SPICE or CDL netlist file.
        include_paths: Optional list of additional search directories for includes.

    Returns:
        Tuple of (subckts_dict, instances_list) where subckts_dict maps cell
        names to SubcktDef objects and instances_list is a list of Instance objects.
    """
    # Expand includes first
    expanded_lines = expand_includes(filename, "spice", include_paths)
    lines = [line_text + "\n" for line_text, _, _ in expanded_lines]

    subckts: dict[str, SubcktDef] = {}
    instances: list[Instance] = []

    current_subckt: Optional[str] = None
    subckt_content: list[str] = []
    top_level_lines: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i].rstrip()

        subckt_match = re.match(r"^\.subckt\s+(\S+)\s*(.*)", line, re.IGNORECASE)
        if subckt_match:
            cell_name = subckt_match.group(1)
            pin_text = subckt_match.group(2)

            # Handle continuation lines
            while i + 1 < len(lines) and lines[i + 1].startswith("+"):
                i += 1
                pin_text += " " + lines[i][1:].strip()

            pin_text = re.sub(r"\+", " ", pin_text)
            pins = [p for p in pin_text.split() if p and not p.startswith("*") and "=" not in p]

            current_subckt = cell_name
            subckt_content = []
            subckts[cell_name] = SubcktDef(name=cell_name, pins=pins)

        elif re.match(r"^\.ends", line, re.IGNORECASE):
            if current_subckt:
                _parse_spice_instances(current_subckt, subckt_content, instances)
            current_subckt = None
            subckt_content = []

        elif current_subckt:
            subckt_content.append(line)

        else:
            # Top-level: capture X-instance lines and continuation lines
            stripped = line.strip()
            if stripped and not stripped.startswith("*") and not stripped.startswith("."):
                if stripped[0].upper() == "X":
                    top_level_lines.append(line)
                    # Capture continuation lines
                    while i + 1 < len(lines) and lines[i + 1].startswith("+"):
                        i += 1
                        top_level_lines.append(lines[i].rstrip())

        i += 1

    # Synthesize flat-deck top if there are top-level instances
    _synthesize_flat_top(filename, top_level_lines, subckts, instances)

    return subckts, instances


def _synthesize_flat_top(
    filename: str,
    top_level_lines: list[str],
    subckts: dict[str, SubcktDef],
    instances: list[Instance],
) -> None:
    """Synthesize a virtual top-level subcircuit for flat-deck testbenches.

    When a SPICE netlist has instance lines at file scope (not inside any .subckt block),
    this function creates a synthetic SubcktDef and parses those instances into it.
    The synthetic top is named __<filename_stem>__.

    Args:
        filename: Source netlist file path (used to derive the synthetic top name).
        top_level_lines: List of captured top-level instance lines (including continuations).
        subckts: Dictionary of SubcktDef objects to mutate (synthetic top is added).
        instances: List of Instance objects to mutate (top-level instances are appended).
    """
    if not top_level_lines:
        return

    # Derive synthetic top name: __<basename_no_ext>__
    stem = os.path.splitext(os.path.basename(filename))[0]
    top_name = f"__{stem}__"

    # Handle collision: if top_name already exists, append _synth suffix
    if top_name in subckts:
        _logger.warning(
            f"Synthetic top name '{top_name}' collides with existing cell; using '{top_name}_synth' instead"
        )
        top_name = f"{top_name}_synth"

    # Create synthetic top SubcktDef with empty pins
    subckts[top_name] = SubcktDef(name=top_name, pins=[])

    # Parse top-level instances into the synthetic top
    _parse_spice_instances(top_name, top_level_lines, instances)


def _parse_spice_instances(parent_cell: str, content: list[str], instances: list[Instance]) -> None:
    """Parse instances within a subckt body.

    Args:
        parent_cell: Name of the parent subcircuit.
        content: List of content lines from the subcircuit body.
        instances: List to append parsed Instance objects to.
    """
    i = 0
    while i < len(content):
        line = content[i]
        stripped = line.strip()

        if stripped.upper().startswith("X"):
            instance_text = stripped
            while i + 1 < len(content) and content[i + 1].lstrip().startswith("+"):
                i += 1
                instance_text += " " + content[i].strip().lstrip("+").strip()

            instance = _parse_spice_instance(instance_text, parent_cell)
            if instance:
                instances.append(instance)
        i += 1


def _parse_spice_instance(text: str, parent_cell: str) -> Optional[Instance]:
    """Parse a single SPICE/CDL instance line.

    Args:
        text: Instance line text.
        parent_cell: Name of the parent subcircuit.

    Returns:
        Instance object or None if parsing fails.
    """
    text = re.sub(r"\+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    tokens = text.split()
    if len(tokens) < 2:
        return None
    if "=" in tokens[0]:
        return None

    inst_name = tokens[0]

    # CDL format: Xinst net1 net2 ... / celltype
    # SPICE format: Xinst net1 net2 ... celltype [params]
    if "/" in tokens:
        slash_idx = tokens.index("/")
        nets = tokens[1:slash_idx]
        cell_type = tokens[slash_idx + 1] if slash_idx + 1 < len(tokens) else None
    else:
        nets = []
        cell_type = None
        for j, tok in enumerate(tokens[1:], 1):
            if "=" in tok:
                break
            if j == len(tokens) - 1:
                cell_type = tok
            else:
                nets.append(tok)
        if cell_type is None and nets:
            cell_type = nets.pop()

    if cell_type is None:
        return None

    # Capture param=value pairs
    params = {}
    for tok in tokens:
        if "=" in tok and not tok.startswith("*"):
            k, v = tok.split("=", 1)
            params[k] = v.strip("'")

    return Instance(
        name=inst_name,
        cell_type=cell_type,
        nets=nets,
        parent_cell=parent_cell,
        params=params or None,
    )
