// Synthetic Verilog fixture: generate if
module verilog_generate_if #(parameter WIDTH = 4) (
  input wire [WIDTH-1:0] in,
  output wire [WIDTH-1:0] out
);

  generate
    if (WIDTH > 0) begin : pos_width
      assign out = in;
    end else begin : zero_width
      assign out = {WIDTH{1'b0}};
    end
  endgenerate

endmodule
