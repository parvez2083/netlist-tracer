// SystemVerilog interface with modports
interface bus_if (input logic clk);
    logic [7:0] data;
    logic valid;
    logic ready;

    modport master (
        output data, valid,
        input ready
    );

    modport slave (
        input data, valid,
        output ready
    );

endinterface
