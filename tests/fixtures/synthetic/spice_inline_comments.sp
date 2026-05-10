* Synthetic SPICE fixture: inline comment stripping
.SUBCKT test_inline VDD VSS
* This is a full-line comment
X1 A B C test_cell ; this is an inline comment
X2 D E F test_cell $ another inline style
.ENDS test_inline
