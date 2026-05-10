* Synthetic SPICE fixture: mixed case keywords and identifiers
.subckt MixedCase_Cell INPUT OUTPUT VDD VSS
x1 INPUT OUTPUT Sub_Component
x2 VSS VDD Another_Comp
.ends MixedCase_Cell

.SUBCKT Sub_Component A B
.ENDS Sub_Component

.subckt Another_Comp P Q
.ends Another_Comp
