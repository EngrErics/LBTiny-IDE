;Simple 10 iter Count Down For Loop
; each iter inverts a value from mem
start:
	LDI	0xF5
	ST	0x030
	LDI	0x09
	ADDI	0x01

loop:
	ADDI	0xFF
	ST	0x020
	LD	0x030
	XORI	0xFF	
	ST	0x030
	LD	0x020
	JZ	end
	JMP	loop

end:
	JMP	end