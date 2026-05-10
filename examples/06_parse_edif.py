#!/usr/bin/env python3
"""
Example 6: Parse an EDIF netlist and demonstrate bus expansion and tracing.

This example demonstrates EDIF format auto-detection, subcircuit discovery,
bus-pin expansion, and bidirectional signal tracing on an EDIF netlist.
"""

from netlist_tracer import BidirectionalTracer, NetlistParser, format_path

# Parse the EDIF netlist with auto-detection
netlist_file = "tests/fixtures/vendored/n_bit_counter.edf"
parser = NetlistParser(netlist_file)

print(f"Netlist file: {netlist_file}")
print(f"Format detected: {parser.format}")
assert parser.format == "edif", f"Expected format 'edif', got '{parser.format}'"
print()

# List all subcircuits with their pin counts
print("Subcircuits found:")
for name in sorted(parser.subckts.keys()):
    sub = parser.subckts[name]
    print(f"  - {name}: {len(sub.pins)} pins")
print()

# Show the top cell (n_bit_counter) and its pins
top_cell = "n_bit_counter"
if top_cell in parser.subckts:
    top_sub = parser.subckts[top_cell]
    print(f"Top cell: {top_cell}")
    print(f"Pins (bus-expanded): {top_sub.pins}")
    print()

# Demonstrate bus expansion using expand_pin
tracer = BidirectionalTracer(parser)
counter_base = "counter"
expanded = tracer.expand_pin(parser.subckts[top_cell], counter_base)
print(f"Bus expansion for '{counter_base}':")
print(f"  {counter_base} expands to: {expanded}")
print()

# Trace a signal: clk through the hierarchy
print("=" * 70)
print(f"Tracing 'clk' through {top_cell}:")
print("=" * 70)
paths = tracer.trace(top_cell, "clk")
print(f"Found {len(paths)} path(s):\n")

for i, path in enumerate(paths, 1):
    formatted = format_path(path)
    print(f"Path {i}: {formatted}")

print()
