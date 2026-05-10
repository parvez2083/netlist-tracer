* Synthetic SPICE fixture: .global directive
.GLOBAL VDD VSS GND
.SUBCKT test_global IN OUT
X1 IN OUT test_sub
.ENDS test_global

.SUBCKT test_sub A B
* Some internal content
.ENDS test_sub
