// Synthetic Verilog fixture: built-in gate primitives
module verilog_gate_primitives (
  input wire a, b,
  output wire y_and, y_or, y_nand, y_nor, y_xor, y_xnor,
  output wire y_buf, y_not
);

  and     u_and     (y_and,  a, b);
  or      u_or      (y_or,   a, b);
  nand    u_nand    (y_nand, a, b);
  nor     u_nor     (y_nor,  a, b);
  xor     u_xor     (y_xor,  a, b);
  xnor    u_xnor    (y_xnor, a, b);

  buf     u_buf     (y_buf, a);
  not     u_not     (y_not, a);

endmodule
