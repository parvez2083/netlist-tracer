// Synthetic Verilog fixture: defparam parameter override
module verilog_defparam (
  input wire clk, reset,
  output wire [7:0] count
);

  // Instance with default parameter
  counter #(.WIDTH(4)) u_counter (
    .clk(clk),
    .reset(reset),
    .count(count)
  );

  // Override the WIDTH parameter using defparam
  defparam u_counter.WIDTH = 8;

endmodule

module counter #(parameter WIDTH = 4) (
  input wire clk, reset,
  output wire [WIDTH-1:0] count
);

  reg [WIDTH-1:0] count_r;
  assign count = count_r;

  always @(posedge clk or negedge reset)
    if (!reset)
      count_r <= {WIDTH{1'b0}};
    else
      count_r <= count_r + 1'b1;

endmodule
