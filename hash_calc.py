#!/usr/bin/env python3
"""
HashCalc — 文件哈希计算器
支持拖放文件、手动选择、多种哈希算法并行计算
"""

import sys
import hashlib
import os
from pathlib import Path

from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QCheckBox, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QLabel, QProgressBar, QMessageBox, QGridLayout, QSizePolicy
)
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QDragMoveEvent, QFont, QColor

# ── 支持的哈希算法 ─────────────────────────────────────────────
HASH_ALGOS = {
    "MD5":      hashlib.md5,
    "SHA1":     hashlib.sha1,
    "SHA224":   hashlib.sha224,
    "SHA256":   hashlib.sha256,
    "SHA384":   hashlib.sha384,
    "SHA512":   hashlib.sha512,
    "SHA3-256": hashlib.sha3_256,
    "SHA3-512": hashlib.sha3_512,
    "BLAKE2b":  hashlib.blake2b,
    "BLAKE2s":  hashlib.blake2s,
}


# ── 后台计算线程 ───────────────────────────────────────────────
class HashWorker(QThread):
    progress = Signal(int, int)       # current_bytes, total_bytes
    finished = Signal(dict)           # {algo_name: hex_digest}
    error = Signal(str)

    def __init__(self, filepath: str, algos: list):
        super().__init__()
        self.filepath = filepath
        self.algos = algos  # list of (display_name, hashlib_func)

    def run(self):
        try:
            file_size = os.path.getsize(self.filepath)
            hashers = {name: func() for name, func in self.algos}
            read = 0
            with open(self.filepath, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)  # 1 MiB chunks
                    if not chunk:
                        break
                    for h in hashers.values():
                        h.update(chunk)
                    read += len(chunk)
                    self.progress.emit(read, file_size)
            results = {name: h.hexdigest() for name, h in hashers.items()}
            self.finished.emit(results)
        except Exception as e:
            self.error.emit(str(e))


# ── 主窗口 ─────────────────────────────────────────────────────
class HashCalcWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("HashCalc — 文件哈希计算器")
        self.setMinimumSize(700, 560)
        self.resize(760, 600)
        self.worker: HashWorker | None = None

        # 全窗口接受拖放
        self.setAcceptDrops(True)
        self._drag_active = False

        self._setup_ui()
        self._setup_drop_overlay()
        self._apply_style()

    # ── UI 构建 ──────────────────────────────────────────────
    def _setup_ui(self):
        self._main_layout = QVBoxLayout(self)
        self._main_layout.setSpacing(10)
        self._main_layout.setContentsMargins(16, 14, 16, 14)

        # 标题
        title = QLabel("HashCalc — 文件哈希计算器")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 16pt; font-weight: bold; margin-bottom: 4px;")
        self._main_layout.addWidget(title)

        # ── 哈希类型选择 ────────────────────────────────────
        algo_group = QGroupBox("选择哈希算法（可多选）")
        algo_layout = QGridLayout(algo_group)
        algo_layout.setSpacing(6)

        self.algo_checkboxes: dict[str, QCheckBox] = {}
        items = list(HASH_ALGOS.items())
        for i, (name, _) in enumerate(items):
            cb = QCheckBox(name)
            cb.setChecked(name in ("SHA256", "SHA512", "MD5"))
            self.algo_checkboxes[name] = cb
            row, col = i % 5, i // 5 * 2
            algo_layout.addWidget(cb, row, col)

        # 快捷按钮行 — 加大高度
        quick_layout = QHBoxLayout()
        quick_layout.setSpacing(8)

        btn_all = QPushButton("全选")
        btn_none = QPushButton("取消")
        btn_common = QPushButton("常用  (MD5 / SHA256 / SHA512)")
        for btn in (btn_all, btn_none, btn_common):
            btn.setMinimumHeight(30)
            btn.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        btn_all.clicked.connect(lambda: self._set_all_algos(True))
        btn_none.clicked.connect(lambda: self._set_all_algos(False))
        btn_common.clicked.connect(self._select_common)

        quick_layout.addWidget(btn_all)
        quick_layout.addWidget(btn_none)
        quick_layout.addWidget(btn_common)
        quick_layout.addStretch()
        algo_layout.addLayout(quick_layout, 5, 0, 1, 4)

        self._main_layout.addWidget(algo_group)

        # ── 文件选择 ────────────────────────────────────────
        file_group = QGroupBox("选择文件")
        file_layout = QHBoxLayout(file_group)
        self.drop_edit = QLineEdit()
        self.drop_edit.setReadOnly(True)
        self.drop_edit.setPlaceholderText("拖放文件到窗口任意位置，或点击右侧「浏览」按钮…")
        btn_browse = QPushButton("浏览…")
        btn_browse.setMinimumWidth(80)
        btn_browse.setMinimumHeight(28)
        btn_browse.clicked.connect(self._browse_file)
        file_layout.addWidget(self.drop_edit)
        file_layout.addWidget(btn_browse)
        self._main_layout.addWidget(file_group)

        # ── 操作按钮 ────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self.btn_calc = QPushButton("▶  开始计算")
        self.btn_calc.setMinimumHeight(40)
        self.btn_calc.setStyleSheet("font-size: 12pt; font-weight: bold;")

        self.btn_copy = QPushButton("📋 复制结果")
        self.btn_copy.setMinimumHeight(40)
        self.btn_copy.setEnabled(False)

        self.btn_calc.clicked.connect(self._start_calculation)
        self.btn_copy.clicked.connect(self._copy_results)

        btn_row.addWidget(self.btn_calc)
        btn_row.addWidget(self.btn_copy)
        self._main_layout.addLayout(btn_row)

        # ── 进度条 ──────────────────────────────────────────
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setMinimumHeight(18)
        self._main_layout.addWidget(self.progress_bar)

        # ── 结果显示 ────────────────────────────────────────
        result_group = QGroupBox("计算结果")
        result_layout = QVBoxLayout(result_group)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setFont(QFont("Consolas", 10))
        self.result_text.setPlaceholderText("等待计算…")
        self.result_text.setMinimumHeight(180)
        result_layout.addWidget(self.result_text)
        self._main_layout.addWidget(result_group)

    # ── 全窗口拖放覆盖层 ────────────────────────────────────
    def _setup_drop_overlay(self):
        """半透明覆盖层，拖拽文件进入窗口时显示"""
        self._overlay = QLabel(self)
        self._overlay.setText("📂  松开鼠标以加载文件")
        self._overlay.setAlignment(Qt.AlignCenter)
        self._overlay.setFont(QFont("Microsoft YaHei", 16))
        self._overlay.setStyleSheet("""
            QLabel {
                background: rgba(30, 136, 229, 0.88);
                color: #ffffff;
                border: 4px dashed #ffffff;
                border-radius: 16px;
                font-weight: bold;
            }
        """)
        self._overlay.setVisible(False)

    def resizeEvent(self, event):
        """窗口大小变化时同步覆盖层尺寸"""
        super().resizeEvent(event)
        self._overlay.setGeometry(self.rect())

    # ── 全窗口拖放事件 ──────────────────────────────────────
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._drag_active = True
            self._overlay.setGeometry(self.rect())
            self._overlay.setVisible(True)
            self._overlay.raise_()

    def dragMoveEvent(self, event: QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._drag_active = False
        self._overlay.setVisible(False)

    def dropEvent(self, event: QDropEvent):
        self._drag_active = False
        self._overlay.setVisible(False)
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if os.path.isfile(path):
                self.drop_edit.setText(path)

    # ── 样式 ────────────────────────────────────────────────
    def _apply_style(self):
        self.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #ccc;
                border-radius: 6px;
                margin-top: 8px;
                padding-top: 14px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 12px;
                padding: 0 6px;
            }
            QLineEdit {
                padding: 8px 10px;
                border: 1px solid #bbb;
                border-radius: 4px;
                font-size: 10pt;
            }
            QPushButton {
                padding: 6px 16px;
                border: 1px solid #aaa;
                border-radius: 4px;
                background: #f5f5f5;
            }
            QPushButton:hover {
                background: #e0e0e0;
            }
            QPushButton:pressed {
                background: #d0d0d0;
            }
            QPushButton:disabled {
                color: #999;
            }
            QTextEdit {
                border: 1px solid #bbb;
                border-radius: 4px;
            }
        """)

    # ── 槽函数 ──────────────────────────────────────────────
    def _set_all_algos(self, checked: bool):
        for cb in self.algo_checkboxes.values():
            cb.setChecked(checked)

    def _select_common(self):
        for name, cb in self.algo_checkboxes.items():
            cb.setChecked(name in ("MD5", "SHA256", "SHA512"))

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "选择文件", "",
            "所有文件 (*.*);;文本文件 (*.txt);;二进制文件 (*.bin *.exe *.dll)"
        )
        if path:
            self.drop_edit.setText(path)

    def _selected_algos(self) -> list:
        return [(name, HASH_ALGOS[name])
                for name, cb in self.algo_checkboxes.items()
                if cb.isChecked()]

    def _start_calculation(self):
        filepath = self.drop_edit.text().strip()
        if not filepath:
            QMessageBox.warning(self, "提示", "请先选择或拖放一个文件。")
            return
        if not os.path.isfile(filepath):
            QMessageBox.warning(self, "提示", f"文件不存在:\n{filepath}")
            return

        algos = self._selected_algos()
        if not algos:
            QMessageBox.warning(self, "提示", "请至少选择一种哈希算法。")
            return

        self.btn_calc.setEnabled(False)
        self.btn_copy.setEnabled(False)
        self.result_text.clear()
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)

        file_size = os.path.getsize(filepath)
        self.progress_bar.setMaximum(file_size)

        self.worker = HashWorker(filepath, algos)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)
        self.worker.start()

    def _on_progress(self, current: int, total: int):
        self.progress_bar.setValue(current)

    def _on_finished(self, results: dict):
        self.progress_bar.setVisible(False)
        self.btn_calc.setEnabled(True)
        self.btn_copy.setEnabled(True)

        filepath = self.drop_edit.text().strip()
        filename = os.path.basename(filepath)
        file_size = os.path.getsize(filepath)

        lines = [
            f"文件: {filename}",
            f"路径: {filepath}",
            f"大小: {self._fmt_size(file_size)}",
            "─" * 56,
        ]
        for name, digest in results.items():
            lines.append(f"{name:12s}: {digest}")
        self.result_text.setPlainText("\n".join(lines))

    def _on_error(self, msg: str):
        self.progress_bar.setVisible(False)
        self.btn_calc.setEnabled(True)
        QMessageBox.critical(self, "计算错误", f"读取文件时出错:\n{msg}")

    def _copy_results(self):
        text = self.result_text.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self.btn_copy.setText("✅ 已复制!")
            QTimer.singleShot(1500, lambda: self.btn_copy.setText("📋 复制结果"))

    @staticmethod
    def _fmt_size(size: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024:
                return f"{size:,} {unit}"
            size //= 1024
        return f"{size:,} PB"


# ── 入口 ────────────────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("HashCalc")
    window = HashCalcWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
