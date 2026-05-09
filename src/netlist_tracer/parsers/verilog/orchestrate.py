from __future__ import annotations

import os
from multiprocessing import Pool, cpu_count
from typing import Optional

from netlist_tracer.model import Instance, SubcktDef, merge_aliases_into_subckt
from netlist_tracer.parsers.verilog.instances import _sv_parse_file
from netlist_tracer.parsers.verilog.preprocess import _sv_discover_headers, _sv_parse_defines
from netlist_tracer.parsers.verilog.specialize import _sv_assemble, _sv_specialize_modules


def parse_verilog_directory(
    dirpath: str,
    tvars: Optional[dict[str, str]] = None,
    defines: Optional[set] = None,
    define_values: Optional[dict[str, int]] = None,
    top: Optional[str] = None,
    workers: int = 0,
) -> tuple[dict[str, SubcktDef], list[Instance], dict]:
    """Parse a Verilog/SystemVerilog directory with full elaboration.

    Args:
        dirpath: Directory containing .v/.sv files.
        tvars: Template variable substitutions ({key: value}).
        defines: Set of preprocessor define names (if None, empty set).
        define_values: Dict of {name: int} define values. If None, auto-discover
                       from headers under dirpath.
        top: Optional top-cell name to limit hierarchy.
        workers: Number of processes for parallel parsing (0 = cpu_count).

    Returns:
        Tuple of (subckts_dict, instances_list, aliases_by_cell) where:
        - subckts_dict: {name: SubcktDef}
        - instances_list: [Instance, ...]
        - aliases_by_cell: {cell_name: {net: canonical_net, ...}}
    """
    tvars = tvars or {}
    defines = defines or set()
    workers = workers or cpu_count()

    # Auto-discover define values if not provided
    if define_values is None:
        headers = _sv_discover_headers(dirpath)
        if headers:
            _, define_values = _sv_parse_defines(headers, tvars)
        else:
            define_values = {}

    # Collect .v and .sv files
    import glob

    files = []
    for ext in ("v", "sv", "verilog", "systemverilog"):
        files.extend(glob.glob(os.path.join(dirpath, f"*.{ext}")))
        files.extend(glob.glob(os.path.join(dirpath, "**", f"*.{ext}"), recursive=True))
    files = sorted(set(files))

    if not files:
        return {}, [], {}

    # Parallel parsing
    args_list = [(f, tvars, defines, define_values) for f in files]
    if workers > 1:
        with Pool(workers) as pool:
            all_modules_nested = pool.map(_sv_parse_file, args_list)
    else:
        all_modules_nested = [_sv_parse_file(args) for args in args_list]

    all_modules = []
    for mods in all_modules_nested:
        all_modules.extend(mods)

    if not all_modules:
        return {}, [], {}

    # Specialize parameterized modules
    _sv_specialize_modules(all_modules, define_values)

    # Assemble to flat model
    subckts_flat, instances_flat = _sv_assemble(all_modules, top, define_values)

    # Convert to SubcktDef objects with alias merging
    subckts: dict[str, SubcktDef] = {}
    for name, ports_flat in subckts_flat.items():
        subckts[name] = SubcktDef(name=name, pins=ports_flat)
    for mod in all_modules:
        mod_name = mod["name"]
        if mod_name in subckts:
            alias_pairs = mod.get("aliases") or []
            merge_aliases_into_subckt(subckts[mod_name], alias_pairs)
    aliases_by_cell: dict[str, dict] = {name: sub.aliases for name, sub in subckts.items()}

    # Convert instances to Instance objects
    instances: list[Instance] = []
    for inst_dict in instances_flat:
        inst = Instance(
            name=inst_dict["name"],
            cell_type=inst_dict["cell_type"],
            nets=inst_dict["nets"],
            parent_cell=inst_dict["parent_cell"],
        )
        instances.append(inst)

    return subckts, instances, aliases_by_cell
