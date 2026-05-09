#!/usr/bin/env python3
"""
Netlist Parser

Parses CDL, SPICE, Verilog/SystemVerilog, and Spectre netlists into a
common in-memory model (SubcktDef + Instance + per-cell aliases).

Format auto-detection from file content:
  - CDL:     .SUBCKT/.ENDS with `*.PININFO` markers
  - SPICE:   .subckt/.ends
  - Spectre: subckt/ends with (nets) cell_type
  - Verilog/SV: module/endmodule with named .pin(net) connections
  - PSV:     .psv files with $var$ template variables

For SystemVerilog directories, runs full elaboration: define-value
resolution, generate-loop expansion, parameter specialization, 2D packed
arrays, multi-bit pin/concat expansion, and per-bit `assign`-alias
decomposition.

Public API:
    from netlist_parser import (
        NetlistParser, SubcktDef, Instance, merge_aliases_into_subckt
    )

Companion CLI tools that import this library:
  - netlist_trace.py    — bidirectional signal tracer (CLI)
  - rtl_preparser.py    — JSON cache builder for SV directories (CLI)
"""

import glob
import json
import os
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from multiprocessing import Pool, cpu_count
from typing import Dict, List, Optional


@dataclass
class SubcktDef:
    """Represents a .SUBCKT/module definition"""
    name: str
    pins: List[str]
    pin_to_pos: Dict[str, int] = field(default_factory=dict)
    # Map of net -> canonical-net for SystemVerilog `assign A = B;` aliases.
    # Two nets that share a canonical are connected by a continuous-assign.
    aliases: Dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        self.pin_to_pos = {pin: i for i, pin in enumerate(self.pins)}


def merge_aliases_into_subckt(sub: 'SubcktDef', pairs):
    """Merge a list of (lhs, rhs) `assign` pairs into sub.aliases using
    union-find. Port names (members of sub.pins) are preferred as roots so
    that going DOWN from a parent into the cell still resolves to the
    port-named net. Existing aliases on sub are kept and unioned with the
    new pairs."""
    pins_set = set(sub.pins)
    parent = {}

    # Seed union-find with existing aliases
    for n, c in sub.aliases.items():
        parent.setdefault(n, n)
        parent.setdefault(c, c)

    def find(x):
        # Iterative path-compression
        root = x
        while parent.setdefault(root, root) != root:
            root = parent[root]
        while parent[x] != root:
            parent[x], x = root, parent[x]
        return root

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra == rb:
            return
        a_is_port = ra in pins_set
        b_is_port = rb in pins_set
        if a_is_port and not b_is_port:
            parent[rb] = ra
        elif b_is_port and not a_is_port:
            parent[ra] = rb
        else:
            # Deterministic tie-break
            if ra < rb:
                parent[rb] = ra
            else:
                parent[ra] = rb

    # Replay existing alias edges first
    for n, c in sub.aliases.items():
        union(n, c)
    for lhs, rhs in pairs:
        if lhs == rhs:
            continue
        union(lhs, rhs)

    # Build canonical map: every net that has a non-self root gets recorded
    new_aliases = {}
    for net in list(parent.keys()):
        root = find(net)
        if root != net:
            new_aliases[net] = root
    sub.aliases = new_aliases

# ── SV elaboration helpers (migrated from netlist_preparse.py) ──────────
# These functions parse a SystemVerilog source tree into module/instance
# dicts with full elaboration: define-value resolution, generate-loop
# expansion, parameter specialization, 2D arrays, multi-bit pin/concat
# expansion, and per-bit assign-alias decomposition.
#
# They are pure module-level functions with no class state. NetlistParser
# orchestrates them; the standalone preparser script (netlist_preparse.py)
# is now a thin wrapper that imports NetlistParser and calls dump_json().

# Pre-compiled patterns
_RE_IFDEF   = re.compile(r'^\s*`ifdef\s+(\w+)')
_RE_IFNDEF  = re.compile(r'^\s*`ifndef\s+(\w+)')
_RE_ELSE    = re.compile(r'^\s*`else\b')
_RE_ENDIF   = re.compile(r'^\s*`endif\b')
_RE_INCLUDE = re.compile(r'^\s*`include\b')
_RE_PREPROC = re.compile(r'^\s*`(timescale|define|undef)\b')
_RE_MODULE  = re.compile(r'\bmodule\s+(\w+)')
_RE_ENDMOD  = re.compile(r'\bendmodule\b')
_RE_PARAM_BLOCK = re.compile(
    r'#\s*\((?:[^()]*|\((?:[^()]*|\([^()]*\))*\))*\)'
)
_RE_INST = re.compile(r'\b([A-Za-z_]\w*)\s+([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)?\(')
_RE_PIN  = re.compile(r'\.(\w+)\s*\(')
_RE_GENFOR = re.compile(
    r'\bfor\s*\(\s*(?:genvar\s+)?(?:int\s+)?(\w+)\s*=\s*([^;]+?)\s*;\s*\w+\s*(<=?)\s*([^;]+?)\s*;\s*([^)]+?)\s*\)'
    r'\s*begin\s*:\s*(\w+)'
)
_RE_LOCALPARAM = re.compile(r'\b(?:localparam|parameter)\s+(?:\w+\s+)?(\w+)\s*=\s*([^;,)]+)')
_RE_BUS_DECL = re.compile(
    r'\b(?:input|output|inout|wire|logic|reg)\s+(?:wire\s+|logic\s+|reg\s+)?'
    r'\[\s*(\d+)\s*:\s*(\d+)\s*\]\s+(\w+)'
)
_RE_BUS_DECL_2D = re.compile(
    r'\b(?:input|output|inout|wire|logic|reg)\s+(?:wire\s+|logic\s+|reg\s+)?'
    r'\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s*'
    r'\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s+(\w+)'
)
_RE_BUS_DECL_UNPACKED = re.compile(
    r'\b(?:input|output|inout|wire|logic|reg)\s+(?:wire\s+|logic\s+|reg\s+)?'
    r'\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s+(\w+)\s*'
    r'\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s*[;,)]'
)
_RE_BUS_DECL_MULTI = re.compile(
    r'\b(?:input|output|inout|wire|logic|reg)\s+(?:wire\s+|logic\s+|reg\s+)?'
    r'\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s+'
    r'([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*[;,)]'
)
_RE_DOLLAR_SIZE = re.compile(r'\$size\s*\(\s*(\w+)\s*\)')
_RE_BEGIN_END = re.compile(r'\b(begin|end)\b')
_RE_ASSIGN = re.compile(r'\bassign\s+(.+?)\s*=\s*(.+?)\s*;', re.DOTALL)
_RE_DEFINE_VALUE = re.compile(r'^\s*`define\s+(\w+)\s+(.+)')

_KEYWORDS = frozenset({
    'module', 'endmodule', 'input', 'output', 'inout',
    'wire', 'reg', 'logic', 'real', 'integer', 'time', 'string', 'void',
    'assign', 'always', 'always_ff', 'always_comb', 'always_latch',
    'initial', 'generate', 'endgenerate', 'for', 'if', 'else',
    'case', 'casex', 'casez', 'default', 'endcase',
    'begin', 'end', 'parameter', 'localparam', 'genvar',
    'function', 'endfunction', 'task', 'endtask',
    'assert', 'assume', 'cover', 'property', 'sequence',
    'typedef', 'enum', 'struct', 'union', 'interface', 'endinterface',
    'modport', 'import', 'export', 'virtual', 'class', 'endclass',
    'bind', 'disable', 'fork', 'join', 'wait', 'return', 'automatic',
    'covergroup', 'constraint', 'package', 'endpackage',
})

_PRIMITIVES = frozenset({
    'and', 'nand', 'or', 'nor', 'xor', 'xnor', 'not', 'buf',
    'bufif0', 'bufif1', 'notif0', 'notif1',
    'pmos', 'nmos', 'cmos', 'rpmos', 'rnmos', 'rcmos',
    'tran', 'tranif0', 'tranif1', 'rtran', 'rtranif0', 'rtranif1',
    'pullup', 'pulldown',
})

_DEFAULT_DEFINES = set()

_DEFAULT_DEFINE_VALUES = {}

_RE_BRACKET_EXPR = re.compile(r'\[([^\[\]]+)\]')
_RE_SAFE_ARITH   = re.compile(r'^[\d\s+\-*/()]+$')


def _sv_match_paren(text, start):
    """Index of matching ')' starting just after the '('. Returns -1 if unmatched."""
    depth = 1
    i = start
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '(':
            depth += 1
        elif ch == ')':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _sv_substitute_vars(content, tvars):
    for k, v in tvars.items():
        content = content.replace('$' + k + '$', v)
    return content


def _sv_strip_comments(content):
    """Remove both // and /* */ comments in a single pass."""
    out = []
    i = 0
    n = len(content)
    while i < n:
        if content[i] == '/' and i + 1 < n:
            if content[i + 1] == '/':
                j = content.find('\n', i)
                if j < 0:
                    break
                i = j
                continue
            elif content[i + 1] == '*':
                j = content.find('*/', i + 2)
                if j < 0:
                    break
                i = j + 2
                continue
        out.append(content[i])
        i += 1
    return ''.join(out)


def _sv_resolve_inline_ifdefs(line, defines):
    """Resolve `ifdef/`ifndef/`else/`endif appearing mid-line."""
    def _rep_ifdef_else(m):
        return m.group(2) if m.group(1) in defines else m.group(3)
    line = re.sub(r'`ifdef\s+(\w+)\s+(.*?)\s*`else\s+(.*?)\s*`endif',
                  _rep_ifdef_else, line)

    def _rep_ifdef(m):
        return m.group(2) if m.group(1) in defines else ''
    line = re.sub(r'`ifdef\s+(\w+)\s+(.*?)\s*`endif', _rep_ifdef, line)

    def _rep_ifndef_else(m):
        return m.group(2) if m.group(1) not in defines else m.group(3)
    line = re.sub(r'`ifndef\s+(\w+)\s+(.*?)\s*`else\s+(.*?)\s*`endif',
                  _rep_ifndef_else, line)

    def _rep_ifndef(m):
        return m.group(2) if m.group(1) not in defines else ''
    line = re.sub(r'`ifndef\s+(\w+)\s+(.*?)\s*`endif', _rep_ifndef, line)
    return line


def _sv_preprocess(content, defines):
    """Resolve `ifdef/`ifndef/`else/`endif with configurable define set."""
    lines = content.split('\n')
    result = []
    stack = []
    for line in lines:
        s = line.lstrip()
        if ('`ifdef' in s or '`ifndef' in s) and '`endif' in s:
            if (not stack) or stack[-1][0]:
                result.append(_sv_resolve_inline_ifdefs(line, defines))
            continue
        m = _RE_IFDEF.match(s)
        if m:
            parent = (not stack) or stack[-1][0]
            met = m.group(1) in defines
            stack.append((parent and met, parent and not met))
            continue
        m = _RE_IFNDEF.match(s)
        if m:
            parent = (not stack) or stack[-1][0]
            met = m.group(1) not in defines
            stack.append((parent and met, parent and not met))
            continue
        if _RE_ELSE.match(s):
            if stack:
                _, can = stack[-1]
                stack[-1] = (can, False)
            continue
        if _RE_ENDIF.match(s):
            if stack:
                stack.pop()
            continue
        if _RE_INCLUDE.match(s) or _RE_PREPROC.match(s):
            continue
        if (not stack) or stack[-1][0]:
            result.append(line)
    return '\n'.join(result)


_RE_DEFINE_BARE = re.compile(r'^\s*`define\s+(\w+)\s*(?://.*)?$')


def _sv_discover_headers(rtl_dir):
    """Find Verilog header files under rtl_dir for define discovery.
    Returns sorted list of paths to .vh / .svh / .d files."""
    files = []
    for ext in ('vh', 'svh', 'd'):
        files.extend(glob.glob(
            os.path.join(rtl_dir, '**', f'*.{ext}'), recursive=True))
        files.extend(glob.glob(os.path.join(rtl_dir, f'*.{ext}')))
    return sorted(set(files))


def _sv_parse_defines(filepaths, tvars=None):
    """Parse header files and return (defines_set, define_values_dict).

    - defines_set: every macro name that appears in any `define statement
      (with or without value). Used for `ifdef X` decisions.
    - define_values_dict: {name: int} for `define NAME <numeric expr>.
      Used to resolve genfor bounds, bus widths, etc.
    """
    defines = set()
    raw_defs = {}
    for fp in filepaths:
        try:
            with open(fp, 'r', errors='replace') as fh:
                content = fh.read()
        except OSError:
            continue
        if tvars:
            content = _sv_substitute_vars(content, tvars)
        for line in content.split('\n'):
            mv = _RE_DEFINE_VALUE.match(line)
            if mv:
                name = mv.group(1)
                val = mv.group(2).strip()
                ci = val.find('//')
                if ci >= 0:
                    val = val[:ci].strip()
                defines.add(name)
                if val:
                    raw_defs[name] = val
                continue
            mb = _RE_DEFINE_BARE.match(line)
            if mb:
                defines.add(mb.group(1))
    resolved = {}
    for _ in range(5):
        progress = False
        for name, expr in raw_defs.items():
            if name in resolved:
                continue
            def _repl(m):
                ref = m.group(1)
                if ref in resolved:
                    return str(resolved[ref])
                return m.group(0)
            val_str = re.sub(r'`(\w+)', _repl, expr)
            if re.match(r'^[\d\s+\-*/()]+$', val_str):
                try:
                    resolved[name] = int(eval(val_str))
                    progress = True
                except Exception:
                    pass
        if not progress:
            break
    return defines, resolved


# Backwards-compat shim: callers that only need numeric values
def _sv_parse_define_values(filepaths, tvars=None):
    """Legacy entry point that returns ONLY the numeric values dict."""
    _, resolved = _sv_parse_defines(filepaths, tvars)
    return resolved


def _sv_resolve_bound(expr, define_values):
    """Resolve a genfor loop bound expression to an integer."""
    expr = expr.strip()
    if expr.isdigit():
        return int(expr)

    def _repl_define(m):
        name = m.group(1)
        val = define_values.get(name)
        return str(val) if val is not None else m.group(0)
    resolved = re.sub(r'`(\w+)', _repl_define, expr)

    def _repl_ident(m):
        name = m.group(0)
        val = define_values.get(name)
        return str(val) if val is not None else name
    resolved = re.sub(r'\b[A-Za-z_]\w*\b', _repl_ident, resolved)
    try:
        if re.match(r'^[\d\s+\-*/()]+$', resolved):
            return int(eval(resolved))
    except Exception:
        pass
    return None


def _sv_resolve_width_expr(expr, define_values):
    if expr is None:
        return None
    return _sv_resolve_bound(expr, define_values or {})


def _sv_make_port_entry(name, hi=None, lo=None):
    """Build a port-info dict (scalar or bus, MSB-first bits)."""
    if hi is None or lo is None:
        return {'name': name, 'bits': [name], 'hi': None, 'lo': None}
    if hi >= lo:
        order = range(hi, lo - 1, -1)
    else:
        order = range(lo, hi - 1, -1)
    bits = [f'{name}[{i}]' for i in order]
    return {'name': name, 'bits': bits, 'hi': hi, 'lo': lo}


def _sv_parse_ports(port_text, define_values=None):
    """Extract ordered port info from module port declaration text."""
    port_text = re.sub(r'\s+', ' ', port_text).strip()
    if not port_text:
        return []
    items = []
    depth = 0
    buf = []
    for ch in port_text:
        if ch in ('(', '['):
            depth += 1
            buf.append(ch)
        elif ch in (')', ']'):
            depth -= 1
            buf.append(ch)
        elif ch == ',' and depth == 0:
            items.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        items.append(''.join(buf).strip())
    ports = []
    for item in items:
        item = item.strip()
        if not item:
            continue
        im = re.match(r'(\w+)\.(\w+)\s+(\w+)', item)
        if im and im.group(1) not in (
            'input', 'output', 'inout', 'logic', 'wire', 'reg', 'real'
        ):
            ports.append(_sv_make_port_entry(im.group(3)))
            continue
        item = re.sub(r'^(input|output|inout)\s+', '', item)
        item = re.sub(r'^(logic|reg|wire|real|integer)\s+', '', item)
        item = item.strip()
        hi = lo = None
        inner_hi = inner_lo = None
        bm = re.match(r'\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s*(.*)$', item)
        if bm:
            hi_expr = bm.group(1)
            lo_expr = bm.group(2)
            rest = bm.group(3).strip()
            hi = _sv_resolve_width_expr(hi_expr, define_values)
            lo = _sv_resolve_width_expr(lo_expr, define_values)
            # 2D port? `[hi:lo][inner_hi:inner_lo] name`
            bm2 = re.match(r'\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s*(.*)$', rest)
            if bm2:
                inner_hi = _sv_resolve_width_expr(bm2.group(1), define_values)
                inner_lo = _sv_resolve_width_expr(bm2.group(2), define_values)
                rest = bm2.group(3).strip()
            item = rest
        else:
            item = re.sub(r'\[[^\]]*\]\s*', '', item).strip()
        if item and re.match(r'^[A-Za-z_]\w*$', item):
            if (hi is not None and lo is not None
                    and inner_hi is not None and inner_lo is not None):
                # 2D port: expand to outer*inner individual bits
                outer = (range(hi, lo - 1, -1) if hi >= lo
                         else range(lo, hi - 1, -1))
                inner = (range(inner_hi, inner_lo - 1, -1) if inner_hi >= inner_lo
                         else range(inner_lo, inner_hi - 1, -1))
                bits = [f'{item}[{i}][{j}]' for i in outer for j in inner]
                ports.append({'name': item, 'bits': bits,
                              'hi': hi, 'lo': lo})
            elif hi is not None and lo is not None:
                ports.append(_sv_make_port_entry(item, hi, lo))
            else:
                ports.append(_sv_make_port_entry(item))
    return ports


def _sv_split_concat_pieces(inner):
    """Split text inside a {...} concatenation by top-level commas."""
    pieces = []
    depth = 0
    buf = []
    for ch in inner:
        if ch in ('{', '(', '['):
            depth += 1
            buf.append(ch)
        elif ch in ('}', ')', ']'):
            depth -= 1
            buf.append(ch)
        elif ch == ',' and depth == 0:
            pieces.append(''.join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        pieces.append(''.join(buf).strip())
    return pieces


def _sv_expand_piece(piece, define_values, port_signals=None, wires_2d=None):
    """Expand a single concatenation piece into a list of per-bit net names."""
    p = piece.strip()
    if not p:
        return None
    if p.startswith('{') and p.endswith('}'):
        return _sv_expand_concat_str(p[1:-1], define_values, port_signals, wires_2d)
    rm = re.match(r'^([^\s{}]+)\s*\{(.*)\}$', p)
    if rm:
        n_expr = rm.group(1)
        inner = rm.group(2)
        n = _sv_resolve_bound(n_expr, define_values or {})
        if n is not None:
            sub = _sv_expand_concat_str(inner, define_values, port_signals, wires_2d)
            if sub is not None:
                return sub * n
        return None
    # Width-cast WIDTH'(EXPR) — strip cast, expand inner. WIDTH may be digits,
    # an identifier, or a `MACRO. Requires `(` right after the apostrophe so
    # this doesn't intercept literal forms like 8'hFF / 4'b1010.
    cm = re.match(r"^[`]?[A-Za-z_0-9]+\s*'\s*\((.+)\)\s*$", p, re.DOTALL)
    if cm:
        return _sv_expand_piece(cm.group(1).strip(),
                                define_values, port_signals, wires_2d)
    lm = re.match(r"^(\d+)'([bBoOdDhH])([0-9a-fA-FxXzZ_?]+)$", p)
    if lm:
        width = int(lm.group(1))
        base = lm.group(2).lower()
        digits = lm.group(3).replace('_', '')
        try:
            if base == 'b':
                bits = digits.zfill(width)[-width:]
            elif base == 'o':
                val = int(digits, 8)
                bits = bin(val)[2:].zfill(width)[-width:]
            elif base == 'd':
                val = int(digits, 10)
                bits = bin(val)[2:].zfill(width)[-width:]
            elif base == 'h':
                val = int(digits, 16)
                bits = bin(val)[2:].zfill(width)[-width:]
            else:
                return None
            return [f"1'b{c}" for c in bits]
        except Exception:
            return None
    if p in ('0', '1'):
        return [f"1'b{p}"]
    dm = re.match(
        r'^([A-Za-z_]\w*)\s*\[\s*([^\]]+?)\s*\]\s*'
        r'\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s*$', p)
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
            return [f'{name}[{idx_str}][{i}]' for i in range(hi, lo - 1, -1)]
        else:
            return [f'{name}[{idx_str}][{i}]' for i in range(lo, hi - 1, -1)]
    dm2 = re.match(
        r'^([A-Za-z_]\w*)\s*\[\s*([^\]]+?)\s*\]\s*'
        r'\[\s*([^\]]+?)\s*\]\s*$', p)
    if dm2:
        name = dm2.group(1)
        idx_expr = dm2.group(2).strip()
        bit_expr = dm2.group(3).strip()
        idx = _sv_resolve_bound(idx_expr, define_values or {})
        bit = _sv_resolve_bound(bit_expr, define_values or {})
        idx_str = str(idx) if idx is not None else idx_expr
        bit_str = str(bit) if bit is not None else bit_expr
        return [f'{name}[{idx_str}][{bit_str}]']
    bm = re.match(r'^([A-Za-z_]\w*)\s*\[\s*([^:\]]+?)\s*:\s*([^\]]+?)\s*\]\s*$', p)
    if bm:
        name = bm.group(1)
        hi = _sv_resolve_bound(bm.group(2), define_values or {})
        lo = _sv_resolve_bound(bm.group(3), define_values or {})
        if hi is None or lo is None:
            return None
        if hi >= lo:
            return [f'{name}[{i}]' for i in range(hi, lo - 1, -1)]
        else:
            return [f'{name}[{i}]' for i in range(lo, hi - 1, -1)]
    sm = re.match(r'^([A-Za-z_]\w*)\s*\[\s*([^\]]+?)\s*\]\s*$', p)
    if sm:
        name = sm.group(1)
        idx_expr = sm.group(2).strip()
        idx = _sv_resolve_bound(idx_expr, define_values or {})
        inner_w = (wires_2d or {}).get(name)
        idx_str = str(idx) if idx is not None else idx_expr
        if inner_w is not None and inner_w > 0:
            return [f'{name}[{idx_str}][{i}]' for i in range(inner_w - 1, -1, -1)]
        if idx is None:
            return [f'{name}[{idx_expr}]']
        return [f'{name}[{idx}]']
    if re.match(r'^[A-Za-z_]\w*$', p):
        return [p]
    return None


def _sv_expand_concat_str(inner, define_values, port_signals=None, wires_2d=None):
    pieces = _sv_split_concat_pieces(inner)
    out = []
    for piece in pieces:
        bits = _sv_expand_piece(piece, define_values, port_signals, wires_2d)
        if bits is None:
            return None
        out.extend(bits)
    return out


def _sv_expand_pin_net(net_str, width, define_values, wires_2d=None):
    """Expand an instance pin's net expression to a list of `width` bit-nets."""
    if width <= 0:
        return []
    s = net_str.strip()
    if not s:
        return [''] * width
    if s.startswith('{') and s.endswith('}'):
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
        if width > 1 and len(bits) == 1 and re.match(r'^[A-Za-z_]\w*$', s):
            name = s
            # 2D wire used whole: emit [outer][inner] bits to match port-side
            # expansion (otherwise port pins use [i][j] but connection uses
            # [k], breaking pin↔net mapping).
            inner_w = (wires_2d or {}).get(name)
            if inner_w and width % inner_w == 0:
                outer_w = width // inner_w
                return [f'{name}[{i}][{j}]'
                        for i in range(outer_w - 1, -1, -1)
                        for j in range(inner_w - 1, -1, -1)]
            return [f'{name}[{i}]' for i in range(width - 1, -1, -1)]
        return None
    return None


def _sv_find_begin_end(text, begin_pos):
    """Find matching 'end' for a 'begin' at begin_pos. Returns index past 'end'."""
    depth = 1
    i = begin_pos
    n = len(text)
    while i < n and depth > 0:
        m = _RE_BEGIN_END.search(text, i)
        if not m:
            break
        if m.group(1) == 'begin':
            depth += 1
        else:
            depth -= 1
        i = m.end()
    return i


def _sv_parse_step(incr_expr, define_values=None):
    incr = incr_expr.strip()
    if '++' in incr:
        return 1
    m = re.match(r'\w+\s*\+=\s*(.+)', incr)
    if m:
        return _sv_resolve_bound(m.group(1), define_values or {})
    m = re.match(r'\w+\s*=\s*\w+\s*\+\s*(.+)', incr)
    if m:
        return _sv_resolve_bound(m.group(1), define_values or {})
    return None


def _sv_parse_param_overrides(param_block_text):
    overrides = {}
    for pm in _RE_PIN.finditer(param_block_text):
        pname = pm.group(1)
        net_start = pm.end()
        net_close = _sv_match_paren(param_block_text, net_start)
        if net_close < 0:
            continue
        overrides[pname] = re.sub(
            r'\s+', ' ', param_block_text[net_start:net_close].strip())
    return overrides


def _sv_extract_instances_flat(body, prefix=''):
    """Extract instances from body text. Prefix is prepended to instance names."""
    overrides_at = {}
    pieces = []
    last = 0
    for pm in _RE_PARAM_BLOCK.finditer(body):
        pieces.append(body[last:pm.start()])
        inner = body[pm.start() + 2 : pm.end() - 1]
        overrides_at[pm.end()] = _sv_parse_param_overrides(inner)
        pieces.append(' ' * (pm.end() - pm.start()))
        last = pm.end()
    pieces.append(body[last:])
    body = ''.join(pieces)
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
            nets = [n.strip() for n in inner.split(',') if n.strip()]
            pmap = {f'_p{i}': n for i, n in enumerate(nets)}
            instances.append((inst, cell, pmap, overrides))
            continue
        if '.' not in inner:
            continue
        pmap = {}
        for pm2 in _RE_PIN.finditer(inner):
            pin = pm2.group(1)
            net_start = pm2.end()
            net_close = _sv_match_paren(inner, net_start)
            if net_close < 0:
                continue
            pmap[pin] = re.sub(r'\s+', ' ', inner[net_start:net_close].strip())
        if pmap:
            instances.append((inst, cell, pmap, overrides))
    return instances


def _sv_extract_wires_2d(body, define_values=None):
    """Scan a module body for 2D packed array declarations.
    Returns {wire_name: inner_width}."""
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


def _sv_extract_wire_widths_1d(body, define_values=None):
    """Return {wire_name: width} for plain 1D bus declarations.
    Handles multi-name declarations like `wire [1:0] a, b, c;` and
    expression bounds like `[`C6__NUM_WCK_CH-1:0]` (resolved via
    `_sv_resolve_bound`)."""
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
        for name in re.split(r'\s*,\s*', m.group(3).strip()):
            if name and name not in out:
                out[name] = width
    return out


def _sv_expand_assign_side(s, define_values, wire_widths_1d, wires_2d):
    """Expand one side of an `assign LHS = RHS;` into MSB-first bit names."""
    s = s.strip()
    if not s:
        return None
    if s.startswith('{') and s.endswith('}'):
        return _sv_expand_concat_str(s[1:-1], define_values, None, wires_2d)
    if re.match(r'^[\.A-Za-z_]\w*$', s):
        w = (wire_widths_1d or {}).get(s)
        if w is not None and w > 1:
            return [f'{s}[{i}]' for i in range(w - 1, -1, -1)]
        return [s]
    return _sv_expand_piece(s, define_values, None, wires_2d)


def _sv_extract_alias_pairs(body, define_values, wire_widths_1d, wires_2d):
    """Extract per-bit alias pairs from `assign LHS = RHS;` statements."""
    pairs = []
    for m in _RE_ASSIGN.finditer(body):
        lhs = m.group(1).strip()
        rhs = m.group(2).strip()
        rhs_outside_braces = re.sub(r'\{[^{}]*\}', '', rhs)
        if re.search(r'[?&|^!~+\-*/<>]', rhs_outside_braces):
            continue
        lhs_bits = _sv_expand_assign_side(lhs, define_values, wire_widths_1d, wires_2d)
        rhs_bits = _sv_expand_assign_side(rhs, define_values, wire_widths_1d, wires_2d)
        if lhs_bits is None or rhs_bits is None:
            continue
        if len(lhs_bits) != len(rhs_bits):
            continue
        for l, r in zip(lhs_bits, rhs_bits):
            if l and r and l != r:
                pairs.append((l, r))
    return pairs


def _sv_extract_instances(body, define_values=None, prefix=''):
    """Extract instances, expanding generate-for blocks recursively."""
    instances = []
    last = 0
    if define_values is None:
        define_values = dict(_DEFAULT_DEFINE_VALUES)
    else:
        define_values = dict(define_values)
    for lm in _RE_LOCALPARAM.finditer(body):
        name = lm.group(1)
        val = _sv_resolve_bound(lm.group(2), define_values)
        if val is not None:
            define_values[name] = val
    sizes = {}
    for bm in _RE_BUS_DECL.finditer(body):
        high, low, sig = int(bm.group(1)), int(bm.group(2)), bm.group(3)
        sizes[sig] = abs(high - low) + 1
    if sizes:
        def _repl_size(m):
            sig = m.group(1)
            return str(sizes[sig]) if sig in sizes else m.group(0)
        body = _RE_DOLLAR_SIZE.sub(_repl_size, body)
    for m in _RE_GENFOR.finditer(body):
        if m.start() < last:
            continue
        instances.extend(_sv_extract_instances_flat(body[last:m.start()], prefix))
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
        if cmp_op == '<=':
            stop += 1
        begin_end = m.end()
        block_end = _sv_find_begin_end(body, begin_end)
        end_kw = body.rfind('end', begin_end, block_end)
        block_body = body[begin_end:end_kw]
        for i in range(start, stop, step):
            expanded = re.sub(r'\b' + var + r'\b', str(i), block_body)
            iter_prefix = f'{prefix}{label}[{i}].'
            instances.extend(_sv_extract_instances(expanded, define_values, iter_prefix))
        last = block_end
    instances.extend(_sv_extract_instances_flat(body[last:], prefix))
    return instances


def _sv_parse_file(args):
    """Parse one file → list of module dicts (designed for Pool.map)."""
    filepath, tvars, defines, define_values = args
    try:
        with open(filepath, 'r', errors='replace') as fh:
            raw = fh.read()
    except OSError:
        return []
    if tvars:
        raw = _sv_substitute_vars(raw, tvars)
    raw = _sv_strip_comments(raw)
    raw = _sv_preprocess(raw, defines)
    modules = []
    pos = 0
    while True:
        mm = _RE_MODULE.search(raw, pos)
        if not mm:
            break
        mod_name = mm.group(1)
        paren_open = raw.find('(', mm.end())
        semi = raw.find(';', mm.end())
        if paren_open < 0 or (0 <= semi < paren_open):
            pos = max(semi + 1, mm.end())
            continue
        param_text = ''
        between = raw[mm.end():paren_open].strip()
        if between.startswith('#'):
            param_close = _sv_match_paren(raw, paren_open + 1)
            if param_close < 0:
                pos = mm.end()
                continue
            param_text = raw[paren_open + 1 : param_close]
            paren_open = raw.find('(', param_close + 1)
            if paren_open < 0:
                pos = mm.end()
                continue
        port_close = _sv_match_paren(raw, paren_open + 1)
        if port_close < 0:
            pos = mm.end()
            continue
        ports = _sv_parse_ports(raw[paren_open + 1 : port_close], define_values)
        insts = []
        em = _RE_ENDMOD.search(raw, port_close)
        body_end = em.start() if em else len(raw)
        end_pos = (em.end() if em else len(raw))
        body = raw[port_close + 1 : body_end]
        if param_text:
            body = param_text + '\n' + body
        for iname, ctype, pmap, ovr in _sv_extract_instances(body, define_values):
            insts.append({'n': iname, 'c': ctype, 'p': pmap, 'o': ovr})
        param_names = []
        if param_text:
            for pm in re.finditer(
                r'\bparameter\s+(?:\w+\s+)?(\w+)\s*=', param_text):
                param_names.append(pm.group(1))
        wires_2d = _sv_extract_wires_2d(body, define_values)
        port_2d = _sv_extract_wires_2d(
            raw[paren_open + 1 : port_close], define_values)
        wires_2d.update(port_2d)
        wire_widths_1d = _sv_extract_wire_widths_1d(body, define_values)
        port_widths_1d = _sv_extract_wire_widths_1d(
            raw[paren_open + 1 : port_close], define_values)
        wire_widths_1d.update(port_widths_1d)

        # Non-ANSI port-style fix: when the port list is just bare names
        # (e.g. Verilog-A: `module foo (a, calout, b);` with widths declared
        # separately in the body as `output [8:0] calout;`), expand any
        # bare-name port whose width is now known from the body decls.
        # Without this, a 9-bit `calout` would collapse to 1 pin and
        # downstream positional connections would shift by 8.
        for idx, p in enumerate(ports):
            if isinstance(p, dict) and p.get('hi') is None and p.get('lo') is None:
                name = p['name']
                w = wire_widths_1d.get(name) or wires_2d.get(name)
                if w and w > 1:
                    ports[idx] = _sv_make_port_entry(name, w - 1, 0)

        aliases = _sv_extract_alias_pairs(
            body, define_values, wire_widths_1d, wires_2d)
        modules.append({
            'name': mod_name,
            'ports': ports,
            'insts': insts,
            'body': body if param_names else '',
            'param_names': param_names,
            'wires_2d': wires_2d,
            'aliases': aliases,
        })
        pos = end_pos
    return modules


def _sv_eval_bracket_arith(text):
    """Inside every [...] subscript, evaluate purely-numeric arithmetic."""
    def _repl(m):
        expr = m.group(1).strip()
        if ':' in expr:
            return m.group(0)
        if not _RE_SAFE_ARITH.match(expr):
            return m.group(0)
        try:
            return f'[{int(eval(expr))}]'
        except Exception:
            return m.group(0)
    prev = None
    for _ in range(3):
        new = _RE_BRACKET_EXPR.sub(_repl, text)
        if new == prev or new == text:
            text = new
            break
        prev = text
        text = new
    return text


def _sv_mangle_value(val):
    s = str(val).strip()
    m = re.match(r"^\d+'[bBoOdDhH](\w+)$", s)
    if m:
        s = m.group(1)
    return re.sub(r'[^A-Za-z0-9_]', '_', s)


def _sv_mangle_name(cell, overrides):
    parts = [cell]
    for k in sorted(overrides):
        parts.append(f'{k}_{_sv_mangle_value(overrides[k])}')
    return '__'.join(parts)


def _sv_specialize_modules(all_modules, define_values, max_combos=64):
    """Generate parameter-specialized copies of parameterized modules."""
    by_name = {m['name']: m for m in all_modules}
    combos = defaultdict(set)
    for mod in all_modules:
        for inst in mod['insts']:
            if not inst.get('o'):
                continue
            ctype = inst['c']
            target = by_name.get(ctype)
            if target is None or not target.get('body'):
                continue
            valid_params = set(target.get('param_names') or [])
            kept = {k: v for k, v in inst['o'].items() if k in valid_params}
            if not kept:
                continue
            combos[ctype].add(frozenset(kept.items()))
    new_modules = []
    spec_lookup = {}
    for ctype, combo_set in combos.items():
        if len(combo_set) > max_combos:
            print(f'Warning: {ctype} has {len(combo_set)} parameter combos '
                  f'(>{max_combos}); skipping specialization',
                  file=sys.stderr)
            continue
        target = by_name[ctype]
        base_body = target['body']
        for combo in combo_set:
            ovr = dict(combo)
            mangled = _sv_mangle_name(ctype, ovr)
            spec_lookup[(ctype, combo)] = mangled
            if mangled in by_name:
                continue
            sub_body = base_body
            for pname, pval in ovr.items():
                sval = str(pval).strip()
                sub_body = re.sub(
                    r'\b' + re.escape(pname) + r'\b', sval, sub_body)
            sub_body = _sv_eval_bracket_arith(sub_body)
            new_insts = []
            for iname, ictype, pmap, sub_ovr in _sv_extract_instances(
                    sub_body, define_values):
                new_insts.append({
                    'n': iname, 'c': ictype, 'p': pmap, 'o': sub_ovr,
                })
            spec_wires_2d = _sv_extract_wires_2d(sub_body, define_values)
            new_modules.append({
                'name': mangled,
                'ports': list(target['ports']),
                'insts': new_insts,
                'body': '',
                'param_names': [],
                'wires_2d': spec_wires_2d,
                'aliases': list(target.get('aliases') or []),
            })
    for mod in all_modules:
        for inst in mod['insts']:
            if not inst.get('o'):
                continue
            ctype = inst['c']
            target = by_name.get(ctype)
            if target is None or not target.get('body'):
                continue
            valid_params = set(target.get('param_names') or [])
            kept = {k: v for k, v in inst['o'].items() if k in valid_params}
            if not kept:
                continue
            key = (ctype, frozenset(kept.items()))
            mangled = spec_lookup.get(key)
            if mangled:
                inst['c'] = mangled
                inst['o'] = {}
    all_modules.extend(new_modules)
    return len(new_modules)


def _sv_flatten_ports(ports):
    """Flatten list of port dicts to a flat list of bit-level pin names."""
    out = []
    for p in ports:
        if isinstance(p, dict):
            out.extend(p['bits'])
        else:
            out.append(p)
    return out


def _sv_assemble(all_modules, top=None, define_values=None):
    """Build flat subckt + per-instance lists from parsed modules."""
    lookup = {m['name']: m for m in all_modules}
    define_values = define_values or {}
    if top and top in lookup:
        keep = set()
        queue = [top]
        while queue:
            name = queue.pop()
            if name in keep:
                continue
            keep.add(name)
            mod = lookup.get(name)
            if mod:
                for inst in mod['insts']:
                    queue.append(inst['c'])
        lookup = {k: v for k, v in lookup.items() if k in keep}
    subckts = {name: _sv_flatten_ports(m['ports']) for name, m in lookup.items()}
    instances = []
    for mod_name, mod in lookup.items():
        parent_wires_2d = mod.get('wires_2d') or {}
        for inst in mod['insts']:
            ctype = inst['c']
            pmap  = inst['p']
            if ctype in lookup:
                cell_ports = lookup[ctype]['ports']
                nets = []
                for port in cell_ports:
                    if isinstance(port, dict):
                        pname = port['name']
                        bits = port['bits']
                        net_str = pmap.get(pname, '')
                        if len(bits) == 1:
                            nets.append(net_str)
                        else:
                            expanded = _sv_expand_pin_net(
                                net_str, len(bits), define_values,
                                parent_wires_2d)
                            if expanded is not None:
                                nets.extend(expanded)
                            else:
                                if net_str:
                                    for bit_name in bits:
                                        bm = re.match(
                                            r'^[A-Za-z_]\w*\[(\d+)\]$',
                                            bit_name)
                                        if bm:
                                            nets.append(
                                                f'{net_str}[{bm.group(1)}]')
                                        else:
                                            nets.append(net_str)
                                else:
                                    nets.extend([''] * len(bits))
                    else:
                        nets.append(pmap.get(port, ''))
            else:
                nets = list(pmap.values())
            instances.append({
                'name': inst['n'],
                'cell_type': ctype,
                'nets': nets,
                'parent_cell': mod_name,
            })
    return subckts, instances


@dataclass
class Instance:
    """Represents an instance within a subckt/module"""
    name: str
    cell_type: str
    nets: List[str]
    parent_cell: str
    params: Dict[str, str] = None  # param=value pairs from SPICE instance lines

class NetlistParser:
    """Parses CDL, SPICE, and Verilog netlists"""

    def __init__(self, filename: str, tvars=None, defines=None,
                 define_values=None, top=None, workers=0):
        """Parse a netlist source.

        filename:
            - .json file → load pre-parsed cache (fast path)
            - directory → multi-file Verilog/SV with full SV elaboration
              (generate-loop expansion, parameter specialization, 2D
              packed arrays, multi-bit pin/concat expansion, per-bit
              `assign` alias decomposition, define-value resolution).
            - single SPICE/Spectre/CDL/Verilog file → format auto-detected
        tvars: dict of template variable substitutions (key→value) used
            for $key$ macros in PSV/SV files. Default empty.
        defines: set of preprocessor `define names treated as defined.
            Default `_DEFAULT_DEFINES`. None = use defaults; set() = empty.
        define_values: dict {NAME: int} for `define values used to
            resolve genfor bounds, bus widths, etc. If None and the
            input is a directory, the parser auto-discovers headers
            (`c6_features.vh`, `*.svh`) under the directory.
        top: optional top-cell name. When set, only the hierarchy
            reachable from `top` is kept in the assembled output.
        workers: parallel worker count for multi-file SV parsing
            (0 = auto, capped at 16).
        """
        self.filename = filename
        self.source_path = filename
        self.tvars = dict(tvars) if tvars else {}
        self.defines = set(defines) if defines is not None else set(_DEFAULT_DEFINES)
        self.define_values = dict(define_values) if define_values else None
        self.top = top
        self.workers = workers
        self.subckts: Dict[str, SubcktDef] = {}
        self.instances_by_parent: Dict[str, List[Instance]] = defaultdict(list)
        self.instances_by_celltype: Dict[str, List[Instance]] = defaultdict(list)
        self.instances_by_name: Dict[str, List[Instance]] = defaultdict(list)

        # JSON cache: load pre-parsed data directly, skip all parsing
        if os.path.isfile(filename) and filename.endswith('.json'):
            self._load_json(filename)
            return

        # Directory path: full SV elaboration via the helpers above
        if os.path.isdir(filename):
            self.files = []
            for ext in ('psv', 'sv', 'v'):
                self.files.extend(glob.glob(
                    os.path.join(filename, '**', f'*.{ext}'), recursive=True))
                self.files.extend(glob.glob(os.path.join(filename, f'*.{ext}')))
            self.files = sorted(set(self.files))
            if not self.files:
                raise ValueError(f"No .sv/.v/.psv files found in directory: {filename}")
            print(f"INFO: Parsing {len(self.files)} Verilog/SV files from: {filename}")
            self.format = 'verilog'
            self.source_path = os.path.abspath(filename)
        else:
            self.files = [filename]
            print(f"INFO: Parsing netlist: {os.path.abspath(filename)}")
            self.format = self._detect_format()
        self._parse()

    def _detect_format(self) -> str:
        """Detect netlist format from file content syntax.

        Distinguishing markers:
        - Verilog:  'module <name>' keyword
        - Spectre:  'subckt <name>' (no dot) or 'simulator lang=spectre'
        - CDL:      '*.PININFO' comment lines (auCdl-specific)
        - SPICE:    '.subckt/.ends' without CDL markers
        """
        has_dotsubckt = False
        has_pininfo = False

        for filepath in self.files:
            with open(filepath, 'r') as f:
                for line in f:
                    stripped = line.strip()
                    if not stripped:
                        continue

                    # Verilog: 'module <name>'
                    if re.match(r'^module\s+\w+', stripped):
                        return 'verilog'

                    # Spectre: 'simulator lang=spectre' or bare 'subckt' (no dot)
                    if stripped.startswith('simulator lang=spectre'):
                        return 'spectre'
                    if re.match(r'^subckt\s', stripped):
                        return 'spectre'

                    # CDL marker: *.PININFO is auCdl-specific, never in HSPICE
                    if stripped.startswith('*.PININFO'):
                        has_pininfo = True

                    # SPICE-family: .SUBCKT present
                    if re.match(r'^\.subckt\s', stripped, re.IGNORECASE):
                        has_dotsubckt = True

                    # Early exit once we have enough info
                    if has_dotsubckt and has_pininfo:
                        return 'cdl'

        if has_dotsubckt:
            return 'cdl' if has_pininfo else 'spice'

        return 'spice'

    def _parse(self):
        """Parse the netlist file"""
        if self.format == 'verilog':
            self._parse_verilog()
        elif self.format == 'spectre':
            self._parse_spectre()
        else:
            self._parse_spice()

    def _add_instance(self, instance: Instance):
        """Register an instance in all lookup indices"""
        self.instances_by_parent[instance.parent_cell].append(instance)
        self.instances_by_celltype[instance.cell_type].append(instance)
        self.instances_by_name[instance.name].append(instance)

    def _load_json(self, filepath: str):
        """Load pre-parsed netlist data from JSON cache."""
        with open(filepath, 'r') as f:
            data = json.load(f)
        self.format = data.get('format', 'verilog')
        self.source_path = data.get('source', filepath)
        print(f"Loading pre-parsed cache: {filepath}")
        print(f"Source: {self.source_path}")

        # Subckts may be stored as either a list of pins, or a dict with
        # 'pins' / 'aliases' keys (older schema kept for compatibility).
        for name, entry in data['subckts'].items():
            if isinstance(entry, dict):
                pins = entry.get('pins', [])
                aliases = entry.get('aliases') or {}
                sub = SubcktDef(name=name, pins=pins)
                if aliases:
                    sub.aliases = dict(aliases)
                self.subckts[name] = sub
            else:
                self.subckts[name] = SubcktDef(name=name, pins=entry)

        # Top-level 'aliases' (preparser-generated): {cell: [[lhs, rhs], ...]}.
        # Apply via union-find so port names become canonical roots.
        for cell, pairs in (data.get('aliases') or {}).items():
            sub = self.subckts.get(cell)
            if sub is not None and pairs:
                merge_aliases_into_subckt(sub, pairs)

        for inst_data in data['instances']:
            self._add_instance(Instance(
                name=inst_data['name'],
                cell_type=inst_data['cell_type'],
                nets=inst_data['nets'],
                parent_cell=inst_data['parent_cell']
            ))

    def validate_connections(self, verbose=False):
        """Shape-check: for every instance, verify that its connection
        count matches its cell's pin count. Returns the list of mismatch
        records as (parent_cell, inst_name, cell_type, n_conn, n_pin)
        tuples. When `verbose`, prints a WARNING per mismatch to stderr.

        This is a CHEAP shape check — it doesn't validate which nets are
        connected, only that the counts line up. It catches:
          - Malformed instance lines in the netlist
          - Parser misreads of cell definitions (e.g. non-ANSI port
            widths declared in the body that the parser missed)
          - Wrong subckt definition resolved for a cell type
        It does NOT catch: wrong nets at right pin counts, MSB/LSB
        ordering errors, type/direction mismatches.

        Should be called AFTER all subckt definitions are loaded — for
        callers that side-load defs from .va or library Verilog files
        after the initial parse, run this last.
        """
        mismatches = []
        for celltype, insts in self.instances_by_celltype.items():
            sub = self.subckts.get(celltype)
            if sub is None:
                continue
            n_pin = len(sub.pins)
            for inst in insts:
                n_conn = len(inst.nets)
                if n_conn != n_pin:
                    mismatches.append(
                        (inst.parent_cell, inst.name, celltype, n_conn, n_pin))
        if verbose:
            for parent, name, ctype, nc, np_ in mismatches:
                print(f"WARNING: {parent}/{name} (cell={ctype}): "
                      f"{nc} connections but cell has {np_} pins",
                      file=sys.stderr)
        return mismatches

    def dump_json(self, out_path):
        """Write the parsed model to a JSON cache file.

        Schema mirrors the historical preparser output so existing cache
        consumers (the tracer's own _load_json, downstream tools) work
        unchanged:
            {
              "format": "verilog",
              "source": "<absolute path>",
              "subckts": {cell: [pin1, pin2, ...]},
              "instances": [{name, cell_type, nets, parent_cell}, ...],
              "aliases":  {cell: [[lhs_bit, rhs_bit], ...]}
            }
        """
        # Subckts: flat pin lists (matches existing schema)
        subckts_out = {name: list(sub.pins) for name, sub in self.subckts.items()}
        # Instances: flat list across all parents
        instances_out = []
        for parent_cell, insts in self.instances_by_parent.items():
            for inst in insts:
                instances_out.append({
                    'name': inst.name,
                    'cell_type': inst.cell_type,
                    'nets': list(inst.nets),
                    'parent_cell': inst.parent_cell,
                })
        # Aliases: invert the canonical map to per-bit pairs (lhs, rhs)
        aliases_out = {}
        for name, sub in self.subckts.items():
            if not sub.aliases:
                continue
            pairs = sorted([list(p) for p in sub.aliases.items()])
            if pairs:
                aliases_out[name] = pairs
        output = {
            'format': self.format,
            'source': self.source_path,
            'subckts': subckts_out,
            'instances': instances_out,
            'aliases': aliases_out,
        }
        out_dir = os.path.dirname(os.path.abspath(out_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, 'w') as fh:
            json.dump(output, fh, indent=2)
        kb = os.path.getsize(out_path) / 1024
        print(f"Output: {out_path} ({kb:.0f} KB)")

    def _parse_verilog(self):
        """Full SV elaboration pipeline.

        Runs the module-level _sv_* helpers in stages:
          1. Auto-discover headers and resolve `define values (if not provided)
          2. Per-file parse via Pool.map
          3. Parameter specialization (creates __param_val variants)
          4. Assemble flat subckts + instances + per-bit aliases
          5. Populate self.subckts / instances_by_* / merge aliases
        """
        # 1. Auto-discover headers (`*.vh` / `*.svh` / `*.d`) and merge
        # both bare `define X and `define X <value> into self.defines /
        # self.define_values. This replaces hard-coded project-specific
        # constants — the source tree's headers are the ground truth.
        if os.path.isdir(self.filename):
            header_files = _sv_discover_headers(self.filename)
            if header_files:
                disc_defs, disc_vals = _sv_parse_defines(header_files, self.tvars)
                # Auto-discovered defines extend (don't overwrite) any
                # caller-supplied set, so explicit -defines / -undefines
                # still win on conflict.
                self.defines = self.defines | disc_defs
                if self.define_values is None:
                    self.define_values = {}
                # Caller-supplied values take precedence on conflict
                for k, v in disc_vals.items():
                    self.define_values.setdefault(k, v)
                print(f"Headers: {len(header_files)} scanned; "
                      f"{len(disc_defs)} defines, "
                      f"{len(disc_vals)} numeric values discovered")
        if self.define_values is None:
            self.define_values = {}

        # 2. Parse files (parallel for multi-file inputs)
        work = [(f, self.tvars, self.defines, self.define_values)
                for f in self.files]
        nw = self.workers or min(cpu_count(), len(self.files), 16)
        if nw > 1 and len(self.files) > 4:
            with Pool(nw) as pool:
                results = pool.map(_sv_parse_file, work)
        else:
            results = [_sv_parse_file(w) for w in work]
        all_mods = [m for batch in results for m in batch]

        # 3. Parameter specialization
        n_spec = _sv_specialize_modules(all_mods, self.define_values)
        if n_spec:
            print(f"Specialized: {n_spec} new subckt variants")

        # 4. Assemble: flat subckts dict + per-instance net lists
        subckts, instances = _sv_assemble(all_mods, top=self.top,
                                          define_values=self.define_values)

        # 5. Build SubcktDef / Instance objects, merge aliases via union-find
        for name, pins in subckts.items():
            self.subckts[name] = SubcktDef(name=name, pins=pins)
        for mod in all_mods:
            if mod['name'] not in subckts:
                continue
            pairs = mod.get('aliases') or []
            if pairs:
                merge_aliases_into_subckt(self.subckts[mod['name']], pairs)
        for inst_data in instances:
            self._add_instance(Instance(
                name=inst_data['name'],
                cell_type=inst_data['cell_type'],
                nets=inst_data['nets'],
                parent_cell=inst_data['parent_cell']))

    def _parse_spice(self):
        """Parse SPICE/CDL netlist"""
        with open(self.filename, 'r') as f:
            lines = f.readlines()

        current_subckt = None
        subckt_content = []
        i = 0

        while i < len(lines):
            line = lines[i].rstrip()

            subckt_match = re.match(r'^\.subckt\s+(\S+)\s*(.*)', line, re.IGNORECASE)
            if subckt_match:
                cell_name = subckt_match.group(1)
                pin_text = subckt_match.group(2)

                # Handle continuation lines
                while i + 1 < len(lines) and lines[i + 1].startswith('+'):
                    i += 1
                    pin_text += ' ' + lines[i][1:].strip()

                pin_text = re.sub(r'\+', ' ', pin_text)
                pins = [p for p in pin_text.split()
                        if p and not p.startswith('*') and '=' not in p]

                current_subckt = cell_name
                subckt_content = []
                self.subckts[cell_name] = SubcktDef(name=cell_name, pins=pins)

            elif re.match(r'^\.ends', line, re.IGNORECASE):
                if current_subckt:
                    self._parse_spice_instances(current_subckt, subckt_content)
                current_subckt = None
                subckt_content = []

            elif current_subckt:
                subckt_content.append(line)

            i += 1

    def _parse_spice_instances(self, parent_cell: str, content: List[str]):
        """Parse instances within a subckt body"""
        i = 0
        while i < len(content):
            line = content[i]
            stripped = line.strip()

            if stripped.upper().startswith('X'):
                instance_text = stripped
                while i + 1 < len(content) and content[i + 1].lstrip().startswith('+'):
                    i += 1
                    instance_text += ' ' + content[i].strip().lstrip('+').strip()

                instance = self._parse_spice_instance(instance_text, parent_cell)
                if instance:
                    self._add_instance(instance)
            i += 1

    def _parse_spice_instance(self, text: str, parent_cell: str) -> Optional[Instance]:
        """Parse a single SPICE/CDL instance line"""
        text = re.sub(r'\+', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        tokens = text.split()
        if len(tokens) < 2:
            return None
        if '=' in tokens[0]:
            return None

        inst_name = tokens[0]

        # CDL format: Xinst net1 net2 ... / celltype
        # SPICE format: Xinst net1 net2 ... celltype [params]
        if '/' in tokens:
            slash_idx = tokens.index('/')
            nets = tokens[1:slash_idx]
            cell_type = tokens[slash_idx + 1] if slash_idx + 1 < len(tokens) else None
        else:
            nets = []
            cell_type = None
            for j, tok in enumerate(tokens[1:], 1):
                if '=' in tok:
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
            if '=' in tok and not tok.startswith('*'):
                k, v = tok.split('=', 1)
                params[k] = v.strip("'")

        return Instance(name=inst_name, cell_type=cell_type, nets=nets,
                        parent_cell=parent_cell, params=params or None)

    def _parse_spectre(self):
        """Parse Spectre netlist"""
        with open(self.filename, 'r') as f:
            raw_lines = f.readlines()

        # Join backslash-continuation lines and strip bracket escaping
        lines = []
        buf = ''
        for raw in raw_lines:
            raw = raw.rstrip()
            if buf:
                raw = raw.lstrip()
            if raw.endswith('\\'):
                buf += raw[:-1] + ' '
            else:
                buf += raw
                lines.append(buf)
                buf = ''
        if buf:
            lines.append(buf)

        # Strip \< and \> bracket escaping
        lines = [l.replace('\\<', '<').replace('\\>', '>') for l in lines]

        skip_prefixes = ('simulator', 'global', 'include', 'parameters', 'real',
                         'model', 'ends', 'ahdl_include', 'saveOptions', 'save')

        # First pass: collect subckt definitions and body lines
        subckt_bodies = {}  # cell_name -> list of body lines
        current_subckt = None
        top_level_lines = []
        # Derive synthetic top-level cell name from filename stem
        top_cell = os.path.splitext(os.path.basename(self.filename))[0]

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith('//'):
                continue

            subckt_match = re.match(r'^subckt\s+(\S+)\s*(.*)', stripped)
            if subckt_match:
                cell_name = subckt_match.group(1)
                pin_text = subckt_match.group(2)
                # Remove optional parentheses around pins
                pin_text = pin_text.strip('()')
                pins = [p for p in pin_text.split() if p]
                self.subckts[cell_name] = SubcktDef(name=cell_name, pins=pins)
                current_subckt = cell_name
                subckt_bodies[cell_name] = []
                continue

            if re.match(r'^ends\b', stripped):
                current_subckt = None
                continue

            if current_subckt:
                subckt_bodies[current_subckt].append(stripped)
            else:
                top_level_lines.append(stripped)

        # Register top-level cell if it has content (testbench)
        if top_level_lines:
            if top_cell not in self.subckts:
                self.subckts[top_cell] = SubcktDef(name=top_cell, pins=[])
            subckt_bodies[top_cell] = top_level_lines

        # Second pass: parse instances in each subckt body
        for cell_name, body_lines in subckt_bodies.items():
            for line in body_lines:
                stripped = line.strip()
                if any(stripped.startswith(p) for p in skip_prefixes):
                    continue
                instance = self._parse_spectre_instance(stripped, cell_name)
                if instance:
                    self._add_instance(instance)

    def _parse_spectre_instance(self, text: str, parent_cell: str) -> Optional[Instance]:
        """Parse a single Spectre instance line: name (nets) cell_type [params]"""
        m = re.match(r'^(\S+)\s*\(([^)]*)\)\s*(\S+)', text)
        if not m:
            return None
        inst_name = m.group(1)
        nets = m.group(2).split()
        cell_type = m.group(3)
        # Only register instances whose cell_type is a known subckt
        if cell_type not in self.subckts:
            return None
        return Instance(name=inst_name, cell_type=cell_type, nets=nets, parent_cell=parent_cell)


