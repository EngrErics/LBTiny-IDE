; ============================================================
; SMC POINTER - Bidirectional indirect read/write
; ============================================================
; TECHNIQUE: Self-Modifying Code (SMC), dual pointer patching
; ------------------------------------------------------------
; Extends the array walk concept to a full read-modify-write
; pointer: reads 8 bytes from one region, inverts each byte
; (bitwise NOT), and writes the results to another region.
;
; TWO patches are performed each iteration:
;   1. The LD instruction's address is patched (read pointer)
;   2. The ST instruction's address is patched (write pointer)
;
; This is the closest thing to a pointer dereference this CPU
; can do without hardware indirect addressing support.
;
; PATCH TARGETS in program memory:
;   LD 0x200 is at 0x00E  -> operand (low byte) at 0x00F
;   ST 0x300 is at 0x010  -> operand (low byte) at 0x011
;
; SETUP: Pre-load 8 bytes into 0x200..0x207.
;        After running, 0x300..0x307 will hold their inverses.
;
; MEMORY MAP:
;   0x001 - loop counter
;   0x002 - current offset (0..7, used for both pointers)
;   0x00F - SMC PATCH: LD read address low byte
;   0x011 - SMC PATCH: ST write address low byte
;   0x200 - source array (load 8 bytes here)
;   0x300 - destination array (inverted bytes appear here)
; ============================================================

INIT:
    LDI 0x08
    ST  0x001           ; counter = 8
    LDI 0x00
    ST  0x002           ; offset = 0
    ST  0x00F           ; patch LD: first read  -> 0x200
    ST  0x011           ; patch ST: first write -> 0x300

LOOP:
    LD  0x001
    JZ  DONE

    LD  0x200           ; Read from source array  (0x00F is patched)
    INV                 ; Bitwise NOT of ACC
    ST  0x300           ; Write to dest array     (0x011 is patched)

    LD  0x002           ; Advance both pointers
    ADDI 0x01
    ST  0x002
    ST  0x00F           ; Patch LD source address
    ST  0x011           ; Patch ST dest address

    LD  0x001
    ADDI 0xFF
    ST  0x001           ; Decrement counter

    JMP LOOP

DONE:
    HALT
