* Synthetic SPICE fixture: tab character in continuation lines
.SUBCKT test_tab_cont A B C
X1	A	B
+	C	D
+	tab_cell
.ENDS test_tab_cont
