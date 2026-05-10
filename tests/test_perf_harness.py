"""Performance harness for large netlist parsing."""

from __future__ import annotations

import time

import pytest

from netlist_tracer import NetlistParser


class TestPerfHarness:
    """Performance validation tests for parser scalability."""

    @pytest.mark.slow
    def test_large_verilog_parse_performance(self, tmp_path):
        """Parse large generated Verilog with 1000+ instances within time budget."""
        # Generate inline Verilog: FF module + top instantiating it 1000×
        verilog_content = """\
module dff(
    input clk,
    input d,
    output reg q
);
    always @(posedge clk) q <= d;
endmodule

module top(
    input clk,
    input [999:0] d_in,
    output [999:0] q_out
);
    generate
        genvar i;
        for (i = 0; i < 1000; i = i + 1) begin : gen_dff
            dff ff_inst (
                .clk(clk),
                .d(d_in[i]),
                .q(q_out[i])
            );
        end
    endgenerate
endmodule
"""
        # Write to temp file
        verilog_file = tmp_path / "large_design.v"
        verilog_file.write_text(verilog_content)

        # Parse and measure wall time
        start = time.perf_counter()
        parser = NetlistParser(str(verilog_file))
        elapsed = time.perf_counter() - start

        # Assert performance: parse time < 30s (generous for slow CI)
        assert elapsed < 30.0, f"Parse time {elapsed:.2f}s exceeds 30s threshold"

        # Assert structural completeness: ≥ 1000 instances total
        total_instances = sum(
            len(parser.instances_by_parent[cell]) for cell in parser.instances_by_parent
        )
        assert total_instances >= 1000, f"Expected ≥1000 instances, got {total_instances}"
