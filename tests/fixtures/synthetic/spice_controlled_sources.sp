* Synthetic SPICE fixture: B/E/F/G/H controlled source elements
.SUBCKT test_sources VDD VSS IN OUT
* Behavioral source (B element)
B1 OUT VSS V=V(IN)*2

* Voltage-controlled voltage source (E element)
E1 N1 VSS IN VSS 1.5

* Voltage-controlled current source (G element)
G1 N2 VSS IN VSS 0.001

* Current-controlled current source (F element, needs V control)
F1 N3 VSS VSRC 1.0

* Current-controlled voltage source (H element, needs V control)
H1 N4 VSS VSRC 1000

* Dummy voltage source for control (not a real element, just for testing)
VSRC VSS VSS DC 0
.ENDS test_sources
