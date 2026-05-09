#!/usr/bin/env python3
"""Example: Tracing multiple pins at once using the trace_pins method.

This example demonstrates the Strict Bit-Level semantics of netlist-tracer:
pin tracing operates ONLY on bit-level pin names (e.g., data[0], data[1]).
Bare bus names (e.g., 'data') are NOT expanded automatically.

Note: For v0.1, bus-name expansion is not supported. To trace multiple bits
of a bus, either specify each bit explicitly or use omit-mode (pins=None)
to trace all bit-level pins of the cell.
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
    print("Example 3: Demonstrating Strict Bit-Level semantics")
    print("=" * 70)

    # Get list of all bit-level pins (these are the only valid ones)
    subckt = parser.subckts.get("picorv32")
    if subckt:
        print(f"\nValid bit-level pins in picorv32: {subckt.pins[:10]}...")
        print("\nNote: These are the ONLY pin names you can use with trace_pins().")
        print("Bare bus names (if they exist) would require specifying each bit,")
        print("e.g., '-pin data[0],data[1],data[2]' not '-pin data'.")


if __name__ == "__main__":
    main()
