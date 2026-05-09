from __future__ import annotations

import re
from typing import Optional

from nettrace.parsers.verilog.preprocess import _sv_resolve_bound, _sv_resolve_width_expr

# Pre-compiled patterns
_RE_INST = re.compile(r"\b([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)?\(")
_RE_PARAM_BLOCK = re.compile(r"#\s*\((?:[^()]*|\((?:[^()]*|\([^()]*\))*\))*\)")
_RE_PIN = re.compile(r"\.(\w+)\s*\(")

_KEYWORDS = frozenset(
    {
        "module",
        "endmodule",
        "input",
        "output",
        "inout",
        "wire",
        "reg",
        "logic",
        "real",
        "integer",
        "time",
        "string",
        "void",
        "assign",
        "always",
        "always_ff",
        "always_comb",
        "always_latch",
        "initial",
        "generate",
        "endgenerate",
        "for",
        "if",
        "else",
        "case",
        "casex",
        "casez",
        "default",
        "endcase",
        "begin",
        "end",
        "parameter",
        "localparam",
        "genvar",
        "function",
        "endfunction",
        "task",
        "endtask",
        "assert",
        "assume",
        "cover",
        "property",
        "sequence",
        "typedef",
        "enum",
        "struct",
        "union",
        "interface",
        "endinterface",
        "modport",
        "import",
        "export",
        "virtual",
        "class",
        "endclass",
        "bind",
        "disable",
        "fork",
        "join",
        "wait",
        "return",
        "automatic",
        "covergroup",
        "constraint",
        "package",
        "endpackage",
    }
)

_PRIMITIVES = frozenset(
    {
        "and",
        "nand",
        "or",
        "nor",
        "xor",
        "xnor",
        "not",
        "buf",
        "bufif0",
        "bufif1",
        "notif0",
        "notif1",
        "pmos",
        "nmos",
        "cmos",
        "rpmos",
        "rnmos",
        "rcmos",
        "tran",
        "tranif0",
        "tranif1",
        "rtran",
        "rtranif0",
        "rtranif1",
        "pullup",
        "pulldown",
    }
)

_RE_BUS_DECL = re.compile(
    r"\b(?:input|output|inout|wire|logic|reg)\s+(?:wire\s+|logic\s+|reg\s+)?"
    r"\[\s*(\d+)\s*:\s*(\d+)\s*\]\s+(\w+)"
)
_RE_BUS_DECL_2D = re.compile(
    r"\b(?:input|output|inout|wire|logic|reg)\s+(?:wire\s+|logic\s+|reg\s+)?"
    r"\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s*"
    r"\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s+(\w+)"
)
_RE_BUS_DECL_UNPACKED = re.compile(
    r"\b(?:input|output|inout|wire|logic|reg)\s+(?:wire\s+|logic\s+|reg\s+)?"
    r"\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s+(\w+)\s*"
    r"\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s*[;,)]"
)
_RE_BUS_DECL_MULTI = re.compile(
    r"\b(?:input|output|inout|wire|logic|reg)\s+(?:wire\s+|logic\s+|reg\s+)?"
    r"\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s+"
    r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*[;,)]"
)
_RE_ASSIGN = re.compile(r"\bassign\s+(.+?)\s*=\s*(.+?)\s*;", re.DOTALL)
_RE_BEGIN_END = re.compile(r"\b(begin|end)\b")
_RE_GENFOR = re.compile(
    r"\bfor\s*\(\s*(?:genvar\s+)?(?:int\s+)?(\w+)\s*=\s*([^;]+?)\s*;\s*\w+\s*(<=?)\s*([^;]+?)\s*;\s*([^)]+?)\s*\)"
    r"\s*begin\s*:\s*(\w+)"
)


def _sv_make_port_entry(name: str, hi: Optional[int] = None, lo: Optional[int] = None) -> dict:
    """Build a port-info dict (scalar or bus, MSB-first bits)."""
    if hi is None or lo is None:
        return {"name": name, "bits": [name], "hi": None, "lo": None}
    if hi >= lo:
        order = range(hi, lo - 1, -1)
    else:
        order = range(lo, hi - 1, -1)
    bits = [f"{name}[{i}]" for i in order]
    return {"name": name, "bits": bits, "hi": hi, "lo": lo}


def _sv_parse_ports(port_text: str, define_values: Optional[dict[str, int]] = None) -> list:
    """Extract ordered port info from module port declaration text."""
    port_text = re.sub(r"\s+", " ", port_text).strip()
    if not port_text:
        return []
    items = []
    depth = 0
    buf = []
    for ch in port_text:
        if ch in ("(", "["):
            depth += 1
            buf.append(ch)
        elif ch in (")", "]"):
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            items.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        items.append("".join(buf).strip())
    ports = []
    for item in items:
        item = item.strip()
        if not item:
            continue
        im = re.match(r"(\w+)\.(\w+)\s+(\w+)", item)
        if im and im.group(1) not in ("input", "output", "inout", "logic", "wire", "reg", "real"):
            ports.append(_sv_make_port_entry(im.group(3)))
            continue
        item = re.sub(r"^(input|output|inout)\s+", "", item)
        item = re.sub(r"^(logic|reg|wire|real|integer)\s+", "", item)
        item = item.strip()
        hi = lo = None
        inner_hi = inner_lo = None
        bm = re.match(r"\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s*(.*)$", item)
        if bm:
            hi_expr = bm.group(1)
            lo_expr = bm.group(2)
            rest = bm.group(3).strip()
            hi = _sv_resolve_width_expr(hi_expr, define_values)
            lo = _sv_resolve_width_expr(lo_expr, define_values)
            # 2D port? `[hi:lo][inner_hi:inner_lo] name`
            bm2 = re.match(r"\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s*(.*)$", rest)
            if bm2:
                inner_hi = _sv_resolve_width_expr(bm2.group(1), define_values)
                inner_lo = _sv_resolve_width_expr(bm2.group(2), define_values)
                rest = bm2.group(3).strip()
            item = rest
        else:
            item = re.sub(r"\[[^\]]*\]\s*", "", item).strip()
        if item and re.match(r"^[A-Za-z_]\w*$", item):
            if hi is not None and lo is not None and inner_hi is not None and inner_lo is not None:
                # 2D port: expand to outer*inner individual bits
                outer = range(hi, lo - 1, -1) if hi >= lo else range(lo, hi - 1, -1)
                inner = (
                    range(inner_hi, inner_lo - 1, -1)
                    if inner_hi >= inner_lo
                    else range(inner_lo, inner_hi - 1, -1)
                )
                bits = [f"{item}[{i}][{j}]" for i in outer for j in inner]
                ports.append({"name": item, "bits": bits, "hi": hi, "lo": lo})
            elif hi is not None and lo is not None:
                ports.append(_sv_make_port_entry(item, hi, lo))
            else:
                ports.append(_sv_make_port_entry(item))
    return ports


def _sv_split_concat_pieces(inner: str) -> list:
    """Split text inside a {...} concatenation by top-level commas."""
    pieces = []
    depth = 0
    buf = []
    for ch in inner:
        if ch in ("{", "(", "["):
            depth += 1
            buf.append(ch)
        elif ch in ("}", ")", "]"):
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            pieces.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        pieces.append("".join(buf).strip())
    return pieces


def _sv_expand_piece(
    piece: str,
    define_values: Optional[dict[str, int]] = None,
    port_signals: Optional[dict] = None,
    wires_2d: Optional[dict[str, int]] = None,
) -> Optional[list]:
    """Expand a single concatenation piece into a list of per-bit net names."""
    if define_values is None:
        define_values = {}
    if wires_2d is None:
        wires_2d = {}
    p = piece.strip()
    if not p:
        return None
    if p.startswith("{") and p.endswith("}"):
        return _sv_expand_concat_str(p[1:-1], define_values, port_signals, wires_2d)
    rm = re.match(r"^([^\s{}]+)\s*\{(.*)\}$", p)
    if rm:
        n_expr = rm.group(1)
        inner = rm.group(2)
        n = _sv_resolve_bound(n_expr, define_values or {})
        if n is not None:
            sub = _sv_expand_concat_str(inner, define_values, port_signals, wires_2d)
            if sub is not None:
                return sub * n
        return None
    # Width-cast WIDTH'(EXPR) — strip cast, expand inner.
    cm = re.match(r"^[`]?[A-Za-z_0-9]+\s*'\s*\((.+)\)\s*$", p, re.DOTALL)
    if cm:
        return _sv_expand_piece(cm.group(1).strip(), define_values, port_signals, wires_2d)
    lm = re.match(r"^(\d+)'([bBoOdDhH])([0-9a-fA-FxXzZ_?]+)$", p)
    if lm:
        width = int(lm.group(1))
        base = lm.group(2).lower()
        digits = lm.group(3).replace("_", "")
        try:
            if base == "b":
                bits = digits.zfill(width)[-width:]
            elif base == "o":
                val = int(digits, 8)
                bits = bin(val)[2:].zfill(width)[-width:]
            elif base == "d":
                val = int(digits, 10)
                bits = bin(val)[2:].zfill(width)[-width:]
            elif base == "h":
                val = int(digits, 16)
                bits = bin(val)[2:].zfill(width)[-width:]
            else:
                return None
            return [f"1'b{c}" for c in bits]
        except Exception:
            return None
    if p in ("0", "1"):
        return [f"1'b{p}"]
    dm = re.match(
        r"^([A-Za-z_]\w*)\s*\[\s*([^\]]+?)\s*\]\s*"
        r"\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s*$",
        p,
    )
    if dm:
        name = dm.group(1)
        idx_expr = dm.group(2).strip()
        idx = _sv_resolve_bound(idx_expr, define_values or {})
        hi = _sv_resolve_bound(dm.group(3), define_values or {})
        lo = _sv_resolve_bound(dm.group(4), define_values or {})
        if hi is None or lo is None:
            return None
        idx_str = str(idx) if idx is not None else idx_expr
        if hi >= lo:
            return [f"{name}[{idx_str}][{i}]" for i in range(hi, lo - 1, -1)]
        else:
            return [f"{name}[{idx_str}][{i}]" for i in range(lo, hi - 1, -1)]
    dm2 = re.match(
        r"^([A-Za-z_]\w*)\s*\[\s*([^\]]+?)\s*\]\s*"
        r"\[\s*([^\]]+?)\s*\]\s*$",
        p,
    )
    if dm2:
        name = dm2.group(1)
        idx_expr = dm2.group(2).strip()
        bit_expr = dm2.group(3).strip()
        idx = _sv_resolve_bound(idx_expr, define_values or {})
        bit = _sv_resolve_bound(bit_expr, define_values or {})
        idx_str = str(idx) if idx is not None else idx_expr
        bit_str = str(bit) if bit is not None else bit_expr
        return [f"{name}[{idx_str}][{bit_str}]"]
    bm = re.match(r"^([A-Za-z_]\w*)\s*\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s*$", p)
    if bm:
        name = bm.group(1)
        hi = _sv_resolve_bound(bm.group(2), define_values or {})
        lo = _sv_resolve_bound(bm.group(3), define_values or {})
        if hi is None or lo is None:
            return None
        if hi >= lo:
            return [f"{name}[{i}]" for i in range(hi, lo - 1, -1)]
        else:
            return [f"{name}[{i}]" for i in range(lo, hi - 1, -1)]
    sm = re.match(r"^([A-Za-z_]\w*)\s*\[\s*([^\]]+?)\s*\]\s*$", p)
    if sm:
        name = sm.group(1)
        idx_expr = sm.group(2).strip()
        idx = _sv_resolve_bound(idx_expr, define_values or {})
        inner_w = (wires_2d or {}).get(name)
        idx_str = str(idx) if idx is not None else idx_expr
        if inner_w is not None and inner_w > 0:
            return [f"{name}[{idx_str}][{i}]" for i in range(inner_w - 1, -1, -1)]
        if idx is None:
            return [f"{name}[{idx_expr}]"]
        return [f"{name}[{idx}]"]
    if re.match(r"^[A-Za-z_]\w*$", p):
        return [p]
    return None


def _sv_expand_concat_str(
    inner: str,
    define_values: Optional[dict[str, int]] = None,
    port_signals: Optional[dict] = None,
    wires_2d: Optional[dict[str, int]] = None,
) -> Optional[list]:
    """Expand concatenation text to per-bit net names."""
    if define_values is None:
        define_values = {}
    if wires_2d is None:
        wires_2d = {}
    pieces = _sv_split_concat_pieces(inner)
    out = []
    for piece in pieces:
        bits = _sv_expand_piece(piece, define_values, port_signals, wires_2d)
        if bits is None:
            return None
        out.extend(bits)
    return out


def _sv_expand_pin_net(
    net_str: str,
    width: int,
    define_values: Optional[dict[str, int]] = None,
    wires_2d: Optional[dict[str, int]] = None,
) -> Optional[list]:
    """Expand an instance pin's net expression to a list of `width` bit-nets."""
    if define_values is None:
        define_values = {}
    if wires_2d is None:
        wires_2d = {}
    if width <= 0:
        return []
    s = net_str.strip()
    if not s:
        return [""] * width
    if s.startswith("{") and s.endswith("}"):
        bits = _sv_expand_concat_str(s[1:-1], define_values, None, wires_2d)
        if bits is None:
            return None
        if len(bits) != width:
            return None
        return bits
    bits = _sv_expand_piece(s, define_values, None, wires_2d)
    if bits is not None:
        if len(bits) == width:
            return bits
        if width > 1 and len(bits) == 1 and re.match(r"^[A-Za-z_]\w*$", s):
            name = s
            # 2D wire used whole: emit [outer][inner] bits to match port-side
            # expansion (otherwise port pins use [i][j] but connection uses
            # [k], breaking pin↔net mapping).
            inner_w = (wires_2d or {}).get(name)
            if inner_w and width % inner_w == 0:
                outer_w = width // inner_w
                return [
                    f"{name}[{i}][{j}]"
                    for i in range(outer_w - 1, -1, -1)
                    for j in range(inner_w - 1, -1, -1)
                ]
            return [f"{name}[{i}]" for i in range(width - 1, -1, -1)]
        return None
    return None


def _sv_find_begin_end(text: str, begin_pos: int) -> int:
    """Find matching 'end' for a 'begin' at begin_pos. Returns index past 'end'."""
    depth = 1
    i = begin_pos
    n = len(text)
    while i < n and depth > 0:
        m = _RE_BEGIN_END.search(text, i)
        if not m:
            break
        if m.group(1) == "begin":
            depth += 1
        else:
            depth -= 1
        i = m.end()
    return i


def _sv_parse_step(incr_expr: str, define_values: Optional[dict[str, int]] = None) -> Optional[int]:
    """Parse generate-for loop step expression."""
    if define_values is None:
        define_values = {}
    incr = incr_expr.strip()
    if "++" in incr:
        return 1
    m = re.match(r"\w+\s*\+=\s*(.+)", incr)
    if m:
        return _sv_resolve_bound(m.group(1), define_values or {})
    m = re.match(r"\w+\s*=\s*\w+\s*\+\s*(.+)", incr)
    if m:
        return _sv_resolve_bound(m.group(1), define_values or {})
    return None


def _sv_extract_wires_2d(body: str, define_values: Optional[dict[str, int]] = None) -> dict:
    """Scan a module body for 2D packed array declarations.
    Returns {wire_name: inner_width}."""
    if define_values is None:
        define_values = {}
    out = {}
    dvs = define_values or {}
    for m in _RE_BUS_DECL_2D.finditer(body):
        inner_hi = _sv_resolve_bound(m.group(3), dvs)
        inner_lo = _sv_resolve_bound(m.group(4), dvs)
        name = m.group(5)
        if inner_hi is None or inner_lo is None:
            continue
        width = abs(inner_hi - inner_lo) + 1
        if width > 0:
            out[name] = width
    for m in _RE_BUS_DECL_UNPACKED.finditer(body):
        p_hi = _sv_resolve_bound(m.group(1), dvs)
        p_lo = _sv_resolve_bound(m.group(2), dvs)
        name = m.group(3)
        if p_hi is None or p_lo is None:
            continue
        width = abs(p_hi - p_lo) + 1
        if width > 0 and name not in out:
            out[name] = width
    return out


def _sv_extract_wire_widths_1d(body: str, define_values: Optional[dict[str, int]] = None) -> dict:
    """Return {wire_name: width} for plain 1D bus declarations.
    Handles multi-name declarations and expression bounds."""
    if define_values is None:
        define_values = {}
    out = {}
    dvs = define_values or {}
    for m in _RE_BUS_DECL_MULTI.finditer(body):
        hi = _sv_resolve_bound(m.group(1), dvs)
        lo = _sv_resolve_bound(m.group(2), dvs)
        if hi is None or lo is None:
            continue
        width = abs(hi - lo) + 1
        if width <= 0:
            continue
        for name in re.split(r"\s*,\s*", m.group(3).strip()):
            if name and name not in out:
                out[name] = width
    return out


def _sv_expand_assign_side(
    s: str,
    define_values: Optional[dict[str, int]],
    wire_widths_1d: dict[str, int],
    wires_2d: dict[str, int],
) -> Optional[list]:
    """Expand one side of an `assign LHS = RHS;` into MSB-first bit names."""
    if define_values is None:
        define_values = {}
    s = s.strip()
    if not s:
        return None
    if s.startswith("{") and s.endswith("}"):
        return _sv_expand_concat_str(s[1:-1], define_values, None, wires_2d)
    if re.match(r"^[\.A-Za-z_]\w*$", s):
        w = (wire_widths_1d or {}).get(s)
        if w is not None and w > 1:
            return [f"{s}[{i}]" for i in range(w - 1, -1, -1)]
        return [s]
    return _sv_expand_piece(s, define_values, None, wires_2d)


def _sv_unroll_generate_for_blocks(
    body: str, define_values: Optional[dict[str, int]] = None
) -> str:
    """
    Pre-processing helper: scan body for generate-for blocks and unroll them.

    For each generate-for block matched by _RE_GENFOR, substitute the block
    with N copies of its inner body where the loop variable has been replaced
    by the corresponding integer literal. Mirrors the in-place expansion already
    done inside _sv_extract_instances at lines 666-697, but emits the result
    as a single string suitable for downstream consumers (alias extraction).

    Inputs:
        body: Raw module body text
        define_values: Resolved parameter/macro values for bound resolution (optional, defaults to {})

    Outputs:
        Transformed body string with generate-for blocks unrolled. If a generate-for block
        has unresolvable bounds (start/stop/step is None), it is preserved verbatim.

    Notes:
        Uses the same regex (_RE_GENFOR), helpers (_sv_find_begin_end, _sv_resolve_bound,
        _sv_parse_step), and loop-variable substitution pattern as _sv_extract_instances.
        Single-pass unroll: outer loops produce inner-loop bodies repeated N times.
        For nested generate-for + assign, apply iteration up to depth 4 if needed.
    """
    if define_values is None:
        define_values = {}

    result = []
    last = 0

    for m in _RE_GENFOR.finditer(body):
        if m.start() < last:
            continue
        # Append text before the match
        result.append(body[last : m.start()])

        var = m.group(1)
        start_expr = m.group(2)
        cmp_op = m.group(3)
        bound_expr = m.group(4)
        incr_expr = m.group(5)
        label = m.group(6)

        start = _sv_resolve_bound(start_expr, define_values)
        stop = _sv_resolve_bound(bound_expr, define_values)
        step = _sv_parse_step(incr_expr, define_values)

        # If bounds are unresolvable, preserve block verbatim
        if start is None or stop is None or step is None:
            begin_end = m.end()
            block_end = _sv_find_begin_end(body, begin_end)
            result.append(body[m.start() : block_end])
            last = block_end
            continue

        if cmp_op == "<=":
            stop += 1

        begin_end = m.end()
        block_end = _sv_find_begin_end(body, begin_end)
        end_kw = body.rfind("end", begin_end, block_end)
        block_body = body[begin_end:end_kw]

        # Expand the loop: N copies with loop variable replaced
        for i in range(start, stop, step):
            expanded = re.sub(r"\b" + var + r"\b", str(i), block_body)
            result.append(expanded)

        last = block_end

    # Append remaining text after last match
    result.append(body[last:])
    return "".join(result)


def _sv_extract_alias_pairs(
    body: str,
    define_values: Optional[dict[str, int]],
    wire_widths_1d: dict[str, int],
    wires_2d: dict[str, int],
) -> list:
    """Extract per-bit alias pairs from `assign LHS = RHS;` statements.

    This function unrolls generate-for blocks in the body before extracting aliases,
    so that alias pairs reflect concrete per-iteration indices (e.g. out[0]->in[0])
    rather than literal loop-variable forms (e.g. out[i]->in[i]).
    """
    if define_values is None:
        define_values = {}
    body = _sv_unroll_generate_for_blocks(body, define_values)
    pairs = []
    for m in _RE_ASSIGN.finditer(body):
        lhs = m.group(1).strip()
        rhs = m.group(2).strip()
        rhs_outside_braces = re.sub(r"\{[^{}]*\}", "", rhs)
        if re.search(r"[?&|^!~+\-*/<>]", rhs_outside_braces):
            continue
        lhs_bits = _sv_expand_assign_side(lhs, define_values, wire_widths_1d, wires_2d)
        rhs_bits = _sv_expand_assign_side(rhs, define_values, wire_widths_1d, wires_2d)
        if lhs_bits is None or rhs_bits is None:
            continue
        if len(lhs_bits) != len(rhs_bits):
            continue
        for lhs_bit, rhs_bit in zip(lhs_bits, rhs_bits):
            if lhs_bit and rhs_bit and lhs_bit != rhs_bit:
                pairs.append((lhs_bit, rhs_bit))
    return pairs


def _sv_match_paren(text: str, start: int) -> int:
    """Index of matching ')' starting just after the '('. Returns -1 if unmatched."""
    depth = 1
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _sv_extract_instances_flat(body: str, prefix: str = "") -> list:
    """Extract instances from body text. Prefix is prepended to instance names."""
    overrides_at = {}
    pieces = []
    last = 0
    for pm in _RE_PARAM_BLOCK.finditer(body):
        pieces.append(body[last : pm.start()])
        inner = body[pm.start() + 2 : pm.end() - 1]
        # Parse param overrides from #(...) block
        overrides = {}
        for pin_m in _RE_PIN.finditer(inner):
            pname = pin_m.group(1)
            net_start = pin_m.end()
            net_close = _sv_match_paren(inner, net_start)
            if net_close < 0:
                continue
            overrides[pname] = re.sub(r"\s+", " ", inner[net_start:net_close].strip())
        overrides_at[pm.end()] = overrides
        pieces.append(" " * (pm.end() - pm.start()))
        last = pm.end()
    pieces.append(body[last:])
    body = "".join(pieces)
    instances = []
    for m in _RE_INST.finditer(body):
        cell = m.group(1)
        inst = m.group(2)
        if cell in _KEYWORDS:
            continue
        open_pos = m.end() - 1
        close = _sv_match_paren(body, open_pos + 1)
        if close < 0:
            continue
        inner = body[open_pos + 1 : close]
        if prefix:
            inst = prefix + inst
        overrides = {}
        cell_end = m.start(1) + len(cell)
        inst_start = m.start(2)
        for end_idx, ov in overrides_at.items():
            if cell_end <= end_idx <= inst_start:
                overrides = ov
                break
        if cell in _PRIMITIVES:
            nets = [n.strip() for n in inner.split(",") if n.strip()]
            pmap = {f"_p{i}": n for i, n in enumerate(nets)}
            instances.append((inst, cell, pmap, overrides))
            continue
        if "." not in inner:
            continue
        pmap = {}
        for pm2 in _RE_PIN.finditer(inner):
            pin = pm2.group(1)
            net_start = pm2.end()
            net_close = _sv_match_paren(inner, net_start)
            if net_close < 0:
                continue
            pmap[pin] = re.sub(r"\s+", " ", inner[net_start:net_close].strip())
        if pmap:
            instances.append((inst, cell, pmap, overrides))
    return instances


def _sv_extract_instances(
    body: str, define_values: Optional[dict[str, int]] = None, prefix: str = ""
) -> list:
    """Extract instances, expanding generate-for blocks recursively."""
    if define_values is None:
        define_values = {}
    else:
        define_values = dict(define_values)
    instances = []
    last = 0

    # Parse local parameters
    _RE_LOCALPARAM = re.compile(r"\b(?:localparam|parameter)\s+(?:\w+\s+)?(\w+)\s*=\s*([^;,)]+)")
    for lm in _RE_LOCALPARAM.finditer(body):
        name = lm.group(1)
        val = _sv_resolve_bound(lm.group(2), define_values)
        if val is not None:
            define_values[name] = val

    # Handle $size() macro
    sizes = {}
    for bm in _RE_BUS_DECL.finditer(body):
        high, low, sig = int(bm.group(1)), int(bm.group(2)), bm.group(3)
        sizes[sig] = abs(high - low) + 1
    if sizes:

        def _repl_size(m):
            sig = m.group(1)
            return str(sizes[sig]) if sig in sizes else m.group(0)

        _RE_DOLLAR_SIZE = re.compile(r"\$size\s*\(\s*(\w+)\s*\)")
        body = _RE_DOLLAR_SIZE.sub(_repl_size, body)

    # Find and expand generate-for loops
    for m in _RE_GENFOR.finditer(body):
        if m.start() < last:
            continue
        instances.extend(_sv_extract_instances_flat(body[last : m.start()], prefix))
        var = m.group(1)
        start_expr = m.group(2)
        cmp_op = m.group(3)
        bound_expr = m.group(4)
        incr_expr = m.group(5)
        label = m.group(6)
        start = _sv_resolve_bound(start_expr, define_values)
        stop = _sv_resolve_bound(bound_expr, define_values)
        step = _sv_parse_step(incr_expr, define_values)
        if start is None or stop is None or step is None:
            last = m.end()
            continue
        if cmp_op == "<=":
            stop += 1
        begin_end = m.end()
        block_end = _sv_find_begin_end(body, begin_end)
        end_kw = body.rfind("end", begin_end, block_end)
        block_body = body[begin_end:end_kw]
        for i in range(start, stop, step):
            expanded = re.sub(r"\b" + var + r"\b", str(i), block_body)
            iter_prefix = f"{prefix}{label}[{i}]."
            instances.extend(_sv_extract_instances(expanded, define_values, iter_prefix))
        last = block_end
    instances.extend(_sv_extract_instances_flat(body[last:], prefix))
    return instances
