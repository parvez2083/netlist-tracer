* Synthetic SPICE fixture: continuation lines across comment lines
.SUBCKT test_cont VDD VSS
X1 A B
* continuation lines below
+ C D E test_cell
.ENDS test_cont
