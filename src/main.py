import sys
import os
import PySide6
from PySide6.QtCore import Qt, QTimer, QRect, QSize, QObject, QEvent, QSettings, Signal, QPoint
from PySide6.QtGui import (QColor, QFont, QAction, QTextFormat, QTextCursor, 
                           QPalette, QPainter)
from PySide6.QtWidgets import (QApplication, QMainWindow, QPlainTextEdit, 
                               QTableWidget, QTableWidgetItem, QVBoxLayout, 
                               QHBoxLayout, QWidget, QToolBar, QSplitter, 
                               QHeaderView, QMessageBox, QLabel, QTextEdit,
                               QFileDialog, QAbstractButton, QLineEdit, 
                               QPushButton)

# Corner Button Event Filter
class CornerPainter(QObject):
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Paint:
            painter = QPainter(obj)
            painter.fillRect(obj.rect(), QColor(49, 54, 59)) 
            painter.setPen(QColor(252, 252, 252))
            font = painter.font()
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(obj.rect(), Qt.AlignCenter, "Addr")
            painter.end()
            return True 
        return False

# Line Number Widget
class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.codeEditor = editor

    def sizeHint(self):
        return QSize(self.codeEditor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event):
        self.codeEditor.lineNumberAreaPaintEvent(event)

    def mousePressEvent(self, event):
        # Pass the raw click coordinates back to the parent editor
        self.codeEditor.handle_gutter_click(event.position().toPoint())

class CodeEditor(QPlainTextEdit):
    # Custom signal to securely notify the MainWindow of a click
    breakpoint_toggled = Signal(int)

    def __init__(self):
        super().__init__()
        self.setFont(QFont("Monospace", 11))
        self.lineNumberArea = LineNumberArea(self)

        self.blockCountChanged.connect(self.updateLineNumberAreaWidth)
        self.updateRequest.connect(self.updateLineNumberArea)
        self.updateLineNumberAreaWidth(0)

    def handle_gutter_click(self, pos):
        # Native Qt translation: Which text block is at this Y coordinate?
        cursor = self.cursorForPosition(QPoint(0, pos.y()))
        block = cursor.block()
        
        # Verify the click didn't happen in the empty space below the file
        top = self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        bottom = top + self.blockBoundingRect(block).height()
        
        if top <= pos.y() <= bottom:
            # Emit the line number (0-indexed)
            self.breakpoint_toggled.emit(block.blockNumber())

    def lineNumberAreaWidth(self):
        digits = 1
        max_v = max(1, self.blockCount())
        while max_v >= 10:
            max_v /= 10
            digits += 1
        # Padded slightly more to accommodate the red circle
        space = 28 + self.fontMetrics().horizontalAdvance('9') * digits
        return space

    def updateLineNumberAreaWidth(self, _):
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def updateLineNumberArea(self, rect, dy):
        if dy:
            self.lineNumberArea.scroll(0, dy)
        else:
            self.lineNumberArea.update(0, rect.y(), self.lineNumberArea.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.updateLineNumberAreaWidth(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self.lineNumberArea.setGeometry(QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height()))

    def lineNumberAreaPaintEvent(self, event):
        painter = QPainter(self.lineNumberArea)
        painter.fillRect(event.rect(), QColor("#222"))

        main_win = self.window()
        breakpoints = getattr(main_win, "breakpoints", set())
        addr_map = getattr(main_win, "addr_map", {})

        block = self.firstVisibleBlock()
        blockNumber = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                
                addr = addr_map.get(blockNumber)
                has_bp = addr in breakpoints if addr is not None else False

                if has_bp:
                    painter.setRenderHint(QPainter.Antialiasing)
                    painter.setBrush(QColor(200, 40, 40)) # Breakpoint Red
                    painter.setPen(Qt.NoPen)
                    
                    r = self.fontMetrics().height() - 4
                    painter.drawEllipse(self.lineNumberArea.width() - r - 6, top + 2, r, r)

                number = str(blockNumber + 1)
                painter.setPen(QColor("#FFF") if has_bp else QColor("#888"))
                painter.drawText(0, top, self.lineNumberArea.width() - 5, self.fontMetrics().height(),
                                 Qt.AlignRight, number)

            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            blockNumber += 1


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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cpu, self.assembler, self.pc_map, self.addr_map = CPU(), Assembler(), {}, {}
        self.breakpoints = set()
        self.current_file = None  
        
        self.settings = QSettings("BeachCore", "IDE")
        saved_watches = self.settings.value("watched_bases", [])
        self.watched_bases = [int(w) for w in saved_watches] if saved_watches else []
        
        saved_bps = self.settings.value("breakpoints", [])
        self.breakpoints = {int(b, 16) for b in saved_bps} if saved_bps else set()

        self.timer = QTimer(); self.timer.timeout.connect(self.do_timer_step)
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("BeachCore IDE"); self.resize(1200, 800)
        
        self.editor = CodeEditor()
        # Wire the new signal directly to the toggle function
        self.editor.breakpoint_toggled.connect(self.toggle_breakpoint)
        
        self.reg_view = QTableWidget(9, 2)
        self.reg_view.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.reg_view.verticalHeader().hide()
        self.reg_view.horizontalHeader().hide()

        header_labels = [f"{i:02X}" for i in range(16)]

        self.watch_view = QTableWidget(0, 16)
        self.watch_view.horizontalHeader().setMinimumSectionSize(10)
        self.watch_view.horizontalHeader().setDefaultSectionSize(25)
        self.watch_view.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.watch_view.verticalHeader().setFixedWidth(40)
        self.watch_view.setHorizontalHeaderLabels(header_labels)
        
        self.watch_corner_painter = CornerPainter(self)
        watch_corner = self.watch_view.findChild(QAbstractButton)
        if watch_corner:
            watch_corner.installEventFilter(self.watch_corner_painter)

        self.mem_view = QTableWidget(16, 16)
        self.mem_view.horizontalHeader().setMinimumSectionSize(10)
        self.mem_view.horizontalHeader().setDefaultSectionSize(25)
        self.mem_view.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.mem_view.verticalHeader().setFixedWidth(40)
        self.mem_view.setHorizontalHeaderLabels(header_labels)

        self.mem_corner_painter = CornerPainter(self)
        mem_corner = self.mem_view.findChild(QAbstractButton)
        if mem_corner:
            mem_corner.installEventFilter(self.mem_corner_painter)

        central = QWidget()
        layout = QHBoxLayout(central)
        
        main_splitter = QSplitter(Qt.Horizontal)
        right_splitter = QSplitter(Qt.Vertical)

        reg_widget = QWidget(); reg_layout = QVBoxLayout(reg_widget)
        reg_layout.setContentsMargins(0, 0, 0, 0)
        reg_layout.addWidget(QLabel("<b>Registers</b>")); reg_layout.addWidget(self.reg_view)
        right_splitter.addWidget(reg_widget)

        watch_widget = QWidget(); watch_layout = QVBoxLayout(watch_widget)
        watch_layout.setContentsMargins(0, 0, 0, 0)
        watch_layout.addWidget(QLabel("<b>Watch Memory</b>"))
        
        watch_controls = QHBoxLayout()
        self.watch_input = QLineEdit()
        self.watch_input.setPlaceholderText("e.g. 0C0, 0F0-0FF")
        self.watch_input.returnPressed.connect(self.do_add_watch)
        
        btn_add = QPushButton("Add")
        btn_add.clicked.connect(self.do_add_watch)
        btn_clear = QPushButton("Clear")
        btn_clear.clicked.connect(self.do_clear_watch)
        
        watch_controls.addWidget(self.watch_input)
        watch_controls.addWidget(btn_add)
        watch_controls.addWidget(btn_clear)
        
        watch_layout.addLayout(watch_controls)
        watch_layout.addWidget(self.watch_view)
        right_splitter.addWidget(watch_widget)

        mem_widget = QWidget(); mem_layout = QVBoxLayout(mem_widget)
        mem_layout.setContentsMargins(0, 0, 0, 0)
        mem_layout.addWidget(QLabel("<b>Program Memory</b>")); mem_layout.addWidget(self.mem_view)
        right_splitter.addWidget(mem_widget)

        right_splitter.setSizes([200, 300, 300])
        main_splitter.addWidget(self.editor)
        main_splitter.addWidget(right_splitter)
        main_splitter.setSizes([700, 500])
        
        layout.addWidget(main_splitter)
        self.setCentralWidget(central)

        file_menu = self.menuBar().addMenu("&File")
        file_actions = [
            ("New", "Ctrl+N", self.do_new),
            ("Open", "Ctrl+O", self.do_open),
            ("Save", "Ctrl+S", self.do_save),
            ("Save As", "Ctrl+Shift+S", self.do_save_as)
        ]
        for text, shortcut, slot in file_actions:
            act = QAction(text, self)
            act.setShortcut(shortcut)
            act.triggered.connect(slot)
            file_menu.addAction(act)
        
        sim_menu = self.menuBar().addMenu("&Simulation")
        speeds = [
            ("1.0 s/instr (Crawl)", 1000),
            ("0.5 s/instr (Slow)", 500),
            ("0.05 s/instr (Default)", 50),
            ("0.01 s/instr (Fast)", 10),
            ("0.001 s/instr (Ultra)", 1)
        ]
        self.speed_actions = []
        for text, ms in speeds:
            act = QAction(text, self, checkable=True)
            act.triggered.connect(lambda checked, m=ms, a=act: self.set_sim_speed(m, a))
            sim_menu.addAction(act)
            self.speed_actions.append(act)
            if ms == 50:
                act.setChecked(True)
                self.current_interval = 50

        t = self.addToolBar("Controls")
        control_actions = [
            ("Assemble (F7)", "F7", self.do_assemble),
            ("Step (F10)", "F10", self.do_step),
            ("Run (F5)", "F5", self.do_run),
            ("Stop (Esc)", "Esc", self.timer.stop),
            ("Reset (Ctrl+R)", "Ctrl+R", self.do_reset)
        ]
        for text, shortcut, slot in control_actions:
            act = QAction(text, self)
            act.setShortcut(shortcut)
            act.triggered.connect(slot)
            t.addAction(act)
        
        t.addAction(QAction("INT Trigger", self, triggered=self.cpu.trigger_interrupt))

        self.setup_watch_grid()
        self.update_ui()

        geometry = self.settings.value("geometry")
        if geometry: self.restoreGeometry(geometry)
        main_state = self.settings.value("main_splitter_state")
        if main_state: main_splitter.restoreState(main_state)
        right_state = self.settings.value("right_splitter_state")
        if right_state: right_splitter.restoreState(right_state)

        self.main_splitter = main_splitter
        self.right_splitter = right_splitter

    def set_sim_speed(self, ms, action):
        for act in self.speed_actions: act.setChecked(False)
        action.setChecked(True)
        self.current_interval = ms
        if self.timer.isActive(): self.timer.start(self.current_interval)

    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("main_splitter_state", self.main_splitter.saveState())
        self.settings.setValue("right_splitter_state", self.right_splitter.saveState())
        self.settings.setValue("breakpoints", [f"{b:03X}" for b in self.breakpoints])
        super().closeEvent(event)        

    # --- BREAKPOINT LOGIC ---
    def toggle_breakpoint(self, line_number):
        if line_number in self.addr_map:
            addr = self.addr_map[line_number]
            if addr in self.breakpoints:
                self.breakpoints.remove(addr)
                self.statusBar().showMessage(f"Breakpoint removed from 0x{addr:03X}", 2000)
            else:
                self.breakpoints.add(addr)
                self.statusBar().showMessage(f"Breakpoint added at 0x{addr:03X}", 2000)
            self.editor.lineNumberArea.update()
        else:
            self.statusBar().showMessage("Cannot set breakpoint: Line does not map to a memory address (Assemble first!)", 4000)

    # --- WATCH WINDOW LOGIC ---
    def do_add_watch(self):
        text = self.watch_input.text().strip()
        if not text: return
        new_bases = set(self.watched_bases)
        try:
            tokens = [t.strip() for t in text.split(',')]
            for token in tokens:
                if '-' in token:
                    start_str, end_str = token.split('-')
                    start, end = int(start_str, 16) & 0xFF0, int(end_str, 16) & 0xFF0
                    if start > end: start, end = end, start
                    for addr in range(start, end + 16, 16): new_bases.add(addr)
                else:
                    new_bases.add(int(token, 16) & 0xFF0)
            self.watched_bases = sorted(list(new_bases))
            self.settings.setValue("watched_bases", [str(b) for b in self.watched_bases])
            self.watch_input.clear()
            self.setup_watch_grid()
            self.update_ui()
        except ValueError:
            QMessageBox.warning(self, "Invalid Input", "Please use hex values (e.g., 0C0 or C00-C20).")

    def do_clear_watch(self):
        self.watched_bases.clear()
        self.settings.setValue("watched_bases", [])
        self.setup_watch_grid()

    def setup_watch_grid(self):
        self.watch_view.setRowCount(len(self.watched_bases))
        v_headers = [f"{b:03X}" for b in self.watched_bases]
        self.watch_view.setVerticalHeaderLabels(v_headers)

    # --- IDE CONTROLS ---
    def do_run(self):
        if self.cpu.pc in self.breakpoints:
            self.cpu.skip_breakpoint = True
        self.timer.start(self.current_interval)

    def do_new(self):
        if self.editor.toPlainText().strip():
            reply = QMessageBox.question(self, "Confirm New File", "You have changes in the editor. Are you sure you want to clear it?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if reply == QMessageBox.No: return
        self.editor.clear()
        self.current_file = None
        self.setWindowTitle("BeachCore IDE - New File")
        self.pc_map = {}; self.addr_map = {}
        self.update_ui()

    def do_open(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open ASM File", "", "Assembly Files (*.asm);;All Files (*)")
        if path:
            try:
                with open(path, 'r') as f: self.editor.setPlainText(f.read())
                self.current_file = path
                self.setWindowTitle(f"BeachCore IDE - {os.path.basename(path)}")
            except Exception as e: QMessageBox.critical(self, "Error", f"Could not open file: {e}")

    def do_save(self):
        if self.current_file:
            try:
                with open(self.current_file, 'w') as f: f.write(self.editor.toPlainText())
            except Exception as e: QMessageBox.critical(self, "Error", f"Could not save file: {e}")
        else: self.do_save_as()

    def do_save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save ASM File", "", "Assembly Files (*.asm);;All Files (*)")
        if path:
            if not path.endswith('.asm'): path += '.asm'
            self.current_file = path
            self.do_save()
            self.setWindowTitle(f"BeachCore IDE - {os.path.basename(path)}")

    def do_assemble(self):
        try:
            self.cpu.mem, self.pc_map, self.addr_map = self.assembler.assemble(self.editor.toPlainText())
            self.cpu.pc = 0; self.update_ui()
            self.statusBar().showMessage("Assembly Successful.", 3000)
        except Exception as e: QMessageBox.critical(self, "Error", str(e))

    def do_timer_step(self):
        # This is strictly for the auto-run timer.
        if self.cpu.pc in self.breakpoints and not self.cpu.skip_breakpoint:
            self.timer.stop()
            self.statusBar().showMessage(f"Breakpoint hit at 0x{self.cpu.pc:03X}", 3000)
            self.update_ui()
            return

        self.cpu.step()
        self.cpu.skip_breakpoint = False 
        self.update_ui()

    def do_step(self):
        # Manual step (F10) ALWAYS forces execution, ignoring breakpoints entirely
        self.cpu.step()
        self.update_ui()

    def do_reset(self):
        self.cpu.reset()
        self.statusBar().clearMessage()
        self.update_ui()

    def update_ui(self):
        regs = [
            ("PC", f"{self.cpu.pc:03X}"), ("ACC", f"{self.cpu.acc:02X}"),
            ("C", self.cpu.c), ("Z", self.cpu.z), ("IE", self.cpu.ie),
            ("ISR", self.cpu.in_isr), ("PC_SAVE", f"{self.cpu.pc_save:03X}"),
            ("Cycles", self.cpu.cycles), ("HALTED", "YES" if self.cpu.halted else "NO")
        ]
        self.reg_view.setRowCount(len(regs))
        for i, (n, v) in enumerate(regs):
            self.reg_view.setItem(i, 0, QTableWidgetItem(n))
            self.reg_view.setItem(i, 1, QTableWidgetItem(str(v)))

        line = self.pc_map.get(self.cpu.pc)
        if line is not None:
            sel = QTextEdit.ExtraSelection()
            if self.cpu.pc in self.breakpoints and not self.timer.isActive():
                sel.format.setBackground(QColor(180, 150, 0)) # Arcana Gold
            else:
                sel.format.setBackground(self.palette().highlight().color()) # Purple
            sel.format.setProperty(QTextFormat.FullWidthSelection, True)
            sel.cursor = QTextCursor(self.editor.document().findBlockByLineNumber(line))
            self.editor.setExtraSelections([sel])

        base = (self.cpu.pc >> 4) << 4
        v_headers = [f"{base+(r*16):03X}" for r in range(16)]
        self.mem_view.setVerticalHeaderLabels(v_headers)

        for r in range(16):
            for c in range(16):
                addr = base+(r*16)+c
                it = QTableWidgetItem(f"{self.cpu.mem[addr]:02X}")
                if addr == self.cpu.pc: it.setBackground(self.palette().highlight().color())
                self.mem_view.setItem(r, c, it)

        for r, watch_base in enumerate(self.watched_bases):
            for c in range(16):
                addr = watch_base + c
                if addr < 4096:
                    it = QTableWidgetItem(f"{self.cpu.mem[addr]:02X}")
                    if addr == self.cpu.pc: it.setBackground(self.palette().highlight().color())
                    self.watch_view.setItem(r, c, it)

if __name__ == "__main__":
    app = QApplication(sys.argv); app.setStyle("Fusion")

    arcana_palette = QPalette()
    arcana_palette.setColor(QPalette.Window, QColor(42, 46, 50))
    arcana_palette.setColor(QPalette.WindowText, QColor(252, 252, 252))
    arcana_palette.setColor(QPalette.Base, QColor(27, 30, 32))
    arcana_palette.setColor(QPalette.AlternateBase, QColor(35, 38, 41))
    arcana_palette.setColor(QPalette.ToolTipBase, QColor(49, 54, 59))
    arcana_palette.setColor(QPalette.ToolTipText, QColor(252, 252, 252))
    arcana_palette.setColor(QPalette.Text, QColor(252, 252, 252))
    arcana_palette.setColor(QPalette.Button, QColor(49, 54, 59))
    arcana_palette.setColor(QPalette.ButtonText, QColor(252, 252, 252))
    arcana_palette.setColor(QPalette.BrightText, QColor(75, 75, 75))
    arcana_palette.setColor(QPalette.Link, QColor(209, 199, 242))
    arcana_palette.setColor(QPalette.Highlight, QColor(110, 86, 169)) 
    arcana_palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
    app.setPalette(arcana_palette)
    
    win = MainWindow()
    win.show()
    
    sys.exit(app.exec())
