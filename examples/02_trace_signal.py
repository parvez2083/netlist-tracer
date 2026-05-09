#!/usr/bin/env python3
"""
Example 2: Trace a signal through the netlist hierarchy.

This example demonstrates bidirectional hierarchical signal tracing,
showing how a signal connects through instances and resolving aliases.
"""

from nettrace import BidirectionalTracer, NetlistParser, format_path

# Parse the sky130 inverter SPICE netlist
netlist_file = "tests/fixtures/vendored/sky130_fd_sc_hd__inv_1.spice"
parser = NetlistParser(netlist_file)

print(f"Parsed netlist: {netlist_file}")
print(f"Format: {parser.format}")
print(f"Subcircuits: {', '.join(parser.subckts.keys())}\n")

# Create a tracer
tracer = BidirectionalTracer(parser)

# Trace from the input pin 'A' of the top cell
start_cell = "sky130_fd_sc_hd__inv_1"
start_pin = "A"

print(f"Tracing from: {start_cell}.{start_pin}\n")

# Get all paths
paths = tracer.trace(start_cell, start_pin)

print(f"Found {len(paths)} path(s):\n")

# Format and display each path
for i, path in enumerate(paths, 1):
    formatted = format_path(path)
    print(f"Path {i}: {formatted}")

    # Show details of the first path
    if i == 1:
        print("\n  Path details (first path only):")
        for j, step in enumerate(path):
            print(f"    Step {j}: cell={step.cell}, pin/net={step.pin_or_net}, "
                  f"direction={step.direction}")
        print()
