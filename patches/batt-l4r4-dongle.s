/* Dongle: relay the 7-bit battery into report[18] and the L4/R4/Square paddles into report[19]. report[18] = (RF[5]>>3) | (RF[6] & 0x60) = battery low-5 (word 19-23) + high-2 (word 29-30). report[19] = RF[6] & 0x0e = R4 (word 25) | L4 (word 26) | Square (word 27). r4 = RF frame, r6 = XInput wire. Hooks the report[19]=0x10 store (0x74be); the report[18]=0 store (0x74ba) runs first, so the shim overwrites report[18]. Rides the pad before img 0x8400. */
.section .tramp, "ax"
	tjl shim

.section .shim, "ax"
shim:
	tpush {lr}
	tloadrb r3, [r4, #5]
	tshftr r3, r3, #3
	tloadrb r2, [r4, #6]
	tmovs r1, #0x60
	tand r1, r2
	tor r3, r1
	tstorerb r3, [r6, #17]
	tmovs r1, #0x0e
	tand r2, r1
	tstorerb r2, [r6, #18]
	tpop {pc}
