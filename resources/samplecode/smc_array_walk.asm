; ============================================================
; SMC ARRAY WALK - Read an array using a self-modifying pointer
; ============================================================
; TECHNIQUE: Self-Modifying Code (SMC) for indirect addressing
; ------------------------------------------------------------
; This CPU has NO indirect addressing mode. You cannot write
; "LD [ptr]" - there is no such instruction. Every LD must
; have a hard-coded address baked into the opcode.
;
; SOLUTION: We patch the address field of a LD instruction
; at runtime, changing where it reads from on the fly.
; This turns a fixed LD into an effective indirect load.
;
; HOW IT WORKS:
;   The instruction "LD 0x200" assembles to two bytes:
;       0x00E: 22  <- opcode (LD, page 2)
;       0x00F: 00  <- low byte of address (the part we patch)
;
;   Each loop iteration we write a new offset into address
;   0x00F, changing the LD's target: 0x200, 0x201, 0x202...
;
; SETUP: Pre-load data into 0x200..0x207 using the memory
;        viewer (set 8 bytes in the 0x200 row). The program
;        will read them out sequentially into 0x100.
;
; MEMORY MAP:
;   0x001 - loop counter (counts down from 8)
;   0x00F - SMC PATCH TARGET (operand of LD 0x200 below)
;   0x100 - current output (last byte read, watch this)
;   0x200 - source array (8 bytes, load manually)
; ============================================================

INIT:
    LDI 0x08
    ST  0x001           ; counter = 8 (array length)
    LDI 0x00
    ST  0x00F           ; patch LD operand: first read -> 0x200

LOOP:
    LD  0x001
    JZ  DONE

    LD  0x200           ; READ FROM ARRAY (0x00F is the live patch target)
    ST  0x100           ; Output the read value

    LD  0x00F           ; Advance the read pointer (increment the offset)
    ADDI 0x01
    ST  0x00F           ; Write new offset back into the LD instruction

    LD  0x001
    ADDI 0xFF
    ST  0x001           ; Decrement counter

    JMP LOOP

DONE:
    HALT
