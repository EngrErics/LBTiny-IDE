; ============================================================
; FIBONACCI SEQUENCE
; ============================================================
; TECHNIQUE: Two-variable accumulation, carry flag termination
; ------------------------------------------------------------
; Computes the Fibonacci sequence, keeping the two most recent
; terms in memory and computing the next by addition.
; Halts when the next term would overflow 8 bits (carry set).
;
; Sequence: 0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233
; F(14) = 377 overflows - carry fires and we halt.
;
; MEMORY MAP:
;   0x100 - A: the previous term
;   0x101 - B: the current term  (watch these two update)
;   0x102 - scratch: temp storage during the swap
; ============================================================

INIT:
    LDI 0x00
    ST  0x100           ; A = 0  (F0)
    LDI 0x01
    ST  0x101           ; B = 1  (F1)

LOOP:
    LD  0x100           ; ACC = A
    ADD 0x101           ; ACC = A + B
    JC  DONE            ; Overflow - result won't fit, halt

    ST  0x102           ; temp = A + B

    LD  0x101           ; new A = old B
    ST  0x100

    LD  0x102           ; new B = A + B
    ST  0x101

    JMP LOOP

DONE:
    HALT
