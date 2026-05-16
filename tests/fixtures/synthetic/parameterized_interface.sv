// SystemVerilog interface with parameters
interface bus_if #(parameter WIDTH = 4) (input logic clk);
    logic [WIDTH-1:0] data;
endinterface
