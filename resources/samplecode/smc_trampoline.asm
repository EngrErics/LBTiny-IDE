; ============================================================
; SMC TRAMPOLINE - Computed indirect jump / dispatch table
; ============================================================
; TECHNIQUE: Self-Modifying Code for indirect branching
; ------------------------------------------------------------
; This CPU has no indirect jump instruction. JMP always takes
; a hard-coded address. There is no "JMP [reg]" or "JMP [mem]".
;
; PROBLEM: How do you jump to an address you only know at
; runtime - like a function pointer or a switch statement?
;
; SOLUTION: The Trampoline pattern.
;   1. Build a JMP instruction in RAM at a known address (0x050)
;   2. Patch the destination field of that JMP with the target
;   3. Execute the JMP from 0x050 - it bounces to the target
;
; The JMP opcode for page 0 targets is 0x80 (MSB of opcode byte).
; The destination low byte is stored at 0x051.
; We write 0x80 to 0x050, then the target address to 0x051,
; then jump to 0x050 - the CPU executes our freshly-built JMP.
;
; DISPATCH TABLE (stored at 0x0F0..0x0F3):
;   A lookup table maps index (0-3) to the low byte of each
;   target address. We patch the LD instruction that reads
;   the table (at 0x020, operand at 0x021) to index into it:
;       index=0 -> read 0x0F0 -> get 0x26 -> JMP 0x026 (TARGET_0)
;       index=1 -> read 0x0F1 -> get 0x2C -> JMP 0x02C (TARGET_1)
;       ... and so on.
;
; The program loops forever, cycling through all 4 targets.
; Watch 0x100 in the memory viewer - it cycles 0xAA,0xBB,0xCC,0xDD.
;
; MEMORY MAP:
;   0x001      - loop counter (cycles 0,1,2,3,0,1,2,3...)
;   0x01B      - SMC PATCH: LD table read address low byte
;   0x050..051 - TRAMPOLINE: live JMP instruction built at runtime
;   0x0F0..0F3 - DISPATCH TABLE: target address low bytes
;   0x100      - output (cycles through 0xAA, 0xBB, 0xCC, 0xDD)
; ============================================================

INIT:
    LDI 0x00
    ST  0x001           ; counter = 0
    LDI 0x80
    ST  0x050           ; Trampoline opcode: JMP page 0

    ; Dispatch table: low bytes of TARGET_0..3
    ; (These were computed from the assembled addresses below)
    LDI 0x26
    ST  0x0F0           ; table[0] = low byte of TARGET_0
    LDI 0x2C
    ST  0x0F1           ; table[1] = low byte of TARGET_1
    LDI 0x32
    ST  0x0F2           ; table[2] = low byte of TARGET_2
    LDI 0x38
    ST  0x0F3           ; table[3] = low byte of TARGET_3

COMPUTE:
    LD  0x001           ; ACC = counter
    ANDI 0x03           ; Mask to 0..3 (wraps every 4)
    ADDI 0xF0           ; ACC = 0xF0 + index (address of table entry)
    ST  0x01B           ; PATCH: write that address into the LD below

    LD  0x0F0           ; Read table[index] (0x01B is the live patch target)
    ST  0x051           ; Write target low byte into trampoline

    JMP 0x050           ; Execute the trampoline - bounces to selected target

; ----- DISPATCH TARGETS -----
; Each target does its work, then falls through to NEXT.
; All targets must be on page 0 (addresses 0x000..0x0FF).

TARGET_0:               ; @ 0x026
    LDI 0xAA
    ST  0x100
    JMP NEXT

TARGET_1:               ; @ 0x02C
    LDI 0xBB
    ST  0x100
    JMP NEXT

TARGET_2:               ; @ 0x032
    LDI 0xCC
    ST  0x100
    JMP NEXT

TARGET_3:               ; @ 0x038
    LDI 0xDD
    ST  0x100
    JMP NEXT

NEXT:
    LD  0x001
    ADDI 0x01
    ST  0x001           ; Increment counter (wraps naturally, ANDI clips it)
    JMP COMPUTE         ; Loop forever
