"""Parser for SPF (SPICE parasitic format) and DSPF netlists."""

from __future__ import annotations

import gzip
import re

from netlist_tracer._logging import get_logger
from netlist_tracer.exceptions import NetlistParseError
from netlist_tracer.model import Instance, SubcktDef

_logger = get_logger(__name__)


################################################################################
# SECTION: SPF State Management
# Description: Data structures for tracking DIVIDER, DELIMITER, and other
# SPF-specific metadata during parse.
################################################################################


class SpfState:
    """Per-parse state for SPF directives and net normalization."""

    def __init__(self) -> None:
        self.divider: str = "/"  # Default divider for hierarchical nets
        self.delimiter: str = ":"  # Default delimiter for subnode markers
        self.gnd_net: str = ""  # Ground net name from *|GROUND_NET
        self.design_name: str = ""  # Design name from *|DESIGN


################################################################################
# SECTION: Header Scanning
# Description: Pre-scan first lines to extract DIVIDER, DELIMITER, DESIGN,
# and other metadata directives.
################################################################################


def _scan_spf_header(lines: list[str]) -> SpfState:
    """
    Pre-scan first ~100 lines for *|DIVIDER, *|DELIMITER, *|DESIGN directives.

    Sets parse-time state defaults. SPF files without explicit directives
    rely on built-in defaults ('/' for DIVIDER, ':' for DELIMITER).

    Inputs:
        lines: Raw file lines

    Outputs:
        SpfState with divider/delimiter/design populated
    """
    stt = SpfState()

    for line in lines[:100]:
        stripped = line.strip()

        # *|DIVIDER <char>
        m = re.match(r"\*\|DIVIDER\s+(\S)", stripped)
        if m:
            stt.divider = m.group(1)
            continue

        # *|DELIMITER <char>
        m = re.match(r"\*\|DELIMITER\s+(\S)", stripped)
        if m:
            stt.delimiter = m.group(1)
            continue

        # *|DESIGN <name>
        m = re.match(r"\*\|DESIGN\s+(\S+)", stripped)
        if m:
            stt.design_name = m.group(1)
            continue

    return stt


################################################################################
# SECTION: Subnode Normalization
# Description: Collapse hierarchical subnode forms (net:N) to parent net names.
################################################################################


def _normalize_subnode_net(net: str, delimiter: str) -> str:
    """
    Collapse subnode form 'parent:N' to 'parent' for tracer purposes.

    Only the LAST occurrence of delimiter is treated as subnode marker.
    Idempotent.

    Inputs:
        net: Net name as it appears on element line
        delimiter: Delimiter char from *|DELIMITER (default ':')

    Outputs:
        Normalized net name
    """
    idx = net.rfind(delimiter)
    if idx >= 0:
        return net[:idx]
    return net


################################################################################
# SECTION: SPF Directive Parsing
# Description: Parse individual *|* directives and mutate SPF state.
################################################################################


def _parse_spf_directive(line: str, stt: SpfState, crnt_sbckt: SubcktDef | None) -> None:
    """
    Handle one *|* directive line. Mutates state and subckt.params as appropriate.

    Inputs:
        line: A *|* directive line (already stripped)
        stt: SpfState
        crnt_sbckt: Currently-open subckt (None if outside .SUBCKT)

    Outputs:
        None (mutates state and subckt)
    """
    # *|GROUND_NET <name>
    m = re.match(r"\*\|GROUND_NET\s+(\S+)", line)
    if m:
        net_nm = m.group(1)
        stt.gnd_net = net_nm
        if crnt_sbckt:
            if "_ground_net" not in crnt_sbckt.params:
                crnt_sbckt.params["_ground_net"] = {}
            crnt_sbckt.params["_ground_net"] = net_nm
        return

    # *|NET <name> <cap_value>
    m = re.match(r"\*\|NET\s+(\S+)\s+(.+)", line)
    if m:
        net_nm = m.group(1)
        cap_str = m.group(2).strip()
        if crnt_sbckt:
            if "_net_caps" not in crnt_sbckt.params:
                crnt_sbckt.params["_net_caps"] = {}
            try:
                cap_val = _parse_cap_value(cap_str)
                crnt_sbckt.params["_net_caps"][net_nm] = cap_val
            except ValueError:
                _logger.warning(f"Could not parse capacitance '{cap_str}' for net '{net_nm}'")
        return

    # *|I (<pinref> <inst> <pintype> <type> <x> <y>)
    m = re.match(r"\*\|I\s+\((.+)\)", line)
    if m:
        prms = m.group(1).split()
        if len(prms) >= 2:
            pinref = prms[0]
            inst_nm = prms[1]
            pintype = prms[2] if len(prms) > 2 else ""
            if crnt_sbckt:
                if "_pin_aliases" not in crnt_sbckt.params:
                    crnt_sbckt.params["_pin_aliases"] = {}
                crnt_sbckt.params["_pin_aliases"][pinref] = (inst_nm, pintype)
        return

    # *|S <subnode>:<N> ... (no-op for now; noted but not processed)
    if line.startswith("*|S"):
        return

    # *|P (...) (port info; defensive: append to pins if not already there)
    m = re.match(r"\*\|P\s+\((.+)\)", line)
    if m:
        # Port line: extract first token as port name
        prms = m.group(1).split()
        if prms and crnt_sbckt and prms[0] not in crnt_sbckt.pins:
            crnt_sbckt.pins.append(prms[0])
        return

    # Silently consume header directives already handled in _scan_spf_header
    if re.match(r"\*\|(DIVIDER|DELIMITER|DESIGN|DATE|VENDOR|PROGRAM|VERSION)", line):
        return

    # Unknown *|* directive: log warning
    if line.startswith("*|"):
        _logger.warning(f"Unknown SPF directive: {line[:40]}")


def _parse_cap_value(cap_str: str) -> float:
    """
    Parse capacitance value with unit suffix (F, PF, etc.).

    Inputs:
        cap_str: Capacitance string (e.g., '1.5PF', '2.3f')

    Outputs:
        float - Value in Farads
    """
    cap_str = cap_str.strip().upper()

    # Try to match number + unit
    m = re.match(r"([\d.eE+-]+)\s*([A-Z]+)?", cap_str)
    if not m:
        raise ValueError(f"Invalid capacitance format: {cap_str}")

    val = float(m.group(1))
    unit = m.group(2) or "F"

    # Unit conversion to Farads
    unit_mult = {
        "F": 1.0,
        "FD": 1.0,
        "P": 1e-12,
        "PF": 1e-12,
        "N": 1e-9,
        "NF": 1e-9,
        "U": 1e-6,
        "UF": 1e-6,
        "M": 1e-3,
        "MF": 1e-3,
    }

    mult = unit_mult.get(unit, 1.0)
    return val * mult


################################################################################
# SECTION: SPF Body Parsing
# Description: Parse SPF file body: .SUBCKT/.ENDS blocks, elements, and
# directives with shared SPICE element handlers.
################################################################################


def _parse_spf_body(
    lines: list[str], stt: SpfState
) -> tuple[dict[str, SubcktDef], list[Instance], list[str]]:
    """
    Iterate body lines, dispatching .SUBCKT/.ENDS, *|* directives, and
    standard SPICE elements (R/C/L/M/X/B/E/F/G/H/K/V/I).

    Inputs:
        lines: Body lines (after header scan)
        stt: Pre-populated SpfState

    Outputs:
        (subckts, instances, global_nets)
    """
    sbckts: dict[str, SubcktDef] = {}
    insts: list[Instance] = []
    crnt_sbckt: SubcktDef | None = None
    crnt_sbckt_nm: str = ""

    for line in lines:
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            continue

        # *|* directive (must check before skipping "*" comments)
        if stripped.startswith("*|"):
            _parse_spf_directive(stripped, stt, crnt_sbckt)
            continue

        # Skip regular comments (* but not *|)
        if stripped.startswith("*"):
            continue

        # .SUBCKT directive
        m = re.match(r"\.SUBCKT\s+(\S+)\s*(.*)", stripped, re.IGNORECASE)
        if m:
            cell_nm = m.group(1)
            pin_txt = m.group(2)
            # Parse pin list
            pins = [
                p.strip() for p in pin_txt.split() if p.strip() and not p.strip().startswith("*")
            ]
            crnt_sbckt = SubcktDef(name=cell_nm, pins=pins)
            crnt_sbckt.params["_net_caps"] = {}
            crnt_sbckt.params["_pin_aliases"] = {}
            crnt_sbckt.params["_ground_net"] = ""
            sbckts[cell_nm] = crnt_sbckt
            crnt_sbckt_nm = cell_nm
            continue

        # .ENDS directive
        if re.match(r"\.ENDS", stripped, re.IGNORECASE):
            crnt_sbckt = None
            crnt_sbckt_nm = ""
            continue

        # Element lines (R/C/L/M/X/etc.) - only inside subckt
        if crnt_sbckt:
            _parse_spf_element_line(stripped, crnt_sbckt_nm, stt, insts)

    return sbckts, insts, []


def _parse_spf_element_line(
    line: str, prnt_sbckt: str, stt: SpfState, insts: list[Instance]
) -> None:
    """
    Parse a single element line within an SPF subckt.

    Handles R/C/L/M/X and normalizes net names via subnode collapsing.

    Inputs:
        line: Stripped element line
        prnt_sbckt: Parent subckt name
        stt: SpfState for delimiter
        insts: Instance list to append to
    """
    tokens = line.split()
    if not tokens:
        return

    elem_name = tokens[0]
    elem_type = elem_name[0].upper()

    # R element: R<name> n1 n2 value
    if elem_type == "R":
        if len(tokens) >= 4:
            n1 = _normalize_subnode_net(tokens[1], stt.delimiter)
            n2 = _normalize_subnode_net(tokens[2], stt.delimiter)
            insts.append(
                Instance(
                    name=elem_name,
                    cell_type="R",
                    nets=[n1, n2],
                    parent_cell=prnt_sbckt,
                )
            )

    # C element: C<name> n1 n2 value
    elif elem_type == "C":
        if len(tokens) >= 4:
            n1 = _normalize_subnode_net(tokens[1], stt.delimiter)
            n2 = _normalize_subnode_net(tokens[2], stt.delimiter)
            insts.append(
                Instance(
                    name=elem_name,
                    cell_type="C",
                    nets=[n1, n2],
                    parent_cell=prnt_sbckt,
                )
            )

    # L element: L<name> n1 n2 value
    elif elem_type == "L":
        if len(tokens) >= 4:
            n1 = _normalize_subnode_net(tokens[1], stt.delimiter)
            n2 = _normalize_subnode_net(tokens[2], stt.delimiter)
            insts.append(
                Instance(
                    name=elem_name,
                    cell_type="L",
                    nets=[n1, n2],
                    parent_cell=prnt_sbckt,
                )
            )

    # M element: M<name> d g s b model ...
    elif elem_type == "M":
        if len(tokens) >= 5:
            d = _normalize_subnode_net(tokens[1], stt.delimiter)
            g = _normalize_subnode_net(tokens[2], stt.delimiter)
            s = _normalize_subnode_net(tokens[3], stt.delimiter)
            b = _normalize_subnode_net(tokens[4], stt.delimiter)
            mdl = tokens[5] if len(tokens) > 5 else "unknown"
            insts.append(
                Instance(
                    name=elem_name,
                    cell_type=mdl,
                    nets=[d, g, s, b],
                    parent_cell=prnt_sbckt,
                )
            )

    # X element (subckt instance): X<name> net1 net2 ... celltype
    elif elem_type == "X":
        if len(tokens) >= 3:
            # Last token is cell type; rest before it are nets
            celltype = tokens[-1]
            nets = [_normalize_subnode_net(t, stt.delimiter) for t in tokens[1:-1]]
            insts.append(
                Instance(
                    name=elem_name,
                    cell_type=celltype,
                    nets=nets,
                    parent_cell=prnt_sbckt,
                )
            )


################################################################################
# SECTION: Public Parser Entry
# Description: Main parse_spf() function for file-level parsing.
################################################################################


def parse_spf(
    filepath: str, include_paths: list[str] | None = None
) -> tuple[dict[str, SubcktDef], list[Instance], list[str]]:
    """
    Parse a single SPF file and return (subckts, instances, global_nets).

    Handles .spf and .dspf files, including gzip-compressed variants.
    Recognizes *|DSPF / *|RSPF / *|CCSPF content markers and .spf/.dspf
    extensions. Honors *|DIVIDER / *|DELIMITER for hierarchical net naming.
    Collapses *|S subnodes back to parent *|NET for tracer purposes.

    Inputs:
        filepath: Path to .spf/.dspf file (gzip-supported)
        include_paths: Reserved for future use; not consumed in v0.5.0

    Outputs:
        (subckts dict, instances list, global_nets list)

    Raises:
        NetlistParseError if file is empty or contains no .SUBCKT
    """
    # Open file (handle .gz extension)
    try:
        if filepath.lower().endswith(".gz"):
            with gzip.open(filepath, "rt", encoding="utf-8", errors="replace") as f:
                content = f.read()
        else:
            with open(filepath, encoding="utf-8", errors="replace") as f:
                content = f.read()
    except OSError as e:
        raise NetlistParseError(f"Failed to read SPF file {filepath}: {e}") from e

    lines = content.splitlines()

    if not lines:
        raise NetlistParseError(f"SPF file is empty: {filepath}")

    # Header scan: extract DIVIDER, DELIMITER, DESIGN
    stt = _scan_spf_header(lines)

    # Body parse: extract subckts, instances, directives
    sbckts, insts, _ = _parse_spf_body(lines, stt)

    if not sbckts:
        raise NetlistParseError(f"No .SUBCKT found in SPF file: {filepath}")

    return sbckts, insts, []
