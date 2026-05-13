; ============================================================
; COUNT TO 0xFF
; ============================================================
; TECHNIQUE: Basic counter loop, carry flag termination
; ------------------------------------------------------------
; Counts from 0x00 up to 0xFF, writing each value to 0x100.
; When the counter wraps back past 0xFF, the carry flag fires
; and the loop ends.
;
; MEMORY MAP:
;   0x100 - current count output (watch this in memory view)
; ============================================================

INIT:
    LDI 0x00            ; Start counter at zero

LOOP:
    ST  0x100           ; Write current count to output
    ADDI 0x01           ; Increment
    JC  DONE            ; Carry set = wrapped past 0xFF, done
    JMP LOOP

DONE:
    ST  0x100           ; Store the final wrapped value (0x00)
    HALT
