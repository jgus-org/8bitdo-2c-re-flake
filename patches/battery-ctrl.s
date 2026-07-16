/* Controller: relay a raw 0-100 battery level over 2.4GHz for the host's unscaled % readout. Writes the battery byte (RAM 0x842e04) into spare button-word bits: low 5 -> word 19-23, high 2 -> word 29-30. L4/R4/Square (word 25-27, scanned by stock firmware) ride through r4 untouched. Replaces the scanner's finalize-store (*button_word = r4). */
.section .tramp, "ax"
	tjl shim

.section .shim, "ax"
shim:
	tpush {lr}
	tloadr r0, batt_ptr
	tloadrb r0, [r0, #0]
	tmovs r1, #0x1f
	tand r1, r0
	tshftl r1, r1, #0x13
	tor r4, r1
	tshftr r0, r0, #5
	tmovs r1, #0x03
	tand r1, r0
	tshftl r1, r1, #0x1d
	tor r4, r1
	tloadr r0, bw_ptr
	tstorer r4, [r0, #0]
	tpop {pc}
	.balign 4
batt_ptr:	.word battery
bw_ptr:	.word button_word
