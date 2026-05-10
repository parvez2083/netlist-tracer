// Synthetic Verilog fixture: generate case
module verilog_generate_case #(parameter MODE = 2) (
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
      3: begin : mode_3
        assign out = {in[1:0], in[3:2]};
      end
      default: begin : mode_default
        assign out = 4'b0000;
      end
    endcase
  endgenerate

endmodule
