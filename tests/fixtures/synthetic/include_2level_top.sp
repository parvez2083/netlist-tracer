.subckt TOP a b out
.include 'include_2level_mid.sp'
X1 a b net1 MID
X2 net1 out LEAF
.ends TOP
