// Synthetic Verilog fixture: parent module instantiating Verilog-A leaf
module verilog_a_parent (input a, output y);

  verilog_a_leaf u_leaf (.inp(a), .outp(y));

endmodule
