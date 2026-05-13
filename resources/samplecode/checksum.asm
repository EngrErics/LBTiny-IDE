; ============================================================
; XOR CHECKSUM
; ============================================================
; TECHNIQUE: Reduction loop, XOR accumulation
; ------------------------------------------------------------
; XORs together a block of bytes from memory to produce a
; single checksum byte. This is a classic data integrity
; technique - XORing all bytes means a single-bit flip in
; any byte will change the checksum.
;
; This demo XORs the bytes at 0x200..0x20F (16 bytes).
; Pre-load values there in the memory watch window to see
; the checksum update.
;
; MEMORY MAP:
;   0x001 - loop counter (counts down from 16)
;   0x002 - running XOR accumulator
;   0x100 - final checksum output
;   0x200 - input data block (16 bytes, load manually)
;
; NOTE: This version XORs a fixed block at 0x200..0x20F.
;       To XOR a different block, change the LDI 0x10 count
;       and update the LD 0x200 address via the SMC technique
;       shown in smc_array_walk.asm.
; ============================================================

INIT:
    LDI 0x10            ; Loop count = 16 bytes
    ST  0x001
    LDI 0x00            ; Clear accumulator
    ST  0x002

LOOP:
    LD  0x001           ; Check counter
    JZ  DONE            ; Counter hit zero - we're done

    LD  0x002           ; Load running XOR result
    XOR 0x200           ; XOR with next byte
    ST  0x002           ; Save result

    LD  0x001           ; Decrement counter
    ADDI 0xFF           ; (adding 0xFF is the same as -1)
    ST  0x001

    JMP LOOP

DONE:
    LD  0x002
    ST  0x100           ; Write final checksum to output
    HALT
