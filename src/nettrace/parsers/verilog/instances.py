from __future__ import annotations

import re

from nettrace.parsers.verilog.preprocess import (
    _sv_preprocess,
    _sv_strip_comments,
    _sv_substitute_vars,
)
from nettrace.parsers.verilog.structure import (
    _sv_extract_alias_pairs,
    _sv_extract_instances,
    _sv_extract_wire_widths_1d,
    _sv_extract_wires_2d,
    _sv_make_port_entry,
    _sv_match_paren,
    _sv_parse_ports,
)

# Pre-compiled patterns
_RE_MODULE = re.compile(r"\bmodule\s+(\w+)")
_RE_ENDMOD = re.compile(r"\bendmodule\b")


def _sv_parse_file(args: tuple[str, dict, set, dict]) -> list:
    """Parse one file → list of module dicts (designed for Pool.map)."""
    filepath, tvars, defines, define_values = args
    try:
        with open(filepath, errors="replace") as fh:
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
        paren_open = raw.find("(", mm.end())
        semi = raw.find(";", mm.end())
        if paren_open < 0 or (0 <= semi < paren_open):
            pos = max(semi + 1, mm.end())
            continue
        param_text = ""
        between = raw[mm.end() : paren_open].strip()
        if between.startswith("#"):
            param_close = _sv_match_paren(raw, paren_open + 1)
            if param_close < 0:
                pos = mm.end()
                continue
            param_text = raw[paren_open + 1 : param_close]
            paren_open = raw.find("(", param_close + 1)
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
        end_pos = em.end() if em else len(raw)
        body = raw[port_close + 1 : body_end]
        if param_text:
            body = param_text + "\n" + body
        for iname, ctype, pmap, ovr in _sv_extract_instances(body, define_values):
            insts.append({"n": iname, "c": ctype, "p": pmap, "o": ovr})
        param_names = []
        if param_text:
            for pm in re.finditer(r"\bparameter\s+(?:\w+\s+)?(\w+)\s*=", param_text):
                param_names.append(pm.group(1))
        wires_2d = _sv_extract_wires_2d(body, define_values)
        port_2d = _sv_extract_wires_2d(raw[paren_open + 1 : port_close], define_values)
        wires_2d.update(port_2d)
        wire_widths_1d = _sv_extract_wire_widths_1d(body, define_values)
        port_widths_1d = _sv_extract_wire_widths_1d(raw[paren_open + 1 : port_close], define_values)
        wire_widths_1d.update(port_widths_1d)

        # Non-ANSI port-style fix: when the port list is just bare names,
        # expand any bare-name port whose width is now known from the body decls.
        for idx, p in enumerate(ports):
            if isinstance(p, dict) and p.get("hi") is None and p.get("lo") is None:
                name = p["name"]
                w = wire_widths_1d.get(name) or wires_2d.get(name)
                if w and w > 1:
                    ports[idx] = _sv_make_port_entry(name, w - 1, 0)

        aliases = _sv_extract_alias_pairs(body, define_values, wire_widths_1d, wires_2d)
        modules.append(
            {
                "name": mod_name,
                "ports": ports,
                "insts": insts,
                "body": body if param_names else "",
                "param_names": param_names,
                "wires_2d": wires_2d,
                "aliases": aliases,
            }
        )
        pos = end_pos
    return modules
