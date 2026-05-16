// Copyright notice: © 2024
// This module demonstrates Latin-1 encoded byte tolerance
module latin1_test (
    input clk,
    output reg ready
);

// A comment with Latin-1 byte 0x81 (ü) encoded
reg valid;

always @(posedge clk) begin
    ready <= valid;
end

endmodule
