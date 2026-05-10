* Synthetic SPICE fixture: K (coupled inductor) element
.SUBCKT test_coupling VDD VSS
* Define two inductors
L1 A B 1u
L2 C D 1u

* Define coupling between them
K1 L1 L2 0.99

.ENDS test_coupling
