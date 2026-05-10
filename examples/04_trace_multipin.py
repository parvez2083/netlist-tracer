#!/usr/bin/env python3
"""Example: Tracing multiple pins at once using the trace_pins method.

trace_pins() accepts pin names in three forms:
  1. Exact bit-level (e.g., "data[3]") — traces that single pin.
  2. Bare bus base name (e.g., "data") — auto-expands to all indexed
     members "data[0]", "data[1]", ..., "data[N]".
  3. pins=None (omit-mode) — traces every bit-level pin in the cell.

Each result key in the returned dict is a single bit-level pin name; bus
expansions produce one key per bit, equivalent to passing the bits as a
comma-separated list.
"""

from netlist_tracer import BidirectionalTracer, NetlistParser


def main():
    # Parse the picorv32 netlist
    parser = NetlistParser("tests/fixtures/vendored/picorv32.v")
    tracer = BidirectionalTracer(parser)

    print("=" * 70)
    print("Example 1: Trace specific bit-level pins (explicit list)")
    print("=" * 70)

    # Trace specific pins: clk and resetn
    results = tracer.trace_pins("picorv32", pins=["clk", "resetn"])

    for pin_name in sorted(results.keys()):
        paths = results[pin_name]
        print(f"\nPin: {pin_name}")
        if paths:
            print(f"  Found {len(paths)} trace path(s)")
            # Show first path as example
            for step in paths[0]:
                print(f"    - {step.cell}|{step.pin_or_net}|{step.direction}")
        else:
            print("  (no paths)")

    print("\n" + "=" * 70)
    print("Example 2: Trace ALL bit-level pins in the cell (omit-mode)")
    print("=" * 70)

    # Trace all bit-level pins by omitting the pins argument
    all_results = tracer.trace_pins("picorv32")

    print(f"\nTracing all {len(all_results)} bit-level pins in picorv32")
    print("Pins found:")
    for pin_name in sorted(all_results.keys())[:5]:  # Show first 5
        paths = all_results[pin_name]
        print(f"  {pin_name}: {len(paths)} path(s)")
    if len(all_results) > 5:
        print(f"  ... and {len(all_results) - 5} more pins")

    print("\n" + "=" * 70)
    print("Example 3: Bare bus name auto-expands to all indexed members")
    print("=" * 70)

    # picorv32 has mem_addr[0]..mem_addr[31] as 32 bit-level pins.
    # Passing the bare bus base name 'mem_addr' expands to all 32 bits.
    bus_results = tracer.trace_pins("picorv32", pins=["mem_addr"])
    print(f"\ntrace_pins('picorv32', pins=['mem_addr']) returned {len(bus_results)} keys")
    print(f"  First 3 keys: {sorted(bus_results.keys())[:3]}")
    print(f"  Last  3 keys: {sorted(bus_results.keys())[-3:]}")
    print("\nThis is equivalent to passing the comma-separated bit list:")
    print("  pins=['mem_addr[0]', 'mem_addr[1]', ..., 'mem_addr[31]']")


if __name__ == "__main__":
    main()
