# CPU & ASSEMBLER CLASSES
#-----------------------------------------------------------------------

class CPU:
    def __init__(self):
        self.mem = bytearray(4096)
        self.breakpoints = set()
        self.skip_breakpoint = False
        self.reset()

    def reset(self):
        self.pc, self.acc, self.c, self.z, self.ie, self.in_isr, self.pc_save, self.cycles = 0, 0, 0, 0, 0, 0, 0, 0
        self.halted = False
        self.skip_breakpoint = False

    def step(self):
        if self.halted: return
        
        op_byte = self.mem[self.pc]
        primary_op = (op_byte >> 4) & 0xF
        sub_op = op_byte & 0xF
        
        # Implied Instructions
        if primary_op == 0x0:
            self.pc = (self.pc + 1) & 0xFFF
            if sub_op == 0x00: pass 
            elif sub_op == 0x01: 
                self.c = self.acc & 1
                self.acc >>= 1
            elif sub_op == 0x02: 
                res = self.acc << 1
                self.c = (res >> 8) & 1
                self.acc = res & 0xFF
            elif sub_op == 0x03: self.ie = 1 
            elif sub_op == 0x04: self.ie = 0 
            elif sub_op == 0x05: 
                self.pc = self.pc_save
                self.in_isr = 0
                self.ie = 1
            elif sub_op == 0x06: self.halted = True 
            elif sub_op == 0x07: 
                self.acc = (~self.acc) & 0xFF
            self.cycles += 3
            self.z = 1 if self.acc == 0 else 0

        # Immediate Instructions
        elif primary_op == 0x1:
            imm = self.mem[(self.pc + 1) & 0xFFF]
            self.pc = (self.pc + 2) & 0xFFF
            if sub_op == 0x0: self.acc = imm 
            elif sub_op == 0x1: 
                res = self.acc + imm
                self.c = (res >> 8) & 1
                self.acc = res & 0xFF
            elif sub_op == 0x2: self.acc &= imm; self.c = 0 
            elif sub_op == 0x3: self.acc |= imm; self.c = 0 
            elif sub_op == 0x4: self.acc ^= imm; self.c = 0 
            self.cycles += 5
            self.z = 1 if self.acc == 0 else 0

        # Address Instructions
        else:
            addr12 = (sub_op << 8) | self.mem[(self.pc + 1) & 0xFFF]
            next_pc = (self.pc + 2) & 0xFFF
            
            if primary_op == 0x2: self.acc = self.mem[addr12] 
            elif primary_op == 0x3: self.mem[addr12] = self.acc 
            elif primary_op == 0x4: 
                res = self.acc + self.mem[addr12]
                self.c = (res >> 8) & 1
                self.acc = res & 0xFF
            elif primary_op == 0x5: self.acc &= self.mem[addr12]; self.c = 0 
            elif primary_op == 0x6: self.acc |= self.mem[addr12]; self.c = 0 
            elif primary_op == 0x7: self.acc ^= self.mem[addr12]; self.c = 0 
            elif primary_op == 0x8: next_pc = addr12 
            elif primary_op == 0x9: 
                if self.z: next_pc = addr12
            elif primary_op == 0xA: 
                if not self.z: next_pc = addr12
            elif primary_op == 0xB: 
                if self.c: next_pc = addr12
            elif primary_op == 0xC: 
                if not self.c: next_pc = addr12
            
            self.pc = next_pc
            self.cycles += 7
            self.z = 1 if self.acc == 0 else 0

    def trigger_interrupt(self):
        if self.ie and not self.in_isr:
            self.pc_save = self.pc
            self.in_isr = 1
            self.ie = 0
            self.pc = 0x008
            self.halted = False

class Assembler:
    IMPLIED = {'NOP':0x00, 'SHR':0x01, 'SHL':0x02, 'EI':0x03, 'DI':0x04, 'RETI':0x05, 'HALT':0x06, 'INV':0x07}
    IMMEDIATE = {'LDI':0x10, 'ADDI':0x11, 'ANDI':0x12, 'ORI':0x13, 'XORI':0x14}
    ADDRESS = {'LD':0x2, 'ST':0x3, 'ADD':0x4, 'AND':0x5, 'OR':0x6, 'XOR':0x7, 'JMP':0x8, 'JZ':0x9, 'JNZ':0xA, 'JC':0xB, 'JNC':0xC}

    def assemble(self, source):
        bin_data, labels, pc_map, addr_map, addr = bytearray(4096), {}, {}, {}, 0
        lines = source.split('\n')
        
        for line in lines:
            line = line.split(';')[0].strip()
            if not line: continue
            if ':' in line: 
                label, line = line.split(':', 1)
                labels[label.strip()] = addr
                line = line.strip()
            if not line: continue
            mne = line.split()[0].upper()
            addr += 1 if mne in self.IMPLIED else 2

        addr = 0
        for i, line in enumerate(lines):
            line = line.split(';')[0].strip()
            if ':' in line: line = line.split(':', 1)[1].strip()
            if not line: continue
            
            pc_map[addr] = i
            addr_map[i] = addr 
            parts = line.replace(',', ' ').split()
            mne = parts[0].upper()

            if mne in self.IMPLIED:
                bin_data[addr] = self.IMPLIED[mne]
                addr += 1
            elif mne in self.IMMEDIATE:
                bin_data[addr] = self.IMMEDIATE[mne]
                val = int(parts[1], 0) & 0xFF
                bin_data[addr+1] = val
                addr += 2
            elif mne in self.ADDRESS:
                op = self.ADDRESS[mne]
                target = labels[parts[1]] if parts[1] in labels else int(parts[1], 0)
                bin_data[addr] = (op << 4) | ((target >> 8) & 0xF)
                bin_data[addr+1] = target & 0xFF
                addr += 2
        return bin_data, pc_map, addr_map