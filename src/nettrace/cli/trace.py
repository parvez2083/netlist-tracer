from __future__ import annotations

import argparse
import logging
import os

from nettrace.exceptions import NetlistParseError
from nettrace.parser import NetlistParser
from nettrace.tracer import BidirectionalTracer, format_path


def main() -> int:
    """Trace signal paths through a netlist (CLI entry point).

    Returns:
        Exit code (0 for success, 1 for error).
    """
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Bidirectional Hierarchical Netlist Tracer")
    parser.add_argument(
        "-netlist", required=True, help="Path to netlist file or directory of .sv/.v files"
    )
    parser.add_argument("-cell", required=True, help="Start cell or instance name")
    parser.add_argument("-pin", required=True, help="Start pin name")
    parser.add_argument("-target", default=None, help="Target cell or instance name (optional)")
    parser.add_argument(
        "-max_depth", type=int, default=None, help="Cap each path to start + max_depth more nodes"
    )
    parser.add_argument(
        "-defines", default=None, help="Comma-separated list of preprocessor defines"
    )
    args = parser.parse_args()

    user_defines = set(args.defines.split(",")) if args.defines else set()

    netlist_file = args.netlist
    start_name = args.cell
    start_pin = args.pin
    target_name = args.target

    if not os.path.isfile(netlist_file) and not os.path.isdir(netlist_file):
        print(f"Error: Netlist file or directory not found: {netlist_file}")
        return 1

    try:
        nl_parser = NetlistParser(netlist_file, defines=user_defines if user_defines else None)
    except NetlistParseError as e:
        print(f"Error: {e}")
        return 1
    except Exception as e:
        print(f"Error: Failed to parse netlist: {e}")
        return 1

    print(f"Format: {nl_parser.format}")
    print(f"Found {len(nl_parser.subckts)} module/subcircuit definitions")

    tracer = BidirectionalTracer(nl_parser)

    def _print_match(cell_type, chain):
        if chain:
            leaf_inst, leaf_parent = chain[-1]
            if len(chain) == 1:
                print(f"  -> instance {leaf_inst} of {cell_type} (in {leaf_parent})")
            else:
                hier = ".".join(c[0] for c in chain)
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
        print("Target: (all endpoints)")
        print(f"\nTracing: {start_name}.{start_pin} -> all endpoints")  # noqa: F541

    print("-" * 50)

    paths = tracer.trace(start_name, start_pin, target_name, max_depth=args.max_depth)

    if paths:
        seen = set()
        unique_paths = []
        for path in paths:
            sig = format_path(path)
            if sig in seen:
                continue
            seen.add(sig)
            unique_paths.append((path, sig))
        print(f"\nFound {len(unique_paths)} path(s):")
        print(
            "Format: <CELL>|<HierarchicalInstanceName>|<PIN>   "
            "where HierarchicalInstanceName = <inst1>/<inst2>/.../<CELL_INST>"
        )
        print(
            "        <CELL>|<internal>|<NET>   for the topmost CELL's pin "
            "(same as NET) connecting to a subblock pin, OR a local "
            "maxima in the path where 2 subblock pins are connected by "
            "a NET inside the CELL\n"
        )
        for i, (_path, sig) in enumerate(unique_paths, 1):
            print(f"Path {i}: {sig}")
        return 0
    else:
        print("\nNo paths found.")
        print("Possible reasons:")
        print("  - The cells are not hierarchically connected")
        print("  - The pin name is incorrect")
        print("  - The cell has no connections through this pin")
        return 0


if __name__ == "__main__":
    exit(main())
