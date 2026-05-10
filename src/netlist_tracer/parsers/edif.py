"""Electronic Design Interchange Format (EDIF) netlist parser."""

from __future__ import annotations

import re
from collections.abc import Iterator
from typing import Optional, Union

from netlist_tracer._logging import get_logger
from netlist_tracer.exceptions import NetlistParseError
from netlist_tracer.model import Instance, SubcktDef

_logger = get_logger(__name__)


def parse_edif(filename: str) -> tuple[dict[str, SubcktDef], list[Instance]]:
    """Parse EDIF netlist file.

    Args:
        filename: Path to .edif/.edn/.edf file.

    Returns:
        Tuple of (subckts_dict, instances_list) matching parse_spice signature.

    Raises:
        NetlistParseError: On malformed s-expression or unsupported construct.
    """
    with open(filename) as f:
        text = f.read()

    tokens = _tokenize(text)
    root = _parse_sexpr(tokens)

    if not isinstance(root, list) or len(root) < 1:
        raise NetlistParseError("Invalid EDIF: root must be a compound s-expression")

    subckts: dict[str, SubcktDef] = {}
    instances: list[Instance] = []

    # Walk (edif ...) root
    _walk_root(root, subckts, instances)

    _logger.info(
        f"EDIF parse complete: {len(subckts)} subckts, {len(instances)} instances"
    )

    return subckts, instances


def _tokenize(text: str) -> Iterator[tuple[str, str, int]]:
    """Lazy s-expression tokenizer.

    Args:
        text: Full file contents as a single string.

    Yields:
        (kind, text, line) tuples where kind is 'lparen', 'rparen', 'atom', or 'string'.
    """
    line_no = 1
    i = 0

    while i < len(text):
        ch = text[i]

        # Newline
        if ch == "\n":
            line_no += 1
            i += 1
            continue

        # Whitespace
        if ch in " \t\r":
            i += 1
            continue

        # Line comment
        if ch == ";" and (i + 1 >= len(text) or text[i + 1] != ";"):
            # Single ; — EDIF comment to end of line
            while i < len(text) and text[i] != "\n":
                i += 1
            continue

        # Block comment (comment ...)
        if (
            i + 7 < len(text)
            and text[i : i + 8].lower() == "(comment"
            and (i + 8 >= len(text) or text[i + 8] in " \t\r\n()")
        ):
            # Skip entire (comment ...) s-expression by counting parens
            depth = 0
            while i < len(text):
                if text[i] == "(":
                    depth += 1
                elif text[i] == ")":
                    depth -= 1
                    if depth == 0:
                        i += 1
                        break
                elif text[i] == "\n":
                    line_no += 1
                i += 1
            continue

        # Left paren
        if ch == "(":
            yield ("lparen", "(", line_no)
            i += 1
            continue

        # Right paren
        if ch == ")":
            yield ("rparen", ")", line_no)
            i += 1
            continue

        # String (double-quoted)
        if ch == '"':
            j = i + 1
            string_content = ""
            while j < len(text):
                if text[j] == "\\":
                    # Backslash escape
                    if j + 1 < len(text):
                        string_content += text[j + 1]
                        j += 2
                    else:
                        j += 1
                elif text[j] == '"':
                    j += 1
                    break
                else:
                    string_content += text[j]
                    if text[j] == "\n":
                        line_no += 1
                    j += 1
            yield ("string", string_content, line_no)
            i = j
            continue

        # Atom (alphanumeric, symbols)
        if ch.isalnum() or ch in "-_*+/<>=!?&|^~':":
            j = i
            while j < len(text) and (
                text[j].isalnum() or text[j] in "-_*+/<>=!?&|^~':"
            ):
                j += 1
            atom_text = text[i:j]
            yield ("atom", atom_text, line_no)
            i = j
            continue

        # Skip unknown characters
        i += 1


def _parse_sexpr(tokens: Iterator[tuple[str, str, int]]) -> Union[str, list]:
    """Recursive-descent s-expression parser using explicit stack.

    Args:
        tokens: Iterator from _tokenize.

    Returns:
        str (atom) or list (compound).

    Raises:
        NetlistParseError: On unbalanced parens or unexpected EOF.
    """
    stack: list[list[Union[str, list]]] = [[]]  # Stack of lists being built

    for kind, text, line_no in tokens:
        if kind == "lparen":
            stack.append([])
        elif kind == "rparen":
            if len(stack) <= 1:
                raise NetlistParseError(f"Unbalanced ')' at line {line_no}")
            top = stack.pop()
            stack[-1].append(top)
        elif kind in ("atom", "string"):
            stack[-1].append(text)

    if len(stack) != 1:
        raise NetlistParseError("Unbalanced s-expression: EOF reached before all parens closed")

    result = stack[0]
    if len(result) != 1:
        raise NetlistParseError(f"Expected single top-level s-expression, got {len(result)}")

    return result[0]


def _unwrap_name(node: Union[str, list]) -> str:
    """Extract canonical name from EDIF identifier. Handles bare atom or (rename safe \"orig\").

    Args:
        node: Atom or s-expression representing a name.

    Returns:
        Safe identifier string.

    Raises:
        NetlistParseError: If (rename ...) structure is malformed.
    """
    if isinstance(node, str):
        return node

    if isinstance(node, list) and len(node) >= 2:
        head = node[0]
        if isinstance(head, str) and head.lower() == "rename":
            safe = node[1]
            if isinstance(safe, str):
                if len(node) > 2 and isinstance(node[2], str):
                    _logger.debug(f"rename: safe={safe}, original={node[2]}")
                return safe

    raise NetlistParseError(f"Invalid name node: {node}")


def _collect_libraries(root: Union[str, list]) -> list[Union[str, list]]:
    """Walk (edif ...) and return list of (library ...) s-expressions.

    Args:
        root: Root s-expression.

    Returns:
        List of library s-expressions.
    """
    if not isinstance(root, list):
        return []

    libraries: list[Union[str, list]] = []
    for child in root:
        if isinstance(child, list) and len(child) > 0:
            head = child[0]
            if isinstance(head, str) and head.lower() == "library":
                libraries.append(child)

    return libraries


def _parse_cell(
    cell_node: Union[str, list], lib_name: str
) -> tuple[Optional[SubcktDef], Optional[Union[str, list]]]:
    """Parse one (cell ...) s-expression. Find NETLIST view and build SubcktDef.

    Args:
        cell_node: (cell ...) s-expression.
        lib_name: Containing library name.

    Returns:
        (SubcktDef, contents_expr) or (None, None) if no NETLIST view.

    Raises:
        NetlistParseError: On malformed structure or unsupported view type.
    """
    if not isinstance(cell_node, list) or len(cell_node) < 2:
        return None, None

    head = cell_node[0]
    if not isinstance(head, str) or head.lower() != "cell":
        return None, None

    # Extract cell name
    cell_name_node = cell_node[1]
    cell_name = _unwrap_name(cell_name_node)

    # Find the NETLIST view
    netlist_view = None
    for child in cell_node[2:]:
        if isinstance(child, list) and len(child) > 0:
            child_head = child[0]
            if isinstance(child_head, str) and child_head.lower() == "view":
                # Check view type
                view_type = None
                for view_child in child[1:]:
                    if isinstance(view_child, list) and len(view_child) > 0:
                        vt_head = view_child[0]
                        if isinstance(vt_head, str) and vt_head.lower() == "viewtype":
                            if len(view_child) > 1 and isinstance(view_child[1], str):
                                view_type = view_child[1].upper()
                            break

                if view_type == "NETLIST":
                    netlist_view = child
                    break
                else:
                    _logger.info(
                        f"Skipping {cell_name} view type {view_type} "
                        f"(only NETLIST supported)"
                    )

    if netlist_view is None:
        _logger.info(f"Cell {cell_name} has no NETLIST view; skipping")
        return None, None

    # Parse interface (ports)
    pins: list[str] = []
    contents: Optional[Union[str, list]] = None

    for view_child in netlist_view[1:]:
        if not isinstance(view_child, list) or len(view_child) < 1:
            continue

        vchild_head = view_child[0]
        if not isinstance(vchild_head, str):
            continue

        if vchild_head.lower() == "interface":
            pins = _parse_interface(view_child)
        elif vchild_head.lower() == "contents":
            contents = view_child

    subckt = SubcktDef(name=cell_name, pins=pins)
    return subckt, contents


def _parse_interface(interface_node: Union[str, list]) -> list[str]:
    """Parse (interface ...) and extract port names, expanding bus ports.

    Args:
        interface_node: (interface ...) s-expression.

    Returns:
        List of port names (bit-level, MSB-first for buses).

    Raises:
        NetlistParseError: On malformed port or unsupported bus form.
    """
    pins: list[str] = []

    if not isinstance(interface_node, list):
        return pins

    for child in interface_node[1:]:
        if not isinstance(child, list) or len(child) < 1:
            continue

        child_head = child[0]
        if not isinstance(child_head, str) or child_head.lower() != "port":
            continue

        # Port can be:
        # (port name (direction X))
        # (port (array (rename name "name[MSB:LSB]") W) (direction X))
        port_name: Optional[str] = None
        is_array = False
        array_width = 0
        msb_str = ""
        lsb_str = ""

        for port_child in child[1:]:
            if isinstance(port_child, str):
                # Bare port name
                port_name = port_child
            elif isinstance(port_child, list) and len(port_child) > 0:
                pc_head = port_child[0]
                if isinstance(pc_head, str):
                    if pc_head.lower() == "array":
                        is_array = True
                        # (array (rename safe "original[MSB:LSB]") width)
                        if len(port_child) > 2:
                            array_width_node = port_child[2]
                            if isinstance(array_width_node, str):
                                try:
                                    array_width = int(array_width_node)
                                except ValueError:
                                    pass

                            name_node = port_child[1]
                            port_name_try = _unwrap_name(name_node)
                            port_name = port_name_try

                            # Extract MSB:LSB from the original string if available
                            if isinstance(name_node, list) and len(name_node) > 2:
                                orig_str = name_node[2]
                                if isinstance(orig_str, str):
                                    # Parse "name[MSB:LSB]"
                                    m = re.match(
                                        r"(\w+)\[(\d+):(\d+)\]", orig_str
                                    )
                                    if m:
                                        port_name = m.group(1)
                                        msb_str = m.group(2)
                                        lsb_str = m.group(3)

        if port_name:
            if is_array and array_width > 0 and msb_str and lsb_str:
                # Expand bus to bit-level pins, MSB-first
                msb = int(msb_str)
                lsb = int(lsb_str)
                sign = 1 if msb >= lsb else -1
                for k in range(array_width):
                    bit_idx = msb - sign * k
                    pins.append(f"{port_name}[{bit_idx}]")
            else:
                # Single-bit port
                pins.append(port_name)

    return pins


def _parse_contents(
    contents_node: Union[str, list], parent_cell: str, subckts: dict[str, SubcktDef]
) -> list[Instance]:
    """Parse (contents ...) and extract instances with connectivity.

    Args:
        contents_node: (contents ...) s-expression.
        parent_cell: Name of the parent cell.
        subckts: Dict of SubcktDef for pin-order lookup.

    Returns:
        List of Instance objects.

    Raises:
        NetlistParseError: On malformed structure.
    """
    instances: list[Instance] = []

    if not isinstance(contents_node, list):
        return instances

    # H3: Hoist owner_cell_pins lookup once at the top
    owner_cell_pins = subckts[parent_cell].pins if parent_cell in subckts else None

    # H1+H2: Fused pass — single walk of contents_node[1:] collecting nets and instances
    net_map: dict[tuple[str, str], str] = {}
    instance_blocks: list[Union[str, list]] = []

    for child in contents_node[1:]:
        if not isinstance(child, list) or len(child) < 1:
            continue

        child_head = child[0]
        if not isinstance(child_head, str):
            continue

        head_lower = child_head.lower()

        if head_lower == "net":
            # (net name (joined (portref ...) (portref ...) ...))
            net_name: Optional[str] = None
            if len(child) > 1 and isinstance(child[1], str):
                net_name = child[1]

            if not net_name:
                continue

            # Extract all portrefs in this net
            for net_child in child[2:]:
                if isinstance(net_child, list) and len(net_child) > 0:
                    nc_head = net_child[0]
                    if isinstance(nc_head, str) and nc_head.lower() == "joined":
                        # Process all portrefs in the joined list
                        for portref_expr in net_child[1:]:
                            if isinstance(portref_expr, list) and len(portref_expr) > 0:
                                pref_head = portref_expr[0]
                                if isinstance(pref_head, str) and pref_head.lower() == "portref":
                                    # Extract (instance_name, port_name) and record
                                    instance_name, port_name = _extract_portref(
                                        portref_expr,
                                        owner_cell_pins=owner_cell_pins,
                                    )
                                    # H2: Only insert if instance_name is not None
                                    if instance_name is not None and port_name:
                                        net_map[(instance_name, port_name)] = net_name

        elif head_lower == "instance":
            # Collect instance block for second phase
            instance_blocks.append(child)

    # Build instances with positional nets[]
    for child in instance_blocks:
        # (instance name (viewref vname (cellref cname (libraryref lname))))
        if len(child) < 2:
            continue

        instance_name = child[1]
        if not isinstance(instance_name, str):
            instance_name = _unwrap_name(instance_name)

        cell_type: Optional[str] = None
        for inst_child in child[2:]:
            if isinstance(inst_child, list) and len(inst_child) > 0:
                ic_head = inst_child[0]
                if isinstance(ic_head, str) and ic_head.lower() == "viewref":
                    # (viewref vname (cellref cname (libraryref lname)))
                    for vc_child in inst_child[1:]:
                        if isinstance(vc_child, list) and len(vc_child) > 0:
                            vcc_head = vc_child[0]
                            if isinstance(vcc_head, str) and vcc_head.lower() == "cellref":
                                if len(vc_child) > 1:
                                    cell_ref_node = vc_child[1]
                                    cell_type = _unwrap_name(cell_ref_node)

        if cell_type and cell_type in subckts:
            cell_def = subckts[cell_type]
            # Build nets[] in pin order
            nets: list[str] = []
            for pin in cell_def.pins:
                net_name = net_map.get((instance_name, pin), "")
                nets.append(net_name)

            inst = Instance(
                name=instance_name, parent_cell=parent_cell, cell_type=cell_type, nets=nets
            )
            instances.append(inst)

    return instances


def _extract_portref(
    portref_node: Union[str, list], owner_cell_pins: Optional[list[str]] = None
) -> tuple[Optional[str], str]:
    """Extract (instance_name_or_None, port_name) from (portref ...).

    Handles (member <bus> <idx>) via bus_ordering_spec rule.

    Args:
        portref_node: (portref ...) s-expression.
        owner_cell_pins: Pin list of the owner cell (for bus bit lookup).

    Returns:
        (instance_name_or_None, port_name) tuple.
    """
    if not isinstance(portref_node, list) or len(portref_node) < 1:
        return None, ""

    # (portref <port_or_member> [(instanceref <iname>)])
    instance_name: Optional[str] = None
    port_name = ""

    for child in portref_node[1:]:
        if isinstance(child, str):
            # Bare port name
            port_name = child
        elif isinstance(child, list) and len(child) > 0:
            child_head = child[0]
            if isinstance(child_head, str):
                if child_head.lower() == "member":
                    # (member <bus> <idx>) — lookup via owner_cell_pins
                    if len(child) > 2 and owner_cell_pins:
                        bus_name = child[1]
                        idx_str = child[2]
                        if isinstance(bus_name, str) and isinstance(idx_str, str):
                            try:
                                idx = int(idx_str)
                                # bus_ordering_spec: pins[idx] gives the HDL bit name directly
                                if 0 <= idx < len(owner_cell_pins):
                                    port_name = owner_cell_pins[idx]
                            except (ValueError, IndexError):
                                pass
                elif child_head.lower() == "instanceref":
                    if len(child) > 1 and isinstance(child[1], str):
                        instance_name = child[1]

    return instance_name, port_name


def _walk_root(root: Union[str, list], subckts: dict[str, SubcktDef], instances: list[Instance]) -> None:
    """Walk (edif ...) root, extracting libraries and cells.

    Args:
        root: Root s-expression.
        subckts: Dict to populate with SubcktDef objects.
        instances: List to append Instance objects to.

    Raises:
        NetlistParseError: On unsupported EDIF version or other errors.
    """
    if not isinstance(root, list) or len(root) < 1:
        raise NetlistParseError("Invalid EDIF: root must be a list")

    # Check root head
    if isinstance(root[0], str) and root[0].lower() == "edif":
        # Valid EDIF root
        pass
    else:
        raise NetlistParseError("Invalid EDIF: root must be (edif ...)")

    # Check and log EDIF version
    for child in root[1:]:
        if isinstance(child, list) and len(child) > 0:
            if isinstance(child[0], str) and child[0].lower() == "edifversion":
                if len(child) > 1:
                    major_str = child[1]
                    if isinstance(major_str, str):
                        try:
                            major = int(major_str)
                            if major not in (2, 3, 4):
                                raise NetlistParseError(
                                    f"Unsupported EDIF major version: {major} "
                                    f"(only 2, 3, 4 supported)"
                                )
                            _logger.info(f"EDIF version: {major}.x")
                        except ValueError:
                            pass

    # Collect libraries
    libraries = _collect_libraries(root)

    for lib_node in libraries:
        if not isinstance(lib_node, list) or len(lib_node) < 2:
            continue

        lib_name_node = lib_node[1]
        if isinstance(lib_name_node, str):
            lib_name = lib_name_node
        else:
            lib_name = _unwrap_name(lib_name_node)

        # Walk cells in this library
        for lib_child in lib_node[2:]:
            if isinstance(lib_child, list) and len(lib_child) > 0:
                lc_head = lib_child[0]
                if isinstance(lc_head, str) and lc_head.lower() == "cell":
                    subckt, contents = _parse_cell(lib_child, lib_name)
                    if subckt:
                        subckts[subckt.name] = subckt
                        if contents:
                            cell_instances = _parse_contents(contents, subckt.name, subckts)
                            instances.extend(cell_instances)
