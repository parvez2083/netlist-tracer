* Synthetic SPICE flat-deck testbench fixture
.param vdd=0.85
Xdut_main in1 out1 vdd vss mac6_top
Xldo_aux  in2 out1 vdd vss ldo_aux
Vsupply vdd 0 0.85
.subckt mac6_top a b c d
M1 c a b d nmos W=1u L=1u
.ends mac6_top
.subckt ldo_aux a b c d
M1 c a b d nmos W=1u L=1u
.ends ldo_aux
.end
