"""Parser for SPF (SPICE parasitic format) and DSPF netlists."""

from __future__ import annotations

import gzip
import re

from netlist_tracer._logging import get_logger
from netlist_tracer.exceptions import NetlistParseError
from netlist_tracer.model import Instance, SubcktDef
from netlist_tracer.parsers._numerics import parse_numerical
from netlist_tracer.parsers.spice import _parse_spice_instance

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
    Identity pass-through for net names. Numeric subnodes (e.g., 'clk_in:20')
    are REAL intermediate nodes in the parasitic R-network and must be preserved.

    The function is kept (rather than removed) so callers don't have to change
    and future format-specific normalization can plug in here. The series-R
    reduction pass (_reduce_series_resistors) handles tracer ergonomics by
    merging purely-series R chains into single equivalent resistors.

    Inputs:
        net: Net name as it appears on element line
        delimiter: Delimiter char from *|DELIMITER (default ':', unused)

    Outputs:
        net (unchanged)
    """
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
    # and the format-marker line itself (*|DSPF/RSPF/CCSPF <version>).
    if re.match(
        r"\*\|(DSPF|RSPF|CCSPF|DIVIDER|DELIMITER|DESIGN|DATE|VENDOR|PROGRAM|VERSION)\b",
        line,
    ):
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

    # R element: R<name> n1 n2 value  (value captured into params['_value'])
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
                    params={"_value": tokens[3]},
                )
            )

    # C element: C<name> n1 n2 value  (value captured into params['_value'])
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
                    params={"_value": tokens[3]},
                )
            )

    # L element: L<name> n1 n2 value  (value captured into params['_value'])
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
                    params={"_value": tokens[3]},
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

    # X element (subckt instance): X<name> net1 net2 ... celltype [params...]
    elif elem_type == "X":
        inst = _parse_spice_instance(line, prnt_sbckt)
        if inst is not None:
            # Apply numeric-only subnode normalization to nets
            inst.nets = [_normalize_subnode_net(n, stt.delimiter) for n in inst.nets]
            insts.append(inst)


################################################################################
# SECTION: Series-R Reduction
# Description: Post-parse reduction of purely-series R chains into merged
# equivalent resistors with summed values.
################################################################################


def _reduce_series_resistors(
    sbckts: dict[str, SubcktDef], insts: list[Instance], top_cell: str
) -> list[Instance]:
    """
    Iteratively merge purely-series R chains in instances under top_cell.

    Returns a NEW instances list (caller replaces). Other-parent instances
    pass through unchanged. Merged R instances have:
      - name: '<first_R>_to_<last_R>'
      - cell_type: 'R'
      - params['_value']: summed value (formatted with :g)
      - params['_merged_from']: ordered list of original R names in chain order
      - params['_chain_endpoints']: tuple (surviving_a_end, surviving_b_end)

    Inputs:
        sbckts: Subckt dict from _parse_spf_body
        insts: Full instance list (all parent_cells)
        top_cell: Name of the top subckt; only instances with parent_cell == top_cell
                  are eligible for reduction

    Outputs:
        New list of Instance objects: instances under other parents pass through;
        instances under top_cell have purely-series R chains collapsed
    """
    # Partition instances by parent_cell
    own_insts = [i for i in insts if i.parent_cell == top_cell]
    non_own_insts = [i for i in insts if i.parent_cell != top_cell]

    # Get port nets from top_cell (must never be merged out)
    port_nets = set(sbckts[top_cell].pins) if top_cell in sbckts else set()

    # Build net-to-instances index for top_cell using id() for fast removal
    net_to_insts: dict[str, list[Instance]] = {}
    for inst in own_insts:
        for net in inst.nets:
            if net not in net_to_insts:
                net_to_insts[net] = []
            net_to_insts[net].append(inst)

    # Seed worklist with all non-port nets
    wrklst = set(net_to_insts.keys()) - port_nets

    mrg_cnt = 0
    deleted_insts = set()  # Track deleted instance ids for fast lookup

    # Worklist-driven merge loop
    while wrklst:
        net = wrklst.pop()

        # Skip if net is a port or has no instances
        if net in port_nets or net not in net_to_insts:
            continue

        insts_here = net_to_insts[net]

        # Filter R's and non-mergeable instances, skipping deleted ones
        r_insts = [i for i in insts_here if i.cell_type == "R" and id(i) not in deleted_insts]
        non_mrgbl = [
            i
            for i in insts_here
            if i.cell_type not in ("R", "C", "K") and id(i) not in deleted_insts
        ]

        # Only merge if exactly 2 R's and no transistors/sources
        if len(r_insts) != 2 or non_mrgbl:
            continue

        r1, r2 = r_insts

        # Find other-terminal nets (the net NOT on the merged-out side)
        a = next((n for n in r1.nets if n != net), None)
        b = next((n for n in r2.nets if n != net), None)

        # Skip if either is None, or if they form a self-loop on r1/r2
        if a is None or b is None or a == net or b == net:
            continue

        # Skip if parallel (both R's span the same two nets)
        if a == b:
            continue

        # Parse values
        v1 = parse_numerical(r1.params.get("_value", "0"))
        v2 = parse_numerical(r2.params.get("_value", "0"))

        if v1 is None or v2 is None:
            _logger.warning(f"Could not parse R value for {r1.name} or {r2.name}; skipping merge")
            continue

        # Determine chain endpoints
        # Convention: endpoints align with nets indices
        # If r1 has _chain_endpoints, it's a previous merge; otherwise it's a single R
        r1_eps = r1.params.get("_chain_endpoints")
        if r1_eps:
            # r1_eps = (endpoint_on_nets[0], endpoint_on_nets[1])
            # net is one of r1.nets; find which
            if r1.nets[0] == net:
                # net is on nets[0] side, so surviving endpoint is on nets[1] side
                a_end = r1_eps[1]
            else:
                # net is on nets[1] side, so surviving endpoint is on nets[0] side
                a_end = r1_eps[0]
        else:
            # Single R: both endpoints are the name
            a_end = r1.name

        r2_eps = r2.params.get("_chain_endpoints")
        if r2_eps:
            # net is one of r2.nets; find which
            if r2.nets[0] == net:
                # net is on nets[0] side, so surviving endpoint is on nets[1] side
                b_end = r2_eps[1]
            else:
                # net is on nets[1] side, so surviving endpoint is on nets[0] side
                b_end = r2_eps[0]
        else:
            # Single R: both endpoints are the name
            b_end = r2.name

        # Construct merged R name (deterministic: sorted endpoints)
        sorted_endpoints = sorted([a_end, b_end])
        new_nm = f"{sorted_endpoints[0]}_to_{sorted_endpoints[1]}"

        # Construct merged_from list: order by direction from a to net to b
        r1_mrgd_from = r1.params.get("_merged_from") or [r1.name]
        r2_mrgd_from = r2.params.get("_merged_from") or [r2.name]

        # Determine order: does r1 go from a->net or net->a?
        if r1.nets[0] == net:
            # r1 is net->a, so reverse it to get a->net
            new_mrgd_from = list(reversed(r1_mrgd_from)) + r2_mrgd_from
        else:
            # r1 is a->net, so keep it
            new_mrgd_from = r1_mrgd_from + r2_mrgd_from

        # Sum values
        new_val = v1 + v2
        new_val_str = f"{new_val:g}"

        # Create merged R instance
        new_inst = Instance(
            name=new_nm,
            cell_type="R",
            nets=[a, b],
            parent_cell=top_cell,
            params={
                "_value": new_val_str,
                "_merged_from": new_mrgd_from,
                "_chain_endpoints": (a_end, b_end),
            },
        )

        # Mark r1 and r2 as deleted
        deleted_insts.add(id(r1))
        deleted_insts.add(id(r2))

        # Append new merged instance
        own_insts.append(new_inst)

        # Add new instance to nets a and b in the index
        if a not in net_to_insts:
            net_to_insts[a] = []
        net_to_insts[a].append(new_inst)

        if b not in net_to_insts:
            net_to_insts[b] = []
        net_to_insts[b].append(new_inst)

        # Re-add a and b to worklist for further merging
        wrklst.add(a)
        wrklst.add(b)

        mrg_cnt += 1

    if mrg_cnt > 0:
        _logger.info(f"series-R reduction: merged {mrg_cnt} chains in {top_cell}")

    # Filter out deleted instances from own_insts before returning
    result = non_own_insts + [i for i in own_insts if id(i) not in deleted_insts]
    return result


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

    # Apply series-R reduction as post-parse pass
    top_cell = next(iter(sbckts))
    insts = _reduce_series_resistors(sbckts, insts, top_cell)

    return sbckts, insts, []
