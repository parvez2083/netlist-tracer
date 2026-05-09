// Synthetic Verilog fixture: concatenation with aliases
module concat_alias (
  input wire a,
  input wire b,
  output wire y
);

  wire [1:0] combined;
  assign combined = {a, b};
  assign y = combined[0];

endmodule
