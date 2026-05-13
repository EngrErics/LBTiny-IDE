; ============================================================
; MEMSET - Fill a memory region with a constant value
; ============================================================
; TECHNIQUE: Counter loop with SMC write pointer
; ------------------------------------------------------------
; Fills 16 bytes of RAM starting at 0x300 with the value 0xAB.
; This is the assembly equivalent of C's memset().
;
; The write address (0x300) is advanced each iteration using
; self-modifying code: we patch the low byte of the ST
; instruction directly in program memory so each store goes
; to the next address.
;
; ST 0x300 is at address 0x00E in program memory.
; Its address operand (low byte) sits at 0x00F.
; We write an incrementing offset into 0x00F each loop.
;
; MEMORY MAP:
;   0x001 - loop counter (counts down from 16)
;   0x002 - current write offset (increments 0x00 to 0x0F)
;   0x300 - fill destination (16 bytes, watch 0x300 row)
;
; To change the fill value: edit LDI 0xAB
; To change the fill length: edit LDI 0x10
; ============================================================

INIT:
    LDI 0x10
    ST  0x001           ; counter = 16
    LDI 0x00
    ST  0x002           ; offset = 0
    ST  0x00F           ; patch ST operand: first write -> 0x300

LOOP:
    LD  0x001
    JZ  DONE

    LDI 0xAB            ; Value to fill
    ST  0x300           ; Write to current address (operand at 0x00F is patched)

    LD  0x002           ; Advance the write pointer
    ADDI 0x01
    ST  0x002
    ST  0x00F           ; Patch ST operand for next iteration

    LD  0x001           ; Decrement counter
    ADDI 0xFF
    ST  0x001

    JMP LOOP

DONE:
    HALT
