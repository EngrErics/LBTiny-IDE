; ============================================================
; BIT COUNT (POPCOUNT)
; ============================================================
; TECHNIQUE: Shift-and-test loop, carry flag as bit probe
; ------------------------------------------------------------
; Counts the number of 1-bits in a byte. This is called
; "population count" or popcount. Classic use case: error
; correction codes, Hamming weight, compression.
;
; Algorithm: shift the byte right 8 times. Each SHR moves
; the lowest bit into the carry flag. If carry is set, that
; bit was a 1 - increment our count.
;
; Example: 0xB7 = 1011 0111 = six 1-bits -> result = 6
; Change the LDI 0xB7 to test any byte you like.
;
; MEMORY MAP:
;   0x100 - input byte (gets shifted down to zero)
;   0x101 - bit count accumulator (result ends up here)
;   0x102 - loop counter (8 iterations)
;   0x103 - final popcount output (watch this)
; ============================================================

INIT:
    LDI 0xB7
    ST  0x100           ; Input byte = 0xB7 (1011 0111)
    LDI 0x00
    ST  0x101           ; count = 0
    LDI 0x08
    ST  0x102           ; loop 8 times (one per bit)

LOOP:
    LD  0x102           ; Check iterations remaining
    JZ  DONE

    LD  0x100           ; Load byte and shift right
    SHR                 ; LSB moves into carry flag
    ST  0x100           ; Save shifted byte

    JNC SKIP            ; Carry clear = that bit was 0, skip

    LD  0x101           ; Carry set = bit was 1, increment count
    ADDI 0x01
    ST  0x101

SKIP:
    LD  0x102           ; Decrement iteration counter
    ADDI 0xFF
    ST  0x102

    JMP LOOP

DONE:
    LD  0x101
    ST  0x103           ; Write popcount to output
    HALT
