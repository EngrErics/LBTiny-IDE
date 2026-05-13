"""
hw_transfer.py
==============

LBTiny-IDE hardware transfer dialog.

Opens a debug/test window for sending binary payloads to the LBTiny Supervisor
(Nucleo-F446RE) over its ST-Link virtual COM port. Verifies that the CRC
returned by the supervisor matches a locally-computed CRC over the same data.

Protocol (v3, command-framed):
    PC -> Nucleo:  0xA5  [cmd_1B]  [len_le_4B]  [payload...]
    Nucleo -> PC:  0x5A  [cmd_1B]  [status_1B]  [data_len_le_4B]  [data...]

Commands:
    CMD_TRANSFER_CRC = 0x01
        payload = bytes to be CRC'd
        response data = [declared_len_le_4B] [crc_le_4B]  (8 bytes)
        status: 0x00 OK, 0x01 overflow, 0xFF unknown command

Future commands (flash read, sector erase, ping, etc.) plug into the same
framing without breaking compatibility.
"""

import os
import struct
import time
import random
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt, QObject, QThread, Signal, Slot
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QGroupBox, QLabel, QPushButton, QComboBox, QPlainTextEdit, QLineEdit,
    QFileDialog, QSizePolicy, QFrame, QWidget,
)

import serial
import serial.tools.list_ports

from stm32_crc import stm32_crc32, padded_length


# ----------------------------------------------------------------------------
# Protocol constants
# ----------------------------------------------------------------------------
SYNC_HOST_TO_NUCLEO = 0xA5
SYNC_NUCLEO_TO_HOST = 0x5A

CMD_TRANSFER_CRC    = 0x01
# CMD_PING          = 0x02   # reserved for future use
# CMD_FLASH_READ    = 0x10
# CMD_FLASH_ERASE   = 0x11

STATUS_OK           = 0x00
STATUS_OVERFLOW     = 0x01
STATUS_UNKNOWN_CMD  = 0xFF

STATUS_NAMES = {
    STATUS_OK:          "OK",
    STATUS_OVERFLOW:    "OVERFLOW",
    STATUS_UNKNOWN_CMD: "UNKNOWN_CMD",
}

MAX_PAYLOAD_BYTES = 4096
DEFAULT_BAUD = 115200
RESPONSE_FIXED_HEADER = 7   # sync + cmd + status + data_len_4B
RESPONSE_READ_TIMEOUT_S = 5.0


# ----------------------------------------------------------------------------
# Result dataclass passed back from worker to GUI
# ----------------------------------------------------------------------------
@dataclass
class TransferResult:
    ok: bool
    label: str
    declared_len: int
    local_crc: int
    nucleo_recv_len: Optional[int]
    nucleo_crc: Optional[int]
    nucleo_status: Optional[int]
    elapsed_s: float
    sent_bytes: bytes
    received_bytes: bytes
    error_message: str = ""


# ----------------------------------------------------------------------------
# Worker - lives in its own QThread, does all the serial I/O
# ----------------------------------------------------------------------------
class TransferWorker(QObject):
    """
    Performs serial I/O off the GUI thread. The dialog connects to these
    signals and updates the UI from the main thread when they fire.
    """
    log = Signal(str, str)                 # (level, message) - level: "info"/"tx"/"rx"/"error"
    connection_changed = Signal(bool, str) # (connected, status_text)
    transfer_complete = Signal(object)     # TransferResult

    def __init__(self):
        super().__init__()
        self._port: Optional[serial.Serial] = None

    # -- connection management ----------------------------------------------
    @Slot(str, int)
    def open_port(self, port_name: str, baud: int):
        try:
            if self._port is not None and self._port.is_open:
                self._port.close()
            self._port = serial.Serial(port_name, baud, timeout=2.0)
            time.sleep(0.4)  # let the Nucleo boot banner settle
            # Drain anything that arrived during boot/open
            try:
                self._port.reset_input_buffer()
            except Exception:
                pass
            self.connection_changed.emit(
                True, f"connected to {port_name} @ {baud} baud"
            )
            self.log.emit("info", f"opened {port_name} at {baud} baud")
        except serial.SerialException as e:
            self._port = None
            self.connection_changed.emit(False, f"open failed: {e}")
            self.log.emit("error", f"could not open {port_name}: {e}")

    @Slot()
    def close_port(self):
        if self._port is not None and self._port.is_open:
            try:
                self._port.close()
            except Exception:
                pass
            self.log.emit("info", "port closed")
        self._port = None
        self.connection_changed.emit(False, "disconnected")

    # -- transfer execution -------------------------------------------------
    @Slot(str, bytes)
    def do_transfer(self, label: str, payload: bytes):
        """Send a CMD_TRANSFER_CRC and read back the response."""
        if self._port is None or not self._port.is_open:
            self.log.emit("error", "transfer requested but port is not open")
            self.transfer_complete.emit(TransferResult(
                ok=False, label=label, declared_len=len(payload),
                local_crc=0, nucleo_recv_len=None, nucleo_crc=None,
                nucleo_status=None, elapsed_s=0.0,
                sent_bytes=b"", received_bytes=b"",
                error_message="port not open",
            ))
            return

        declared_len = len(payload)

        # Drain any stale bytes from boot banner or previous transfers
        try:
            stale = self._port.read(self._port.in_waiting or 0)
            if stale:
                self.log.emit("info",
                    f"drained {len(stale)} stale bytes before transfer")
        except Exception:
            pass

        # Build frame: 0xA5 | cmd | len_le_4B | payload
        header = struct.pack("<BBI", SYNC_HOST_TO_NUCLEO, CMD_TRANSFER_CRC,
                             declared_len)
        frame = header + payload

        self.log.emit("tx", f"frame {len(frame)} bytes  "
                            f"(header: {header.hex(' ')}, payload: {declared_len} bytes)")

        # Local CRC is over what the Nucleo would actually store (max 4096)
        stored_portion = payload[:MAX_PAYLOAD_BYTES]
        local_crc = stm32_crc32(stored_portion)

        t_start = time.time()
        try:
            self._port.write(frame)
            self._port.flush()
        except serial.SerialException as e:
            self.log.emit("error", f"write failed: {e}")
            self.transfer_complete.emit(TransferResult(
                ok=False, label=label, declared_len=declared_len,
                local_crc=local_crc, nucleo_recv_len=None, nucleo_crc=None,
                nucleo_status=None, elapsed_s=time.time() - t_start,
                sent_bytes=frame, received_bytes=b"",
                error_message=f"write failed: {e}",
            ))
            return

        # Read fixed header first to learn data_len
        self._port.timeout = RESPONSE_READ_TIMEOUT_S
        try:
            head = self._port.read(RESPONSE_FIXED_HEADER)
        except serial.SerialException as e:
            self.log.emit("error", f"read failed: {e}")
            self.transfer_complete.emit(TransferResult(
                ok=False, label=label, declared_len=declared_len,
                local_crc=local_crc, nucleo_recv_len=None, nucleo_crc=None,
                nucleo_status=None, elapsed_s=time.time() - t_start,
                sent_bytes=frame, received_bytes=b"",
                error_message=f"read failed: {e}",
            ))
            return

        if len(head) != RESPONSE_FIXED_HEADER:
            self.log.emit("error",
                f"response header truncated: got {len(head)} of "
                f"{RESPONSE_FIXED_HEADER} bytes")
            self.transfer_complete.emit(TransferResult(
                ok=False, label=label, declared_len=declared_len,
                local_crc=local_crc, nucleo_recv_len=None, nucleo_crc=None,
                nucleo_status=None, elapsed_s=time.time() - t_start,
                sent_bytes=frame, received_bytes=head,
                error_message="response header truncated",
            ))
            return

        sync, cmd, status, data_len = struct.unpack("<BBBI", head)

        if sync != SYNC_NUCLEO_TO_HOST:
            self.log.emit("error",
                f"bad response sync 0x{sync:02X} (expected 0x{SYNC_NUCLEO_TO_HOST:02X})")
            self.transfer_complete.emit(TransferResult(
                ok=False, label=label, declared_len=declared_len,
                local_crc=local_crc, nucleo_recv_len=None, nucleo_crc=None,
                nucleo_status=status, elapsed_s=time.time() - t_start,
                sent_bytes=frame, received_bytes=head,
                error_message=f"bad response sync 0x{sync:02X}",
            ))
            return

        # Read variable-length data
        data = self._port.read(data_len) if data_len else b""
        t_end = time.time()
        full_response = head + data

        self.log.emit("rx", f"response {len(full_response)} bytes: "
                            f"{full_response.hex(' ')}")
        self.log.emit("info",
            f"cmd=0x{cmd:02X} status=0x{status:02X} ({STATUS_NAMES.get(status, '?')}) "
            f"data_len={data_len}")

        # Parse CMD_TRANSFER_CRC response data
        nucleo_recv_len = None
        nucleo_crc = None
        if cmd == CMD_TRANSFER_CRC and data_len >= 8:
            nucleo_recv_len, nucleo_crc = struct.unpack("<II", data[:8])

        # Decide PASS/FAIL
        ok = False
        error_message = ""

        if cmd != CMD_TRANSFER_CRC:
            error_message = f"response cmd 0x{cmd:02X} doesn't match request"
        elif nucleo_recv_len is None or nucleo_crc is None:
            error_message = "response data missing length/CRC"
        elif nucleo_recv_len != declared_len:
            error_message = (f"length mismatch: declared {declared_len}, "
                             f"echoed {nucleo_recv_len}")
        elif nucleo_crc != local_crc:
            if status == STATUS_OVERFLOW:
                error_message = ("CRCs disagree even after accounting for "
                                 "overflow truncation")
            else:
                error_message = "CRC mismatch - data corruption in transfer"
        else:
            ok = True
            if status == STATUS_OVERFLOW:
                self.log.emit("info",
                    f"overflow case OK: sent {declared_len}, "
                    f"stored {MAX_PAYLOAD_BYTES}, CRCs agree on stored portion")

        self.transfer_complete.emit(TransferResult(
            ok=ok, label=label, declared_len=declared_len,
            local_crc=local_crc, nucleo_recv_len=nucleo_recv_len,
            nucleo_crc=nucleo_crc, nucleo_status=status,
            elapsed_s=t_end - t_start,
            sent_bytes=frame, received_bytes=full_response,
            error_message=error_message,
        ))


# ----------------------------------------------------------------------------
# Dialog
# ----------------------------------------------------------------------------
class HwTransferDialog(QDialog):
    """
    Debug/test dialog for the LBTiny hardware transfer protocol.

    Layout (top to bottom):
      - Connection bar: port dropdown, refresh, baud, Connect/Disconnect
      - Binary info: source label, size, padded size, local CRC, recompute
      - Debug actions: Send Current Binary / Empty / Test Pattern / Random / Overflow
      - Last transfer results: declared, recv, local CRC, nucleo CRC, status, elapsed
      - Log pane: timestamped log of everything, with Clear button
    """

    # Signals to the worker (cross-thread)
    _request_open  = Signal(str, int)
    _request_close = Signal()
    _request_xfer  = Signal(str, bytes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._parent_window = parent  # used to fetch current_binary
        self.setWindowTitle("LBTiny - Hardware Transfer (Debug)")
        self.resize(820, 720)

        self._build_ui()
        self._start_worker()
        self._refresh_ports()

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # ---- connection bar ----
        conn_group = QGroupBox("Connection")
        conn_row = QHBoxLayout(conn_group)

        conn_row.addWidget(QLabel("Port:"))
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(220)
        conn_row.addWidget(self.port_combo)

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._refresh_ports)
        conn_row.addWidget(self.refresh_btn)

        conn_row.addWidget(QLabel("Baud:"))
        self.baud_combo = QComboBox()
        self.baud_combo.addItems(["115200"])
        self.baud_combo.setCurrentText("115200")
        conn_row.addWidget(self.baud_combo)

        self.connect_btn = QPushButton("Connect")
        self.connect_btn.clicked.connect(self._on_connect_clicked)
        conn_row.addWidget(self.connect_btn)

        self.conn_status_label = QLabel("disconnected")
        self.conn_status_label.setStyleSheet("color: #AAA; font-style: italic;")
        conn_row.addWidget(self.conn_status_label, 1)

        layout.addWidget(conn_group)

        # ---- binary info ----
        bin_group = QGroupBox("Binary Info")
        bin_layout = QFormLayout(bin_group)

        self.bin_source_label = QLabel("(none - use Send Current Binary to pull from IDE)")
        bin_layout.addRow("Source:", self.bin_source_label)

        self.bin_size_label = QLabel("0 bytes")
        bin_layout.addRow("Size:", self.bin_size_label)

        self.bin_padded_label = QLabel("0 bytes")
        bin_layout.addRow("Padded (for CRC):", self.bin_padded_label)

        crc_row = QHBoxLayout()
        self.bin_local_crc_label = QLabel("—")
        self.bin_local_crc_label.setFont(self._mono_font())
        crc_row.addWidget(self.bin_local_crc_label, 1)
        self.recompute_btn = QPushButton("Recompute Local CRC")
        self.recompute_btn.clicked.connect(self._recompute_local_crc)
        crc_row.addWidget(self.recompute_btn)
        crc_wrap = QWidget()
        crc_wrap.setLayout(crc_row)
        bin_layout.addRow("Local CRC:", crc_wrap)

        layout.addWidget(bin_group)

        # ---- debug actions ----
        act_group = QGroupBox("Debug Actions")
        act_grid = QGridLayout(act_group)

        self.btn_send_current = QPushButton("Send Current Binary")
        self.btn_send_empty   = QPushButton("Send Empty")
        self.btn_send_pattern = QPushButton("Send Test Pattern (64 counting)")
        self.btn_send_random  = QPushButton("Send Random 3000")
        self.btn_send_over    = QPushButton("Send Overflow (5000)")

        self.btn_send_current.clicked.connect(self._send_current)
        self.btn_send_empty.clicked.connect(self._send_empty)
        self.btn_send_pattern.clicked.connect(self._send_pattern)
        self.btn_send_random.clicked.connect(self._send_random)
        self.btn_send_over.clicked.connect(self._send_overflow)

        act_grid.addWidget(self.btn_send_current, 0, 0)
        act_grid.addWidget(self.btn_send_empty,   0, 1)
        act_grid.addWidget(self.btn_send_pattern, 0, 2)
        act_grid.addWidget(self.btn_send_random,  1, 0)
        act_grid.addWidget(self.btn_send_over,    1, 1)

        # Placeholder column for future commands (flash read, etc.)
        future_label = QLabel("(future: flash read, sector erase, ping, status query)")
        future_label.setStyleSheet("color: #666; font-style: italic;")
        act_grid.addWidget(future_label, 1, 2)

        layout.addWidget(act_group)

        # Start with action buttons disabled until connected
        self._set_actions_enabled(False)

        # ---- last transfer results ----
        res_group = QGroupBox("Last Transfer Result")
        res_form = QFormLayout(res_group)

        self.res_banner = QLabel("(no transfer yet)")
        self.res_banner.setAlignment(Qt.AlignCenter)
        self.res_banner.setStyleSheet(
            "padding: 8px; background: #333; color: #AAA; font-weight: bold;"
        )
        res_form.addRow(self.res_banner)

        self.res_label_label  = QLabel("—")
        self.res_declared_lbl = QLabel("—")
        self.res_recv_lbl     = QLabel("—")
        self.res_local_crc    = QLabel("—"); self.res_local_crc.setFont(self._mono_font())
        self.res_nucleo_crc   = QLabel("—"); self.res_nucleo_crc.setFont(self._mono_font())
        self.res_status_lbl   = QLabel("—")
        self.res_elapsed_lbl  = QLabel("—")
        self.res_error_lbl    = QLabel(""); self.res_error_lbl.setStyleSheet("color: #FF8888;")

        res_form.addRow("Label:", self.res_label_label)
        res_form.addRow("Declared len (host):", self.res_declared_lbl)
        res_form.addRow("Recv len (Nucleo echo):", self.res_recv_lbl)
        res_form.addRow("Local CRC:", self.res_local_crc)
        res_form.addRow("Nucleo CRC:", self.res_nucleo_crc)
        res_form.addRow("Status byte:", self.res_status_lbl)
        res_form.addRow("Elapsed:", self.res_elapsed_lbl)
        res_form.addRow("Error:", self.res_error_lbl)

        layout.addWidget(res_group)

        # ---- log pane ----
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(self._mono_font())
        self.log_view.setMaximumBlockCount(2000)
        log_layout.addWidget(self.log_view, 1)

        log_btn_row = QHBoxLayout()
        clear_btn = QPushButton("Clear Log")
        clear_btn.clicked.connect(self.log_view.clear)
        log_btn_row.addStretch()
        log_btn_row.addWidget(clear_btn)
        log_layout.addLayout(log_btn_row)

        layout.addWidget(log_group, 1)  # log expands

    def _mono_font(self) -> QFont:
        f = QFont("Courier New", 10)
        f.setStyleHint(QFont.Monospace)
        f.setFixedPitch(True)
        return f

    # ------------------------------------------------------------- worker
    def _start_worker(self):
        self._thread = QThread(self)
        self._worker = TransferWorker()
        self._worker.moveToThread(self._thread)

        # Worker -> dialog
        self._worker.log.connect(self._on_log)
        self._worker.connection_changed.connect(self._on_connection_changed)
        self._worker.transfer_complete.connect(self._on_transfer_complete)

        # Dialog -> worker
        self._request_open.connect(self._worker.open_port)
        self._request_close.connect(self._worker.close_port)
        self._request_xfer.connect(self._worker.do_transfer)

        self._thread.start()

    def closeEvent(self, event):
        """Close the worker thread cleanly when the dialog closes."""
        try:
            self._request_close.emit()
            self._thread.quit()
            self._thread.wait(2000)
        except Exception:
            pass
        super().closeEvent(event)

    # ------------------------------------------------------------ helpers
    def _set_actions_enabled(self, enabled: bool):
        self.btn_send_current.setEnabled(enabled)
        self.btn_send_empty.setEnabled(enabled)
        self.btn_send_pattern.setEnabled(enabled)
        self.btn_send_random.setEnabled(enabled)
        self.btn_send_over.setEnabled(enabled)

    def _refresh_ports(self):
        self.port_combo.clear()
        ports = list(serial.tools.list_ports.comports())
        # Prefer /dev/ttyACM* on Linux, /dev/cu.usbmodem* on Mac, COM* on Windows
        def sort_key(p):
            n = p.device
            score = 0
            if "ACM" in n or "usbmodem" in n: score -= 100
            return (score, n)
        ports.sort(key=sort_key)
        if not ports:
            self.port_combo.addItem("(no ports found)", userData=None)
            return
        for p in ports:
            desc = f"{p.device}"
            if p.description and p.description != "n/a":
                desc += f"  —  {p.description}"
            self.port_combo.addItem(desc, userData=p.device)
        self._on_log("info", f"found {len(ports)} serial port(s)")

    def _current_port_device(self) -> Optional[str]:
        return self.port_combo.currentData()

    def _on_connect_clicked(self):
        if self.connect_btn.text() == "Connect":
            dev = self._current_port_device()
            if not dev:
                self._on_log("error", "no port selected")
                return
            baud = int(self.baud_combo.currentText())
            self._request_open.emit(dev, baud)
        else:
            self._request_close.emit()

    # ------------------------------------------------------- signal slots
    @Slot(str, str)
    def _on_log(self, level: str, message: str):
        colors = {
            "info":  "#CCC",
            "tx":    "#80C0FF",
            "rx":    "#80FFB0",
            "error": "#FF8888",
        }
        prefixes = {"info": " ", "tx": "→", "rx": "←", "error": "!"}
        color = colors.get(level, "#CCC")
        prefix = prefixes.get(level, " ")
        ts = time.strftime("%H:%M:%S")
        # Use HTML so we can color the line; QPlainTextEdit doesn't render HTML
        # so we use appendPlainText with a level marker prefix instead.
        self.log_view.appendPlainText(f"{ts} {prefix} [{level:5s}] {message}")
        # Scroll to bottom
        self.log_view.moveCursor(QTextCursor.End)

    @Slot(bool, str)
    def _on_connection_changed(self, connected: bool, status_text: str):
        self.conn_status_label.setText(status_text)
        if connected:
            self.conn_status_label.setStyleSheet("color: #80FFB0;")
            self.connect_btn.setText("Disconnect")
            self._set_actions_enabled(True)
        else:
            self.conn_status_label.setStyleSheet("color: #AAA; font-style: italic;")
            self.connect_btn.setText("Connect")
            self._set_actions_enabled(False)

    @Slot(object)
    def _on_transfer_complete(self, r: TransferResult):
        # Banner
        if r.ok:
            self.res_banner.setText(f"PASS  —  {r.label}")
            self.res_banner.setStyleSheet(
                "padding: 8px; background: #B49600; color: white; font-weight: bold;"
            )
        else:
            self.res_banner.setText(f"FAIL  —  {r.label}")
            self.res_banner.setStyleSheet(
                "padding: 8px; background: #882222; color: white; font-weight: bold;"
            )

        # Fields
        self.res_label_label.setText(r.label)
        self.res_declared_lbl.setText(f"{r.declared_len} bytes")
        self.res_recv_lbl.setText(
            f"{r.nucleo_recv_len} bytes" if r.nucleo_recv_len is not None else "—"
        )
        self.res_local_crc.setText(f"0x{r.local_crc:08X}")
        self.res_nucleo_crc.setText(
            f"0x{r.nucleo_crc:08X}" if r.nucleo_crc is not None else "—"
        )
        if r.nucleo_status is not None:
            status_name = STATUS_NAMES.get(r.nucleo_status, "?")
            self.res_status_lbl.setText(f"0x{r.nucleo_status:02X} ({status_name})")
        else:
            self.res_status_lbl.setText("—")
        self.res_elapsed_lbl.setText(f"{r.elapsed_s:.3f} s")
        self.res_error_lbl.setText(r.error_message or "")

    # ----------------------------------------------------- action handlers
    def _get_current_binary(self) -> Optional[bytes]:
        """Pull the freshest binary from the parent IDE."""
        binary = getattr(self._parent_window, "current_binary", None)
        if binary is None:
            return None
        # current_binary in main.py is a bytearray; convert to bytes
        return bytes(binary)

    def _recompute_local_crc(self):
        """Refresh the binary-info group from whatever is loaded in the IDE."""
        binary = self._get_current_binary()
        if binary is None:
            self.bin_source_label.setText("(no binary - assemble in IDE first)")
            self.bin_size_label.setText("0 bytes")
            self.bin_padded_label.setText("0 bytes")
            self.bin_local_crc_label.setText("—")
            self._on_log("info", "no current_binary on parent window")
            return

        src = getattr(self._parent_window, "current_file", None) or "(unsaved)"
        self.bin_source_label.setText(os.path.basename(src) if src else "(unsaved)")
        self.bin_size_label.setText(f"{len(binary)} bytes")
        self.bin_padded_label.setText(f"{padded_length(binary)} bytes")
        crc = stm32_crc32(binary)
        self.bin_local_crc_label.setText(f"0x{crc:08X}")
        self._on_log("info",
            f"local CRC of current binary: 0x{crc:08X} "
            f"(size {len(binary)}, padded {padded_length(binary)})")

    def _send_current(self):
        binary = self._get_current_binary()
        if binary is None:
            self._on_log("error",
                "no current_binary loaded - assemble in the IDE first")
            return
        self._recompute_local_crc()
        self._request_xfer.emit(f"current binary ({len(binary)} B)", binary)

    def _send_empty(self):
        self._request_xfer.emit("empty payload", b"")

    def _send_pattern(self):
        payload = bytes(range(64))
        self._request_xfer.emit("test pattern (64 counting)", payload)

    def _send_random(self):
        rng = random.Random(0xC0FFEE)
        payload = bytes(rng.randint(0, 255) for _ in range(3000))
        self._request_xfer.emit("random 3000 bytes", payload)

    def _send_overflow(self):
        payload = bytes((i & 0xFF) for i in range(5000))
        self._request_xfer.emit("overflow 5000 bytes", payload)