// Synthetic Verilog fixture: parameterized module specialization
module param_specialize #(
  parameter WIDTH = 8
) (
  input wire [WIDTH-1:0] a,
  input wire [WIDTH-1:0] b,
  output wire [WIDTH-1:0] c
);

  assign c = a & b;

endmodule

module top_param (
  input wire [15:0] x,
  input wire [15:0] y,
  output wire [15:0] z
);

  param_specialize #(.WIDTH(16)) ps (
    .a(x),
    .b(y),
    .c(z)
  );

endmodule
