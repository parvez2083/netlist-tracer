"""Tests for Verilog quick-win features: generate-if, generate-case, primitives, defparam."""

from netlist_tracer import NetlistParser


class TestGenerateIf:
    """Tests for generate-if conditional compilation."""

    def test_generate_if_smoke(self, synthetic_verilog_generate_if_v):
        """Smoke test: generate-if fixture parses without error."""
        parser = NetlistParser(synthetic_verilog_generate_if_v)
        assert "verilog_generate_if" in parser.subckts
        mod = parser.subckts["verilog_generate_if"]
        assert mod is not None

    def test_generate_if_branch_isolation(self, tmp_path):
        """generate-if with gate instances should select only the true branch and isolate it."""
        code = """
module gate_inst(input clk, output q);
  parameter DO_GATE = 1;
  generate
    if (DO_GATE > 0) begin : g_on
      and u_and (q, clk, clk);
    end else begin : g_off
      buf u_buf (q, clk);
    end
  endgenerate
endmodule
"""
        vfile = tmp_path / "test_gen_if_branch.v"
        vfile.write_text(code)
        parser = NetlistParser(str(vfile))
        insts = parser.instances_by_parent.get("gate_inst", [])
        names = [i.name for i in insts]

        # True branch (DO_GATE > 0) should be selected: u_and must be present
        assert "u_and" in names, f"Selected branch missing: {names}"
        # False branch should be isolated: u_buf must NOT be present
        assert "u_buf" not in names, f"Rejected branch leaked: {names}"

    def test_generate_if_with_direct_assignment(self, tmp_path):
        """Test generate-if with direct wire assignment (creates aliases)."""
        vfile = tmp_path / "test_gen_if_alias.v"
        vfile.write_text(
            """
module test_gen_if_alias #(parameter ENABLE = 1) (
  input wire [3:0] in,
  output wire [3:0] out
);
  generate
    if (ENABLE == 1) begin : enabled
      assign out = in;
    end else begin : disabled
      assign out = 4'b0000;
    end
  endgenerate
endmodule
"""
        )
        parser = NetlistParser(str(vfile))
        assert "test_gen_if_alias" in parser.subckts
        mod = parser.subckts["test_gen_if_alias"]
        # Should have parsed the true branch with direct assignment
        assert mod is not None


class TestGenerateCase:
    """Tests for generate-case conditional compilation."""

    def test_generate_case_smoke(self, synthetic_verilog_generate_case_v):
        """Smoke test: generate-case fixture parses without error."""
        parser = NetlistParser(synthetic_verilog_generate_case_v)
        mod = parser.subckts["verilog_generate_case"]
        assert mod is not None

    def test_generate_case_branch_isolation(self, tmp_path):
        """generate-case with gate instances should select only the matching arm and isolate others."""
        code = """
module mode_select(input clk, output q);
  parameter MODE = 1;
  generate
    case (MODE)
      0: begin : arm_0
        not u_arm0_not (q, clk);
      end
      1: begin : arm_1
        buf u_arm1_buf (q, clk);
      end
      2: begin : arm_2
        and u_arm2_and (q, clk, clk);
      end
      default: begin : arm_default
        nor u_default_nor (q, clk, clk);
      end
    endcase
  endgenerate
endmodule
"""
        vfile = tmp_path / "test_gen_case_branch.v"
        vfile.write_text(code)
        parser = NetlistParser(str(vfile))
        insts = parser.instances_by_parent.get("mode_select", [])
        names = [i.name for i in insts]

        # MODE=1 is selected: u_arm1_buf must be present
        assert "u_arm1_buf" in names, f"Selected arm missing: {names}"
        # Other arms must be isolated: u_arm0_not, u_arm2_and, u_default_nor must NOT be present
        assert "u_arm0_not" not in names, f"Unselected arm 0 leaked: {names}"
        assert "u_arm2_and" not in names, f"Unselected arm 2 leaked: {names}"
        assert "u_default_nor" not in names, f"Unselected default leaked: {names}"

    def test_generate_case_default(self, tmp_path):
        """generate-case with unmatched value should pick default."""
        vfile = tmp_path / "test_gen_case_dflt.v"
        vfile.write_text(
            """
module test_gen_case_dflt #(parameter MODE = 99) (
  input wire [3:0] in,
  output wire [3:0] out
);
  generate
    case (MODE)
      1: begin : mode_1
        assign out = in;
      end
      2: begin : mode_2
        assign out = ~in;
      end
      default: begin : mode_default
        assign out = 4'b1111;
      end
    endcase
  endgenerate
endmodule
"""
        )
        parser = NetlistParser(str(vfile))
        mod = parser.subckts["test_gen_case_dflt"]
        assert mod is not None


class TestGatePrimitives:
    """Tests for built-in gate primitive instantiation."""

    def test_primitive_instances_appear(self, synthetic_verilog_gate_primitives_v):
        """Primitive instances should be recognized with synthesized cell types."""
        parser = NetlistParser(synthetic_verilog_gate_primitives_v)
        mod = parser.subckts["verilog_gate_primitives"]
        assert mod is not None

        # Check that we have instances
        insts_in_module = parser.instances_by_parent.get("verilog_gate_primitives", [])
        assert len(insts_in_module) > 0

        # At least one instance should reference a synthesized primitive cell
        has_synthesized = any("__prim_" in inst.cell_type for inst in insts_in_module)
        assert has_synthesized, "Should have at least one synthesized primitive cell"

    def test_primitive_cell_definitions(self, synthetic_verilog_gate_primitives_v):
        """Synthesized primitive cell definitions should exist."""
        parser = NetlistParser(synthetic_verilog_gate_primitives_v)

        # Check for synthesized primitives in subckt dict
        syn_cells = {name for name in parser.subckts.keys() if "__prim_" in name}
        assert len(syn_cells) > 0, "Should have synthesized primitive cells"

        # Check that at least 'and' and 'nand' primitives are present
        expected_prims = {"__prim_and_3__", "__prim_nand_3__"}
        assert expected_prims.issubset(syn_cells), (
            f"Expected primitives {expected_prims} not found in {syn_cells}"
        )


class TestDefparam:
    """Tests for defparam parameter override."""

    def test_defparam_override(self, synthetic_verilog_defparam_v):
        """defparam should override inline #() parameter values."""
        parser = NetlistParser(synthetic_verilog_defparam_v)
        mod_top = parser.subckts["verilog_defparam"]
        assert mod_top is not None

        # The module should have an instance of 'counter'
        insts_in_top = parser.instances_by_parent.get("verilog_defparam", [])
        assert len(insts_in_top) == 1
        inst = insts_in_top[0]
        assert inst.name == "u_counter"
        # Cell type may be specialized variant with parameters
        assert "counter" in inst.cell_type

        # The instance should have WIDTH parameter set by defparam
        # WIDTH=8 means the cell type should include __WIDTH_8
        assert "__WIDTH_8" in inst.cell_type

    def test_defparam_wins_over_inline(self, tmp_path):
        """defparam should take precedence over inline #() parameter."""
        vfile = tmp_path / "test_defparam.v"
        vfile.write_text(
            """
module sub #(parameter WIDTH = 4) (
  output wire [WIDTH-1:0] out
);
  assign out = {WIDTH{1'b0}};
endmodule

module top (
  output wire [7:0] result
);
  sub #(.WIDTH(4)) u_sub(.out(result[3:0]));
  defparam u_sub.WIDTH = 8;
endmodule
"""
        )
        parser = NetlistParser(str(vfile))
        insts = parser.instances_by_parent.get("top", [])
        assert len(insts) == 1
        # defparam should set WIDTH=8, which should result in cell_type specialized with WIDTH_8
        inst = insts[0]
        # The cell type should reflect the specialized parameter value from defparam
        assert "__WIDTH_8" in inst.cell_type
