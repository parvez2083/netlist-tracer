* Synthetic SPICE fixture: basic netlist
.SUBCKT nand2 Y A B VDD VSS
M1 Y A VDD VDD pmos W=2u L=1u
M2 Y B VDD VDD pmos W=2u L=1u
M3 Y A 1 VSS nmos W=1u L=1u
M4 1 B VSS VSS nmos W=1u L=1u
.ENDS nand2

.SUBCKT top_spice VDD VSS A B Y
X1 Y A B VDD VSS nand2
.ENDS top_spice
