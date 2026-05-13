; ============================================================
; INTERRUPT DEMO
; ============================================================
; TECHNIQUE: ISR setup, EI/DI, RETI, pc_save
; ------------------------------------------------------------
; Demonstrates the interrupt system. The CPU hardwires the
; ISR (Interrupt Service Routine) entry point to address 0x008.
; When an interrupt fires, the CPU automatically:
;   1. Saves the current PC to pc_save
;   2. Disables further interrupts (IE = 0)
;   3. Jumps to 0x008
;
; RETI restores the saved PC and re-enables interrupts.
;
; This program:
;   - Places a JMP MAIN at 0x000 to skip over the ISR slot
;   - Pads with NOPs so the ISR label lands exactly at 0x008
;   - ISR toggles a flag byte at 0x100 (0x00 <-> 0x01)
;   - MAIN initializes the flag, enables interrupts, then idles
;   - Use the "INT Trigger" toolbar button to fire interrupts
;     and watch 0x100 toggle in the memory viewer
;
; MEMORY MAP:
;   0x100 - interrupt flag (watch this toggle on each INT)
;   0x008 - ISR entry point (hardwired by CPU architecture)
;
; TRY IT: Step through slowly with F10, click INT Trigger,
;         observe the CPU jump to 0x008 and return.
; ============================================================

    JMP MAIN            ; 0x000: Skip over ISR vector region
    NOP                 ; 0x002: padding
    NOP                 ; 0x003: padding
    NOP                 ; 0x004: padding
    NOP                 ; 0x005: padding
    NOP                 ; 0x006: padding
    NOP                 ; 0x007: padding

ISR:                    ; MUST be at 0x008 - CPU jumps here on interrupt
    LD  0x100           ; Load current flag value
    XORI 0x01           ; Toggle bit 0
    ST  0x100           ; Save it back
    RETI                ; Restore PC, re-enable interrupts, return

MAIN:
    LDI 0x00
    ST  0x100           ; Initialize flag to 0x00
    EI                  ; Enable interrupts

IDLE:
    NOP
    JMP IDLE            ; Spin forever, waiting for interrupts
