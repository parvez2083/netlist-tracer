#!/usr/bin/env python3
"""
Example 1: Parse a netlist and inspect its structure.

This example demonstrates basic netlist parsing, subcircuit discovery,
and inspection of ports and instances.
"""

from netlist_tracer import NetlistParser

# Parse a SPICE netlist
netlist_file = "tests/fixtures/synthetic/spice_basic.sp"
parser = NetlistParser(netlist_file)

print(f"Format detected: {parser.format}")
print(f"Subcircuits found: {len(parser.subckts)}")
print(f"Total instances: {sum(len(v) for v in parser.instances_by_parent.values())}\n")

# List all subcircuit names
print("Subcircuit names:")
for name in sorted(parser.subckts.keys()):
    sub = parser.subckts[name]
    print(f"  - {name}: {len(sub.pins)} pins")

# Show details of the first subcircuit
if parser.subckts:
    first_name = sorted(parser.subckts.keys())[0]
    first_sub = parser.subckts[first_name]
    print(f"\nFirst subcircuit: {first_name}")
    print(f"  Pins: {first_sub.pins}")
    print(f"  Aliases: {first_sub.aliases if first_sub.aliases else '(none)'}")

    # Show instances within this subcircuit
    instances_in_first = parser.instances_by_parent.get(first_name, [])
    if instances_in_first:
        print(f"  Instances ({len(instances_in_first)}):")
        for inst in instances_in_first[:3]:  # Show first 3
            print(f"    - {inst.name} ({inst.cell_type}): {inst.nets}")
