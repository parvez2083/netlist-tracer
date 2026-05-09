// Synthetic Verilog fixture: generate loop
module generate_loop (
  input wire [3:0] in,
  output wire [3:0] out
);

  genvar i;
  generate
    for (i = 0; i < 4; i = i + 1) begin : loop
      assign out[i] = in[i];
    end
  endgenerate

endmodule
