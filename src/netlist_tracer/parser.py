from __future__ import annotations

import glob
import json
import os
from collections import defaultdict
from multiprocessing import cpu_count
from typing import Optional

from netlist_tracer._logging import get_logger
from netlist_tracer.exceptions import NetlistParseError
from netlist_tracer.model import Instance, SubcktDef, merge_aliases_into_subckt
from netlist_tracer.parsers.detect import detect_format
from netlist_tracer.parsers.edif import parse_edif
from netlist_tracer.parsers.spectre import parse_spectre
from netlist_tracer.parsers.spice import parse_spice
from netlist_tracer.parsers.verilog.instances import _sv_parse_file
from netlist_tracer.parsers.verilog.preprocess import _sv_discover_headers, _sv_parse_defines
from netlist_tracer.parsers.verilog.specialize import _sv_assemble, _sv_specialize_modules

_logger = get_logger(__name__)

_CACHE_SCHEMA_VERSION = 2


class NetlistParser:
    """Parses CDL, SPICE, Spectre, and Verilog/SystemVerilog netlists."""

    def __init__(
        self,
        filename: str,
        tvars: Optional[dict[str, str]] = None,
        defines: Optional[set[str]] = None,
        define_values: Optional[dict[str, int]] = None,
        top: Optional[str] = None,
        workers: int = 0,
        include_paths: Optional[list[str]] = None,
        format: Optional[str] = None,
    ) -> None:
        """Parse a netlist source.

        Args:
            filename: Path to netlist file, directory, or .json cache.
                - .json file: load pre-parsed cache (fast path)
                - directory: multi-file Verilog/SV with full elaboration
                - single file: format auto-detected from content
            tvars: Template variable substitutions for $key$ macros.
            defines: Set of preprocessor define names.
            define_values: Dict of {name: int} for define values.
            top: Optional top-cell name to limit hierarchy.
            workers: Parallel worker count (0 = auto).
            include_paths: Optional list of additional search directories for includes.
            format: Override auto-detection with explicit format string.
                Valid values: 'spice', 'cdl', 'spectre', 'verilog', 'edif', None (auto-detect).
        """
        # Validate format parameter
        valid_formats = {"spice", "cdl", "spectre", "verilog", "edif", None}
        if format is not None and format not in valid_formats:
            raise NetlistParseError(
                f"Invalid format '{format}': must be one of "
                f"{sorted(str(f) for f in valid_formats if f is not None)}"
            )

        self.filename = filename
        self.source_path = filename
        self.tvars = dict(tvars) if tvars else {}
        self.defines = set(defines) if defines is not None else set()
        self.define_values = dict(define_values) if define_values else None
        self.top = top
        self.workers = workers
        self.include_paths = include_paths
        self.subckts: dict[str, SubcktDef] = {}
        self.instances_by_parent: dict[str, list[Instance]] = defaultdict(list)
        self.instances_by_celltype: dict[str, list[Instance]] = defaultdict(list)
        self.instances_by_name: dict[str, list[Instance]] = defaultdict(list)
        self.format = "spice"
        self.files: list[str] = []
        self.global_nets: list[str] = []
        self._user_format = format

        # JSON cache: load pre-parsed data directly
        if os.path.isfile(filename) and filename.endswith(".json"):
            self._load_json(filename)
            return

        # Directory path: full SV elaboration
        if os.path.isdir(filename):
            self.files = []
            for ext in ("psv", "sv", "v", "va", "vams", "vha"):
                self.files.extend(
                    glob.glob(os.path.join(filename, "**", f"*.{ext}"), recursive=True)
                )
                self.files.extend(glob.glob(os.path.join(filename, f"*.{ext}")))
            self.files = sorted(set(self.files))
            if not self.files:
                raise NetlistParseError(f"No .sv/.v/.psv files found in directory: {filename}")
            _logger.info(f"Parsing {len(self.files)} Verilog/SV files from: {filename}")
            # Directory paths imply Verilog; format kwarg is ignored for directories
            self.format = "verilog"
            self.source_path = os.path.abspath(filename)
        else:
            self.files = [filename]
            _logger.info(f"Parsing netlist: {os.path.abspath(filename)}")
            # Use explicit format if provided; otherwise auto-detect
            if self._user_format:
                self.format = self._user_format
            else:
                self.format = self._detect_format()
        self._parse()

    def _detect_format(self) -> str:
        """Detect netlist format from file content."""
        return detect_format(self.files)

    def _parse(self) -> None:
        """Dispatch to format-specific parser."""
        if self.format == "verilog":
            self._parse_verilog()
        elif self.format == "edif":
            self._parse_edif()
        elif self.format == "spectre":
            self._parse_spectre()
        else:
            self._parse_spice()

    def _add_instance(self, instance: Instance) -> None:
        """Register an instance in all lookup indices."""
        self.instances_by_parent[instance.parent_cell].append(instance)
        self.instances_by_celltype[instance.cell_type].append(instance)
        self.instances_by_name[instance.name].append(instance)

    def _load_json(self, filepath: str) -> None:
        """Load pre-parsed netlist data from JSON cache.

        Supports v0 (legacy, no schema_version field), v1 (aliases as
        list of [lhs, rhs] pairs), and v2 (aliases as dict, compact
        encoding). Raises NetlistParseError if schema_version is newer
        than supported.
        """
        with open(filepath) as f:
            data = json.load(f)

        # Check schema version for forward compatibility
        schema_version = data.get("schema_version", 0)  # v0 if missing
        if schema_version > _CACHE_SCHEMA_VERSION:
            raise NetlistParseError(
                f"Cache schema version {schema_version} is newer than supported "
                f"version {_CACHE_SCHEMA_VERSION}; update netlist-tracer."
            )
        if schema_version == 0:
            _logger.info(f"Loading legacy v0 cache (no schema_version field): {filepath}")

        self.format = data.get("format", "verilog")
        self.source_path = data.get("source", filepath)
        _logger.info(f"Loading pre-parsed cache: {filepath}")
        _logger.info(f"Source: {self.source_path}")

        for name, entry in data["subckts"].items():
            if isinstance(entry, dict):
                pins = entry.get("pins", [])
                aliases = entry.get("aliases") or {}
                sub = SubcktDef(name=name, pins=pins)
                if aliases:
                    sub.aliases = dict(aliases)
                self.subckts[name] = sub
            else:
                self.subckts[name] = SubcktDef(name=name, pins=entry)

        for cell, pairs in (data.get("aliases") or {}).items():
            subckt: SubcktDef | None = self.subckts.get(cell)
            if subckt is not None and pairs:
                # v2 stores aliases as dict {lhs: rhs}; v0/v1 as list of [lhs, rhs] pairs.
                items = pairs.items() if isinstance(pairs, dict) else pairs
                merge_aliases_into_subckt(subckt, items)

        for inst_data in data["instances"]:
            self._add_instance(
                Instance(
                    name=inst_data["name"],
                    cell_type=inst_data["cell_type"],
                    nets=inst_data["nets"],
                    parent_cell=inst_data["parent_cell"],
                )
            )

    def _parse_spice(self) -> None:
        """Parse SPICE/CDL netlist."""
        if len(self.files) != 1:
            raise NetlistParseError("SPICE parser expects exactly one file")
        subckts, instances, global_nets = parse_spice(
            self.files[0], include_paths=self.include_paths
        )
        self.subckts = subckts
        self.global_nets = global_nets
        for inst in instances:
            self._add_instance(inst)

    def _parse_edif(self) -> None:
        """Parse EDIF netlist."""
        if len(self.files) != 1:
            raise NetlistParseError("EDIF parser expects exactly one file")
        subckts, instances = parse_edif(self.files[0])
        self.subckts = subckts
        for inst in instances:
            self._add_instance(inst)

    def _parse_spectre(self) -> None:
        """Parse Spectre netlist."""
        if len(self.files) != 1:
            raise NetlistParseError("Spectre parser expects exactly one file")
        subckts, instances = parse_spectre(self.files[0], include_paths=self.include_paths)
        self.subckts = subckts
        for inst in instances:
            self._add_instance(inst)

    def _parse_verilog(self) -> None:
        """Full SV elaboration pipeline."""
        if os.path.isdir(self.filename):
            header_files = _sv_discover_headers(self.filename)
            if header_files:
                disc_defs, disc_vals = _sv_parse_defines(header_files, self.tvars)
                self.defines = self.defines | disc_defs
                if self.define_values is None:
                    self.define_values = {}
                for k, v in disc_vals.items():
                    self.define_values.setdefault(k, v)
                _logger.info(
                    f"Headers: {len(header_files)} scanned; "
                    f"{len(disc_defs)} defines, "
                    f"{len(disc_vals)} numeric values discovered"
                )
        if self.define_values is None:
            self.define_values = {}

        work = [(f, self.tvars, self.defines, self.define_values) for f in self.files]
        nw = self.workers or min(cpu_count(), len(self.files), 16)
        if nw > 1 and len(self.files) > 4:
            from multiprocessing import Pool

            with Pool(nw) as pool:
                results = pool.map(_sv_parse_file, work)
        else:
            results = [_sv_parse_file(w) for w in work]
        all_mods = [m for batch in results for m in batch]

        if not all_mods:
            raise NetlistParseError("No modules parsed from Verilog files")

        n_spec = _sv_specialize_modules(all_mods, self.define_values)
        if n_spec:
            _logger.info(f"Specialized: {n_spec} new subckt variants")

        subckts, instances_dicts = _sv_assemble(
            all_mods, top=self.top, define_values=self.define_values
        )
        self.subckts = subckts
        # Convert instances from dicts to Instance objects
        for inst_dict in instances_dicts:
            inst = Instance(
                name=inst_dict["name"],
                cell_type=inst_dict["cell_type"],
                nets=inst_dict["nets"],
                parent_cell=inst_dict["parent_cell"],
            )
            self._add_instance(inst)

    def validate_connections(self, verbose: bool = False) -> list[tuple[str, str, str, int, int]]:
        """Validate instance pin counts match cell definitions.

        Args:
            verbose: Print warnings for mismatches to stderr.

        Returns:
            List of mismatch tuples (parent_cell, inst_name, cell_type,
            n_connections, n_pins).
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
                    mismatches.append((inst.parent_cell, inst.name, celltype, n_conn, n_pin))
        if verbose:
            for parent, name, ctype, nc, np_ in mismatches:
                _logger.warning(
                    f"WARNING: {parent}/{name} (cell={ctype}): {nc} connections but cell has {np_} pins"
                )
        return mismatches

    def dump_json(self, out_path: str) -> None:
        """Write parsed model to JSON cache file.

        Output is compact (no indentation) and machine-oriented. Use
        `python3 -m json.tool < cache.json` to inspect by eye.

        Schema version (v2) differences vs older caches the loader still
        understands (v0/v1):
          - Aliases stored as dict {lhs: rhs} (was list of [lhs, rhs] pairs)
          - Compact JSON output (no indentation)
          - No defensive list copies on pin/net references

        Args:
            out_path: Output file path.
        """
        subckts_out = {name: sub.pins for name, sub in self.subckts.items()}
        instances_out = [
            {
                "name": inst.name,
                "cell_type": inst.cell_type,
                "nets": inst.nets,
                "parent_cell": inst.parent_cell,
            }
            for insts in self.instances_by_parent.values()
            for inst in insts
        ]
        aliases_out = {name: dict(sub.aliases) for name, sub in self.subckts.items() if sub.aliases}
        output = {
            "schema_version": _CACHE_SCHEMA_VERSION,
            "format": self.format,
            "source": self.source_path,
            "subckts": subckts_out,
            "instances": instances_out,
            "aliases": aliases_out,
        }
        out_dir = os.path.dirname(os.path.abspath(out_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", buffering=65536) as fh:
            json.dump(output, fh, separators=(",", ":"))
        kb = os.path.getsize(out_path) / 1024
        _logger.info(f"Output: {out_path} ({kb:.0f} KB)")
