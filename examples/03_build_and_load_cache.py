#!/usr/bin/env python3
"""
Example 3: Build and load a JSON cache for fast re-parsing.

This example demonstrates the JSON cache feature, which serializes a parsed
netlist for quick subsequent loading without re-parsing the source format.
"""

import os
import tempfile

from netlist_tracer import NetlistParser

# Parse and serialize
source_file = "tests/fixtures/vendored/sky130_fd_sc_hd__inv_1.spice"
parser1 = NetlistParser(source_file)

print(f"Original parse from: {source_file}")
print(f"Subcircuits: {len(parser1.subckts)}")
print(f"Instances: {sum(len(v) for v in parser1.instances_by_parent.values())}\n")

# Dump to a temporary JSON cache
with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
    cache_file = f.name

try:
    parser1.dump_json(cache_file)
    print(f"Cached to: {cache_file}")
    print(f"Cache size: {os.path.getsize(cache_file)} bytes\n")

    # Load from cache (fast path)
    parser2 = NetlistParser(cache_file)
    print(f"Loaded from cache: {cache_file}")
    print(f"Subcircuits: {len(parser2.subckts)}")
    print(f"Instances: {sum(len(v) for v in parser2.instances_by_parent.values())}\n")

    # Verify they match
    if len(parser1.subckts) == len(parser2.subckts) and sum(
        len(v) for v in parser1.instances_by_parent.values()
    ) == sum(len(v) for v in parser2.instances_by_parent.values()):
        print("✓ Cache verification PASSED: structure matches")
    else:
        print("✗ Cache verification FAILED: structure mismatch")

finally:
    # Clean up
    if os.path.exists(cache_file):
        os.remove(cache_file)
        print(f"\nCleaned up: {cache_file}")
