; ============================================================
; 8-BIT MULTIPLY (via repeated addition)
; ============================================================
; TECHNIQUE: Software multiply, countdown loop
; ------------------------------------------------------------
; This CPU has no MUL instruction. We implement multiplication
; as repeated addition: A * B = A added to itself B times.
;
; Example: 7 * 6 = 7 + 7 + 7 + 7 + 7 + 7 = 42 = 0x2A
;
; Change the LDI values in INIT to multiply different numbers.
; Note: result must fit in 8 bits (max ~15*15=225 is safe).
; Values that overflow 255 will produce a truncated result.
;
; MEMORY MAP:
;   0x100 - operand A (the value being added repeatedly)
;   0x101 - operand B (the counter, counts down to zero)
;   0x102 - running sum (accumulates each addition)
;   0x103 - final product output (watch this)
; ============================================================

INIT:
    LDI 0x07
    ST  0x100           ; A = 7
    LDI 0x06
    ST  0x101           ; B = 6
    LDI 0x00
    ST  0x102           ; sum = 0

LOOP:
    LD  0x101           ; Check B (the counter)
    JZ  DONE            ; B reached zero - done

    LD  0x102           ; sum = sum + A
    ADD 0x100
    ST  0x102

    LD  0x101           ; B = B - 1
    ADDI 0xFF
    ST  0x101

    JMP LOOP

DONE:
    LD  0x102
    ST  0x103           ; Write product to output
    HALT
