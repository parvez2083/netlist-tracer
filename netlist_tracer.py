#!/usr/bin/env python3
"""
Bidirectional Hierarchical Netlist Tracer

Traces a pin from one cell to another in CDL, SPICE, Verilog, or Spectre
netlists, exploring both upward (through parent instances) and downward
(through child instances) directions.

Parsing logic lives in the companion library `netlist_parser.py`. This
file contains:
  - TraceStep dataclass
  - BidirectionalTracer (BFS over the parsed model)
  - format_path (renderer for trace paths)
  - main() CLI

Usage:
    python netlist_tracer.py -netlist <file_or_dir> -cell <start_cell_or_inst> -pin <pin> [-target <target>] [-vars <substitutions>]

    -netlist can be a single file, a directory containing .sv/.v/.psv files, or a pre-parsed .json cache.
             For .psv directories, subdirectories are scanned recursively.
    If target is omitted, traces all paths to their endpoints (leaf cells or top-level).
    Format is auto-detected from file content.
    -vars provides template variable substitutions for .psv files as key=value,key=value pairs.

Example:
    python netlist_tracer.py -netlist design.cdl -cell cell1 -pin pin1 -target cell2
    python netlist_tracer.py -netlist design.json -cell cell1 -pin pin1
"""

import argparse
import os
import re
import sys
from collections import deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# All parsing lives in netlist_parser.py (companion library).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from netlist_parser import (
    NetlistParser, SubcktDef, Instance, merge_aliases_into_subckt,
)


@dataclass
class TraceStep:
    """Represents one step in the trace path"""
    cell: str
    pin_or_net: str
    direction: str  # 'start', 'down', 'up', or 'alias'
    instance_name: Optional[str] = None
    # Hierarchical instance stack at this step, ordered outermost-first.
    # Each entry is (inst_name, parent_cell). The last entry corresponds to
    # the instance whose body we are currently inside (i.e., `cell`).
    inst_stack: Tuple[Tuple[str, str], ...] = ()


class BidirectionalTracer:
    """Traces signals bidirectionally through netlist hierarchy"""

    def __init__(self, parser: NetlistParser):
        self.parser = parser
        # Per-cell reverse-alias index: cell -> {canonical_net -> [aliased_nets]}
        # Built lazily on first access via _equivalence_class.
        self._equiv_cache: Dict[str, Dict[str, List[str]]] = {}

    def _equivalence_class(self, cell: str, net: str) -> List[str]:
        """Return all nets in `cell` that are equivalent to `net` under the
        SubcktDef.aliases relation, INCLUDING `net` itself. The result is
        deterministic (canonical first, then alphabetical).

        For cells without aliases (or nets not participating in any alias),
        returns just [net]."""
        sub = self.parser.subckts.get(cell)
        if not sub or not sub.aliases:
            return [net]
        canon_index = self._equiv_cache.get(cell)
        if canon_index is None:
            canon_index = {}
            for n, c in sub.aliases.items():
                canon_index.setdefault(c, []).append(n)
            # Sort each bucket for deterministic enumeration
            for c, lst in canon_index.items():
                lst.sort()
            self._equiv_cache[cell] = canon_index
        canon = sub.aliases.get(net, net)
        equiv = list(canon_index.get(canon, ()))
        if canon not in equiv:
            equiv.insert(0, canon)
        if net not in equiv:
            equiv.insert(0, net)
        return equiv

    def _split_path(self, path: str) -> List[str]:
        """
        Split a hierarchical path on '.' or '/', but treat content inside
        '[...]' as part of one segment (so 'inst1[1]' stays together).
        """
        segments = []
        buf = []
        depth = 0
        for ch in path:
            if ch == '[':
                depth += 1
                buf.append(ch)
            elif ch == ']':
                depth = max(0, depth - 1)
                buf.append(ch)
            elif (ch == '.' or ch == '/') and depth == 0:
                if buf:
                    segments.append(''.join(buf))
                    buf = []
            else:
                buf.append(ch)
        if buf:
            segments.append(''.join(buf))
        return segments

    def _resolve_hierarchical(self, segments: List[str]) -> List[Tuple[str, Tuple[Tuple[str, str], ...]]]:
        """
        Walk segments top-down through the hierarchy. At each step, greedily
        try to consume multiple segments at once (because instance names may
        themselves contain dots, e.g. 'inst1[1].genblk[0].inst2').

        Returns list of (cell_type, full_chain) tuples, where full_chain is
        the ordered tuple of ((inst_name, parent_cell), ...) collected by
        descending the segments. The last entry in the chain corresponds to
        the leaf instance whose body is `cell_type`.
        """
        n = len(segments)

        # state: (next_segment_index, current_parent_cell_type_or_None, chain_so_far)
        # chain_so_far is a tuple of (inst_name, parent_cell) entries.
        results = []
        stack = [(0, None, ())]
        while stack:
            i, parent, chain = stack.pop()
            if i >= n:
                if chain:
                    leaf_cell = chain[-1]  # We'll recover cell_type from the last consumed inst
                    # cell_type was tracked separately via `parent` after the
                    # last consumption; here `parent` is the leaf cell type.
                    results.append((parent, chain))
                continue

            # Try greedy: consume segments[i:j] for j from n down to i+1
            for j in range(n, i, -1):
                candidate = '.'.join(segments[i:j])
                if parent is None:
                    # First segment: search across all instances by name
                    insts = self.parser.instances_by_name.get(candidate, [])
                else:
                    # Subsequent segment: only look in instances under current parent
                    insts = [inst for inst in self.parser.instances_by_parent.get(parent, [])
                             if inst.name == candidate]
                for inst in insts:
                    new_chain = chain + ((inst.name, inst.parent_cell),)
                    stack.append((j, inst.cell_type, new_chain))

        return results

    def resolve_name(self, name: str) -> List[Tuple[str, Optional[Tuple[Tuple[str, str], ...]]]]:
        """
        Resolve a name to (cell_type, full_inst_chain).

        full_inst_chain is None when `name` is a cell type (no instance
        context); a single-element chain for a flat instance name; or a
        multi-element chain for a hierarchical path. The chain is
        outermost-first: chain[0] is the topmost ancestor we know about,
        chain[-1] is the leaf instance whose body is `cell_type`.

        For flat instance names that match multiple instances across the
        design, only the immediate parent context is known — each match
        gets a single-element chain. The trace() method later expands this
        to all possible ancestor chains via _enumerate_ancestor_chains().
        """
        # Check if it's a cell type
        if name in self.parser.subckts:
            return [(name, None)]

        # Search for instances with this name (flat lookup)
        matches: List[Tuple[str, Tuple[Tuple[str, str], ...]]] = [
            (inst.cell_type, ((inst.name, inst.parent_cell),))
            for inst in self.parser.instances_by_name.get(name, [])
        ]

        # Auto-correct instance name prefix mismatches
        if not matches:
            corrected_name = None
            if self.parser.format in ('cdl', 'spice') and not name.startswith('X'):
                # Add X prefix for CDL/SPICE
                corrected_name = 'X' + name
            elif self.parser.format in ('verilog', 'spectre') and name.startswith('X'):
                # Remove X prefix for Verilog/Spectre
                corrected_name = name[1:]

            if corrected_name:
                matches = [(inst.cell_type, ((inst.name, inst.parent_cell),))
                           for inst in self.parser.instances_by_name.get(corrected_name, [])]
                if matches:
                    print(f"  (auto-corrected '{name}' to '{corrected_name}')")

        # Hierarchical path resolution (e.g. 'top.sub.inst1[1].genblk[0].inst2')
        # Returns the FULL chain consumed by the hierarchical path, so the
        # tracer can use it directly without re-enumerating ancestors.
        if not matches:
            segments = self._split_path(name)
            if len(segments) >= 2:
                matches = self._resolve_hierarchical(segments)

        return matches

    def _enumerate_ancestor_chains(self, cell_type: str,
                                   _seen: Optional[set] = None
                                   ) -> List[Tuple[Tuple[str, str], ...]]:
        """Return all hierarchical ancestor chains for a cell type, ordered
        outermost-first. Each chain is a tuple of (inst_name, parent_cell)
        entries terminating at a top-level cell (one with no instances).

        For a top-level cell, returns [()] — a single empty chain meaning
        "no ancestors". For a cell instantiated multiple times, the
        cross-product of parent chains is returned.

        Cycle protection via `_seen` prevents infinite recursion on
        pathological netlists (cell A instantiates cell B which instantiates
        cell A); such cycles produce no chain.
        """
        if _seen is None:
            _seen = set()
        if cell_type in _seen:
            return []
        insts = self.parser.instances_by_celltype.get(cell_type, [])
        if not insts:
            # Top-level: the chain ends here
            return [()]
        _seen = _seen | {cell_type}
        chains: List[Tuple[Tuple[str, str], ...]] = []
        for inst in insts:
            parent_chains = self._enumerate_ancestor_chains(
                inst.parent_cell, _seen)
            for pc in parent_chains:
                chains.append(pc + ((inst.name, inst.parent_cell),))
        return chains

    def trace(self, start_name: str, start_pin: str,
              target_name: Optional[str] = None,
              max_depth: Optional[int] = None) -> List[List[TraceStep]]:
        """Trace from start_name.start_pin to target_name (or all endpoints).

        max_depth: cap each path to start + max_depth more nodes (path length
            <= max_depth+1). None = unbounded. When the start pin is a
            supply (VDD*/VSS*) and max_depth is None, default to 1 so the
            user sees only the immediate UP/DOWN neighbors of the rail
            instead of an exhaustive trace through every consumer.
        """
        start_matches = self.resolve_name(start_name)
        if not start_matches:
            print(f"Error: '{start_name}' not found as cell type or instance name")
            return []

        # Supply-pin start gets max_depth=1 by default (immediate neighbors
        # only). Otherwise tracing from VDD1 would walk every consumer in
        # the design.
        if max_depth is None and re.match(r'^(VDD|VSS)', start_pin):
            max_depth = 1

        # Resolve target if specified.
        # target_set holds entries we'll match BFS frontiers against. Each
        # frontier carries (curr_cell, inst_stack); we match either the leaf
        # context (last entry of inst_stack) or just by cell type.
        target_set = set()
        if target_name:
            target_matches = self.resolve_name(target_name)
            if not target_matches:
                print(f"Error: '{target_name}' not found as cell type or instance name")
                return []
            for cell_type, inst_chain in target_matches:
                # inst_chain is None for cell-type, otherwise a full chain
                leaf_ctx = inst_chain[-1] if inst_chain else None
                target_set.add((cell_type, leaf_ctx))

        # Build list of (start_cell, full_inst_stack) seeds.
        #
        # When the user specifies a hierarchical instance path
        # (e.g. 'top.group[1].sub....leaf'), the resolver
        # returns the EXACT chain — we use it directly as the seed without
        # any further ancestor enumeration.
        #
        # When the user specifies a flat instance name (single segment that
        # matches multiple physical instances), the chain has only the
        # immediate parent. We expand each match by walking up to top-level
        # so subsequent UP steps in the BFS stay constrained to a real
        # ancestor path.
        #
        # When the user specifies a cell type, we enumerate all instances of
        # that cell type and all their ancestor chains.
        #
        # The full-stack seeding is critical: without it, an UP step from an
        # empty stack would enumerate EVERY instance of the cell type across
        # the design, which compounds at every level and causes exponential
        # path explosion.
        seeds: List[Tuple[str, Tuple[Tuple[str, str], ...]]] = []
        for start_cell, start_inst_chain in start_matches:
            subckt = self.parser.subckts.get(start_cell)
            if not subckt or start_pin not in subckt.pin_to_pos:
                print(f"Error: Pin '{start_pin}' not found in cell '{start_cell}'")
                if subckt:
                    # Suggest pins similar to what the user typed: prefer
                    # substring matches (case-insensitive), then fall back
                    # to difflib similarity. Strip [bit] suffix from each
                    # pin so a query like 'pin1' matches 'pin1[3]'.
                    import difflib
                    q = start_pin.lower()
                    base = lambda p: re.sub(r'\[\d+\]$', '', p)
                    seen, suggestions = set(), []
                    # Substring matches first (most useful)
                    for p in subckt.pins:
                        b = base(p)
                        if q in b.lower() and b not in seen:
                            seen.add(b)
                            suggestions.append(b)
                    # Then fuzzy matches on bases not already shown
                    bases = list(dict.fromkeys(base(p) for p in subckt.pins))
                    for s in difflib.get_close_matches(start_pin, bases, n=10, cutoff=0.6):
                        if s not in seen:
                            seen.add(s)
                            suggestions.append(s)
                    if suggestions:
                        print(f"Did you mean: {suggestions[:10]}")
                    else:
                        print(f"Available pins ({len(subckt.pins)} total): {subckt.pins[:10]}...")
                continue
            if start_inst_chain is None:
                # Cell-type start: enumerate every real instance and its
                # ancestor chain(s) up to top-level.
                chains = self._enumerate_ancestor_chains(start_cell)
                if not chains:
                    # start_cell is itself a top-level cell with no
                    # ancestors (or part of a cycle); seed with empty stack.
                    seeds.append((start_cell, ()))
                else:
                    for chain in chains:
                        seeds.append((start_cell, chain))
            elif len(start_inst_chain) == 1:
                # Flat instance name: only the immediate parent is known.
                # Expand to all ancestor chains for that parent so UP steps
                # in the BFS stay constrained.
                inst_name, parent_cell = start_inst_chain[0]
                parent_chains = self._enumerate_ancestor_chains(parent_cell)
                if not parent_chains:
                    seeds.append((start_cell, start_inst_chain))
                else:
                    for pc in parent_chains:
                        seeds.append((start_cell, pc + start_inst_chain))
            else:
                # Hierarchical path: the user's exact chain is authoritative;
                # use it as-is. (We do NOT walk further up because the user
                # may have intentionally rooted at an interior cell.)
                seeds.append((start_cell, start_inst_chain))

        all_paths = []

        for start_cell, initial_stack in seeds:
            subckt = self.parser.subckts.get(start_cell)
            initial_step = TraceStep(
                cell=start_cell,
                pin_or_net=start_pin,
                direction='start',
                instance_name=initial_stack[-1][0] if initial_stack else None,
                inst_stack=initial_stack,
            )

            queue = deque([(start_cell, start_pin, initial_stack, [initial_step])])
            visited = set()

            while queue:
                curr_cell, curr_net, inst_stack, path = queue.popleft()

                state_key = (curr_cell, curr_net, inst_stack)
                if state_key in visited:
                    continue
                visited.add(state_key)

                # Safety: empty-string nets are never legitimate signals —
                # they come from preparser fallbacks for unconnected pins
                # (e.g. `.pin1()`, `.pin2()`). Treat them as
                # do-not-bridge so two unrelated unconnected pins never get
                # joined into a fake supernet.
                if curr_net == '':
                    continue

                # Constant-literal terminator: Verilog literals like 1'b0,
                # 1'b1, 4'h0 are recorded as nets but are actually tieoff
                # constants. Record the path so callers can see what the
                # constant is, then stop propagating (otherwise every pin
                # tied to `1'b0` would bridge into one fake supernet).
                if re.match(r"^\d+'[bdohBDOH][0-9a-fA-FxXzZ_?]+$", curr_net):
                    if len(path) > 1:
                        all_paths.append(path)
                    continue

                # Supply-net terminator: VDD*/VSS* nets are global power
                # rails. Without this, a single rail bridges thousands of
                # unrelated signals into one fake supernet. Treat as a hard
                # mid-trace endpoint. The start step itself (len==1) is
                # exempt so a supply-pin trace can still expand once;
                # max_depth=1 (auto-set in trace() for supply starts) then
                # terminates after that one hop.
                if re.match(r'^(VDD|VSS)', curr_net) and len(path) > 1:
                    all_paths.append(path)
                    continue

                # User-supplied depth cap: max_depth+1 nodes total (start
                # + max_depth more). Default is unbounded; supply-pin
                # starts default to 1 (set in trace()).
                if max_depth is not None and len(path) > max_depth:
                    all_paths.append(path)
                    continue

                # Check if we reached the target
                if target_name:
                    curr_ctx = inst_stack[-1] if inst_stack else None
                    if (curr_cell, curr_ctx) in target_set or (curr_cell, None) in target_set:
                        all_paths.append(path)
                        continue

                queue_len_before = len(queue)
                path_cells = {(s.cell, s.pin_or_net) for s in path}

                # Expand assign-aliases: enqueue every net equivalent to
                # curr_net under this cell's `assign A = B;` relation, with
                # an explicit 'alias' step so the user can see why the two
                # nets are connected.
                for equiv_net in self._equivalence_class(curr_cell, curr_net):
                    if equiv_net == curr_net:
                        continue
                    if (curr_cell, equiv_net) in path_cells:
                        continue
                    alias_step = TraceStep(
                        cell=curr_cell,
                        pin_or_net=equiv_net,
                        direction='alias',
                        instance_name=None,
                        inst_stack=inst_stack,
                    )
                    queue.append((curr_cell, equiv_net, inst_stack,
                                  path + [alias_step]))

                # Explore downward (into child instances)
                for inst in self.parser.instances_by_parent.get(curr_cell, []):
                    if curr_net not in inst.nets:
                        continue
                    net_pos = inst.nets.index(curr_net)
                    child_subckt = self.parser.subckts.get(inst.cell_type)
                    if not child_subckt or net_pos >= len(child_subckt.pins):
                        continue
                    child_pin = child_subckt.pins[net_pos]
                    if (inst.cell_type, child_pin) in path_cells:
                        continue

                    new_stack_down = inst_stack + ((inst.name, curr_cell),)
                    new_step = TraceStep(
                        cell=inst.cell_type,
                        pin_or_net=child_pin,
                        direction='down',
                        instance_name=inst.name,
                        inst_stack=new_stack_down,
                    )
                    queue.append((
                        inst.cell_type,
                        child_pin,
                        new_stack_down,
                        path + [new_step]
                    ))

                # Explore upward (to parent instances)
                #
                # The inst_stack carries the FULL ancestor chain that this
                # BFS branch is operating in (seeded at trace() start). UP is
                # only legal when we have a parent context to pop — if the
                # stack is empty, we are at the top of the chain and cannot
                # go further up. Enumerating instances_by_celltype here would
                # cross-contaminate ancestor chains and cause path
                # explosion.
                subckt = self.parser.subckts.get(curr_cell)
                if subckt and curr_net in subckt.pin_to_pos and inst_stack:
                    pin_pos = subckt.pin_to_pos[curr_net]
                    inst_name, parent_cell = inst_stack[-1]
                    instances = [i for i in self.parser.instances_by_celltype.get(curr_cell, [])
                                 if i.name == inst_name and i.parent_cell == parent_cell]
                    new_stack = inst_stack[:-1]

                    for inst in instances:
                        if pin_pos >= len(inst.nets):
                            continue
                        parent_net = inst.nets[pin_pos]
                        if (inst.parent_cell, parent_net) in path_cells:
                            continue

                        new_step = TraceStep(
                            cell=inst.parent_cell,
                            pin_or_net=parent_net,
                            direction='up',
                            instance_name=inst.name,
                            inst_stack=new_stack,
                        )
                        queue.append((
                            inst.parent_cell,
                            parent_net,
                            new_stack,
                            path + [new_step]
                        ))

                # If no target and no new paths, this is an endpoint
                if not target_name and len(queue) == queue_len_before and len(path) > 1:
                    all_paths.append(path)

        return all_paths


def format_path(path: List[TraceStep]) -> str:
    """Format a trace path as a single compact line.

    Each step displays the hierarchical instance chain in effect AT that
    step, taken from `step.inst_stack`, expressed RELATIVE TO the topmost
    cell reached during the trace. The topmost is the step with the
    shortest inst_stack (i.e. the highest point reached after all UP pops);
    its stack is the common prefix that we strip from every other step's
    chain so the displayed instance reference is anchored at the common
    parent rather than at design-top.

    Step formats:
      - At topmost (relative chain empty):  <cell>/<internal>.<net>
      - Otherwise:                          <cell>/<rel_hier_inst>.<net>
                                            where rel_hier_inst is the
                                            dot-joined inst names AFTER
                                            stripping the topmost's prefix.

    Note: '<internal>' is a literal placeholder marking a local peak (no
    enclosing instance reference at that step), NOT a wildcard.

    The inst_stack on each step is maintained by the BFS: DOWN pushes
    (inst_name, parent_cell), UP pops the last entry. The seed chain at the
    start step is the user-specified or enumerated ancestor chain.
    """
    if not path:
        return ""

    # Mark TRUE peaks (UP→DOWN turning points) as <internal>.
    # Strip the GLOBAL shallowest prefix from every step so the rendered
    # chain is anchored at the trace's topmost cell.
    global_min = min(len(step.inst_stack) for step in path)

    # A "true peak" is a maximal contiguous plateau of equal-depth steps
    # bounded by STRICTLY higher depths on both sides (or by path edges,
    # which count as higher boundaries). Within each such plateau, ALL
    # steps are marked — including UP/DOWN transitions that land at the
    # peak depth alongside any aliases there.
    #
    # This correctly distinguishes a real reversal point from a step that
    # merely happens to be the shallowest within an alias-bounded segment
    # (which the previous logic over-marked). Examples:
    #   UP-alias-UP-peak-DOWN  → only the peak step is <internal>;
    #                            the alias is on the slope, not the peak
    #   UP-alias-DOWN          → both UP and alias are at the peak plateau
    is_local_peak = [False] * len(path)
    depths = [len(s.inst_stack) for s in path]
    n = len(path)
    i = 0
    while i < n:
        d = depths[i]
        j = i
        while j + 1 < n and depths[j + 1] == d:
            j += 1
        left_higher = (i == 0) or (depths[i - 1] > d)
        right_higher = (j == n - 1) or (depths[j + 1] > d)
        if left_higher and right_higher:
            for k in range(i, j + 1):
                is_local_peak[k] = True
        i = j + 1

    # Render format: <CELL>|<hier1>/<hier2>/...|<NET>
    # The '|' delimiters keep the three segments unambiguous even when the
    # individual segments contain '.':
    #   - cell: never has '.'
    #   - each hier element may have '.' (SV generate-block elaborated names
    #     like `sub[1].inst2`); '/' joins consecutive elements
    #   - net may have '.' (SV interface/struct member access like
    #     `bus[1].pin1`)
    parts = []
    for i, step in enumerate(path):
        rel = step.inst_stack[global_min:]
        if is_local_peak[i] or not rel:
            inst = '<internal>'
        else:
            inst = '/'.join(s[0] for s in rel)
        parts.append(f"{step.cell}|{inst}|{step.pin_or_net}")
    return " -- ".join(parts)


def main():
    parser = argparse.ArgumentParser(description="Bidirectional Hierarchical Netlist Tracer")
    parser.add_argument("-netlist", required=True, help="Path to netlist file or directory of .sv/.v files")
    parser.add_argument("-cell", required=True, help="Start cell or instance name")
    parser.add_argument("-pin", required=True, help="Start pin name")
    parser.add_argument("-target", default=None, help="Target cell or instance name (optional)")
    parser.add_argument("-max_depth", type=int, default=None,
        help="Cap each path to start + max_depth more nodes "
             "(default: unbounded; auto=1 when -pin is a VDD*/VSS* supply)")
    parser.add_argument("-defines", default=None,
        help="Comma-separated list of preprocessor defines to treat as defined "
             "(e.g. FEATURE1,FEATURE2)")
    args = parser.parse_args()

    user_defines = set(args.defines.split(',')) if args.defines else set()

    netlist_file = args.netlist
    start_name = args.cell
    start_pin = args.pin
    target_name = args.target

    # Check if file or directory exists
    if not os.path.isfile(netlist_file) and not os.path.isdir(netlist_file):
        print(f"Error: Netlist file or directory not found: {netlist_file}")
        sys.exit(1)

    try:
        parser = NetlistParser(netlist_file, defines=user_defines if user_defines else None)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error: Failed to parse netlist: {e}")
        sys.exit(1)
    print(f"Format: {parser.format}")
    print(f"Found {len(parser.subckts)} module/subcircuit definitions")

    tracer = BidirectionalTracer(parser)

    # Display resolution info. resolve_name returns (cell_type, chain) where
    # chain is None for cell-type matches and a tuple of (inst, parent)
    # entries (outermost-first) otherwise.
    def _print_match(cell_type, chain):
        if chain:
            leaf_inst, leaf_parent = chain[-1]
            if len(chain) == 1:
                print(f"  -> instance {leaf_inst} of {cell_type} (in {leaf_parent})")
            else:
                hier = '.'.join(c[0] for c in chain)
                print(f"  -> instance {hier} of {cell_type}")
        else:
            print(f"  -> cell type {cell_type}")

    start_matches = tracer.resolve_name(start_name)
    print(f"\nStart: {start_name}")
    for cell_type, chain in start_matches:
        _print_match(cell_type, chain)

    if target_name:
        target_matches = tracer.resolve_name(target_name)
        print(f"Target: {target_name}")
        for cell_type, chain in target_matches:
            _print_match(cell_type, chain)
        print(f"\nTracing: {start_name}.{start_pin} -> {target_name}")
    else:
        print(f"Target: (all endpoints)")
        print(f"\nTracing: {start_name}.{start_pin} -> all endpoints")

    print("-" * 50)

    paths = tracer.trace(start_name, start_pin, target_name,
                         max_depth=args.max_depth)

    if paths:
        # Deduplicate by formatted output. Multiple BFS seeds can share the
        # same relative-to-topmost view (e.g., two ancestor chains that
        # diverge only in cells we never trace through), and those produce
        # identical display strings. Order is preserved (first occurrence
        # wins) so output stays deterministic.
        seen = set()
        unique_paths = []
        for path in paths:
            sig = format_path(path)
            if sig in seen:
                continue
            seen.add(sig)
            unique_paths.append((path, sig))
        print(f"\nFound {len(unique_paths)} path(s):")
        print("Format: <CELL>|<HierarchicalInstanceName>|<PIN>   "
              "where HierarchicalInstanceName = <inst1>/<inst2>/.../<CELL_INST>")
        print("        <CELL>|<internal>|<NET>   for the topmost CELL's pin "
              "(same as NET) connecting to a subblock pin, OR a local "
              "maxima in the path where 2 subblock pins are connected by "
              "a NET inside the CELL\n")
        for i, (path, sig) in enumerate(unique_paths, 1):
            print(f"Path {i}: {sig}")
    else:
        print("\nNo paths found.")
        print("Possible reasons:")
        print("  - The cells are not hierarchically connected")
        print("  - The pin name is incorrect")
        print("  - The cell has no connections through this pin")


if __name__ == "__main__":
    main()
