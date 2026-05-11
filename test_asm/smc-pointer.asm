; ==========================================
; RAM WAVE ANIMATION via SELF-MODIFYING CODE
; ==========================================

INIT:
    LDI 0xFF      ; Start with the 'Fill' color
    ST COLOR      
    
START:
    LDI 0x00      ; Reset our memory offset pointer to 0
    ST PTR_LOW    

LOOP:
    LD COLOR      ; Load the current color (0xFF or 0x00)
    
WRITE_INST:
    ; This instruction sits at address 0x00A and 0x00B
    ; The second byte (0x00B) is the lower address nibbles.
    ; WE WILL OVERWRITE ADDRESS 0x00B DYNAMICALLY!
    ST 0xC00      

    ; --- Increment the pointer ---
    LD PTR_LOW    
    ADDI 0x01     ; Add 1. If it wraps from 0xFF to 0x00, Z flag becomes 1
    ST PTR_LOW    
    
    ; --- The SMC Magic ---
    ; Store the incremented pointer directly into the 
    ; operand byte of the ST instruction above!
    ST 0x00B      

    ; --- Check if we finished the page ---
    JZ FLIP       ; If ADDI wrapped to 0, the Z flag is set. Jump to flip!
    JMP LOOP      ; Otherwise, keep sweeping

FLIP:
    LD COLOR      ; Load current color
    INV           ; Invert it! (0xFF becomes 0x00, 0x00 becomes 0xFF)
    ST COLOR      ; Save new color
    JMP START     ; Restart the sweep

; --- Variables ---
COLOR:
    NOP           ; Sits at 0x01F
PTR_LOW:
    NOP           ; Sits at 0x020