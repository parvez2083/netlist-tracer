// Nested 2-level generate-for loops for testing fixed-point unrolling
// Expected: 2 outer iterations × 2 inner iterations = 4 total assign expansions per initial assign
module nested_generate (
    input [3:0] in0,
    input [3:0] in1,
    output [3:0] out0,
    output [3:0] out1
);

  genvar i, j;

  generate
    for (i = 0; i < 2; i = i + 1) begin : outer
      for (j = 0; j < 2; j = j + 1) begin : inner
        // Use simple direct bit-level assigns (per Blueprint B.5)
        // No arithmetic on indices (i*2+j is out of scope)
        assign out0[i] = in0[i];   // Outer loop variable only
        assign out1[j] = in1[j];   // Inner loop variable only
      end
    end
  endgenerate

endmodule
