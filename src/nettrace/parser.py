from __future__ import annotations

import glob
import json
import os
from collections import defaultdict
from multiprocessing import cpu_count
from typing import Optional

from nettrace._logging import get_logger
from nettrace.exceptions import NetlistParseError
from nettrace.model import Instance, SubcktDef, merge_aliases_into_subckt
from nettrace.parsers.detect import detect_format
from nettrace.parsers.spectre import parse_spectre
from nettrace.parsers.spice import parse_spice
from nettrace.parsers.verilog.instances import _sv_parse_file
from nettrace.parsers.verilog.preprocess import _sv_discover_headers, _sv_parse_defines
from nettrace.parsers.verilog.specialize import _sv_assemble, _sv_specialize_modules

_logger = get_logger(__name__)


class NetlistParser:
    """Parses CDL, SPICE, Spectre, and Verilog/SystemVerilog netlists."""

    def __init__(
        self,
        filename: str,
        tvars: Optional[dict[str, str]] = None,
        defines: Optional[set] = None,
        define_values: Optional[dict[str, int]] = None,
        top: Optional[str] = None,
        workers: int = 0,
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
        """
        self.filename = filename
        self.source_path = filename
        self.tvars = dict(tvars) if tvars else {}
        self.defines = set(defines) if defines is not None else set()
        self.define_values = dict(define_values) if define_values else None
        self.top = top
        self.workers = workers
        self.subckts: dict[str, SubcktDef] = {}
        self.instances_by_parent: dict[str, list[Instance]] = defaultdict(list)
        self.instances_by_celltype: dict[str, list[Instance]] = defaultdict(list)
        self.instances_by_name: dict[str, list[Instance]] = defaultdict(list)
        self.format = "spice"
        self.files: list[str] = []

        # JSON cache: load pre-parsed data directly
        if os.path.isfile(filename) and filename.endswith(".json"):
            self._load_json(filename)
            return

        # Directory path: full SV elaboration
        if os.path.isdir(filename):
            self.files = []
            for ext in ("psv", "sv", "v"):
                self.files.extend(
                    glob.glob(os.path.join(filename, "**", f"*.{ext}"), recursive=True)
                )
                self.files.extend(glob.glob(os.path.join(filename, f"*.{ext}")))
            self.files = sorted(set(self.files))
            if not self.files:
                raise NetlistParseError(f"No .sv/.v/.psv files found in directory: {filename}")
            _logger.info(f"Parsing {len(self.files)} Verilog/SV files from: {filename}")
            self.format = "verilog"
            self.source_path = os.path.abspath(filename)
        else:
            self.files = [filename]
            _logger.info(f"Parsing netlist: {os.path.abspath(filename)}")
            self.format = self._detect_format()
        self._parse()

    def _detect_format(self) -> str:
        """Detect netlist format from file content."""
        return detect_format(self.files)

    def _parse(self) -> None:
        """Dispatch to format-specific parser."""
        if self.format == "verilog":
            self._parse_verilog()
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
        """Load pre-parsed netlist data from JSON cache."""
        with open(filepath) as f:
            data = json.load(f)
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
            sub = self.subckts.get(cell)
            if sub is not None and pairs:
                merge_aliases_into_subckt(sub, pairs)

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
        subckts, instances = parse_spice(self.files[0])
        self.subckts = subckts
        for inst in instances:
            self._add_instance(inst)

    def _parse_spectre(self) -> None:
        """Parse Spectre netlist."""
        if len(self.files) != 1:
            raise NetlistParseError("Spectre parser expects exactly one file")
        subckts, instances = parse_spectre(self.files[0])
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
                    f"{parent}/{name} (cell={ctype}): {nc} connections but cell has {np_} pins"
                )
        return mismatches

    def dump_json(self, out_path: str) -> None:
        """Write parsed model to JSON cache file.

        Args:
            out_path: Output file path.
        """
        subckts_out = {name: list(sub.pins) for name, sub in self.subckts.items()}
        instances_out = []
        for _parent_cell, insts in self.instances_by_parent.items():
            for inst in insts:
                instances_out.append(
                    {
                        "name": inst.name,
                        "cell_type": inst.cell_type,
                        "nets": list(inst.nets),
                        "parent_cell": inst.parent_cell,
                    }
                )
        aliases_out = {}
        for name, sub in self.subckts.items():
            if not sub.aliases:
                continue
            pairs = sorted([list(p) for p in sub.aliases.items()])
            if pairs:
                aliases_out[name] = pairs
        output = {
            "format": self.format,
            "source": self.source_path,
            "subckts": subckts_out,
            "instances": instances_out,
            "aliases": aliases_out,
        }
        out_dir = os.path.dirname(os.path.abspath(out_path))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w") as fh:
            json.dump(output, fh, indent=2)
        kb = os.path.getsize(out_path) / 1024
        _logger.info(f"Output: {out_path} ({kb:.0f} KB)")
