from __future__ import annotations

import contextlib
import shutil
import sys
import threading
import traceback
from pathlib import Path
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from src.config import load_config
from src.douyin_uploader import DouyinUploader
from src.invoice_parser import InvoiceParseResult, parse_invoices


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def ensure_config_file() -> Path:
    target = app_base_dir() / "config.yaml"
    if target.exists():
        return target

    bundled_dir = Path(getattr(sys, "_MEIPASS", app_base_dir()))
    bundled_config = bundled_dir / "config.yaml"
    if bundled_config.exists():
        shutil.copy2(bundled_config, target)
        return target

    raise FileNotFoundError(f"未找到配置文件: {target}")


class SignalWriter:
    def __init__(self, signal: QtCore.SignalInstance) -> None:
        self.signal = signal

    def write(self, text: str) -> int:
        if text:
            self.signal.emit(text)
        return len(text)

    def flush(self) -> None:
        pass


class TaskWorker(QtCore.QObject):
    log = QtCore.Signal(str)
    finished = QtCore.Signal(str)
    failed = QtCore.Signal(str)
    waiting_for_login = QtCore.Signal()

    def __init__(self, task) -> None:
        super().__init__()
        self.task = task

    @QtCore.Slot()
    def run(self) -> None:
        try:
            writer = SignalWriter(self.log)
            with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
                message = self.task(self)
            self.finished.emit(message or "完成")
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.config_path = ensure_config_file()
        self.config = load_config(self.config_path)
        self.pdf_dir = Path(self.config["pdf"]["input_dir"]).expanduser()
        self.thread: QtCore.QThread | None = None
        self.worker: TaskWorker | None = None
        self.login_event: threading.Event | None = None

        self.setWindowTitle("发票自动提交")
        self.resize(980, 680)
        self._build_ui()
        self._load_initial_state()

    def _build_ui(self) -> None:
        root = QtWidgets.QWidget()
        self.setCentralWidget(root)

        layout = QtWidgets.QVBoxLayout(root)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        title = QtWidgets.QLabel("发票自动提交")
        title.setObjectName("title")
        layout.addWidget(title)

        folder_row = QtWidgets.QHBoxLayout()
        self.folder_label = QtWidgets.QLineEdit()
        self.folder_label.setReadOnly(True)
        self.folder_label.setMinimumHeight(34)
        self.choose_folder_button = QtWidgets.QPushButton("选择 PDF 文件夹")
        self.choose_folder_button.setMinimumHeight(34)
        self.choose_folder_button.clicked.connect(self.choose_pdf_folder)
        folder_row.addWidget(self.folder_label, 1)
        folder_row.addWidget(self.choose_folder_button)
        layout.addLayout(folder_row)

        controls = QtWidgets.QHBoxLayout()
        self.login_button = QtWidgets.QPushButton("登录")
        self.save_login_button = QtWidgets.QPushButton("保存登录状态")
        self.parse_button = QtWidgets.QPushButton("解析发票")
        self.upload_button = QtWidgets.QPushButton("上传发票")
        self.run_button = QtWidgets.QPushButton("全流程")
        self.dry_run_checkbox = QtWidgets.QCheckBox("Dry-run（不上传）")

        for button in (
            self.login_button,
            self.save_login_button,
            self.parse_button,
            self.upload_button,
            self.run_button,
        ):
            button.setMinimumHeight(36)
            controls.addWidget(button)

        controls.addStretch(1)
        controls.addWidget(self.dry_run_checkbox)
        layout.addLayout(controls)

        self.save_login_button.setEnabled(False)
        self.login_button.clicked.connect(self.start_login)
        self.save_login_button.clicked.connect(self.save_login_state)
        self.parse_button.clicked.connect(self.start_parse)
        self.upload_button.clicked.connect(self.start_upload)
        self.run_button.clicked.connect(self.start_run_all)

        self.status_label = QtWidgets.QLabel("就绪")
        self.status_label.setObjectName("status")
        layout.addWidget(self.status_label)

        self.log_edit = QtWidgets.QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self.log_edit, 1)

        self.setStyleSheet(
            """
            QWidget {
                font-family: "Microsoft YaHei", "Noto Sans CJK SC", Arial, sans-serif;
                font-size: 14px;
            }
            QLabel#title {
                font-size: 24px;
                font-weight: 700;
            }
            QLabel#status {
                color: #4b5563;
            }
            QPushButton {
                padding: 7px 14px;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background: #f8fafc;
            }
            QPushButton:hover {
                background: #eef2f7;
            }
            QPushButton:disabled {
                color: #9ca3af;
                background: #f3f4f6;
            }
            QPlainTextEdit, QLineEdit {
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                background: #ffffff;
            }
            QPlainTextEdit {
                padding: 8px;
            }
            """
        )

    def _load_initial_state(self) -> None:
        self.folder_label.setText(str(self.pdf_dir))
        self.dry_run_checkbox.setChecked(
            bool(self.config.get("upload", {}).get("dry_run", True))
        )
        self.append_log("桌面 App 已启动。\n")
        self.append_log(f"当前 PDF 文件夹: {self.pdf_dir}\n")

    def choose_pdf_folder(self) -> None:
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "选择 PDF 文件夹",
            str(self.pdf_dir if self.pdf_dir.exists() else Path.cwd()),
        )
        if not selected:
            return
        self.pdf_dir = Path(selected)
        self.folder_label.setText(str(self.pdf_dir))
        self.append_log(f"已选择 PDF 文件夹: {self.pdf_dir}\n")

    def runtime_config(self) -> dict[str, Any]:
        config = load_config(self.config_path)
        config.setdefault("pdf", {})["input_dir"] = str(self.pdf_dir)
        config.setdefault("upload", {})["dry_run"] = self.dry_run_checkbox.isChecked()
        config.setdefault("upload", {})["pause_after_open"] = False
        return config

    def start_login(self) -> None:
        self.login_event = threading.Event()
        config = self.runtime_config()

        def task(worker: TaskWorker) -> str:
            def wait_for_save() -> None:
                worker.waiting_for_login.emit()
                print("浏览器已打开。完成登录后点击窗口里的“保存登录状态”。")
                assert self.login_event is not None
                self.login_event.wait()

            DouyinUploader(config).login(wait_for_user=wait_for_save)
            return "登录状态已保存"

        self.start_task("登录", task)

    def save_login_state(self) -> None:
        if self.login_event is None:
            return
        self.append_log("正在保存登录状态...\n")
        self.login_event.set()
        self.save_login_button.setEnabled(False)

    def start_parse(self) -> None:
        config = self.runtime_config()

        def task(_: TaskWorker) -> str:
            results = parse_invoices(config)
            self.print_parse_summary(results)
            return "解析完成"

        self.start_task("解析发票", task)

    def start_upload(self) -> None:
        config = self.runtime_config()

        def task(_: TaskWorker) -> str:
            DouyinUploader(config).upload_from_records()
            return "上传流程完成"

        self.start_task("上传发票", task)

    def start_run_all(self) -> None:
        config = self.runtime_config()

        def task(_: TaskWorker) -> str:
            results = parse_invoices(config)
            self.print_parse_summary(results)
            DouyinUploader(config).upload_from_records()
            return "全流程完成"

        self.start_task("全流程", task)

    def print_parse_summary(self, results: list[InvoiceParseResult]) -> None:
        total = len(results)
        success = sum(1 for result in results if result.status == "parsed")
        failed = total - success
        print(f"处理完成：共 {total} 个 PDF，成功 {success} 个，失败 {failed} 个。")
        for result in results:
            target = result.copied_file if result.copied_file else ""
            print(
                f"[{result.status}] {Path(result.source_file).name} -> "
                f"{target} {result.message}"
            )

    def start_task(self, name: str, task) -> None:
        if self.thread is not None:
            QtWidgets.QMessageBox.information(self, "任务运行中", "当前任务尚未结束。")
            return

        self.set_busy(True)
        self.status_label.setText(f"{name}中...")
        self.append_log(f"\n==== {name} ====\n")

        self.thread = QtCore.QThread(self)
        self.worker = TaskWorker(task)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.log.connect(self.append_log)
        self.worker.waiting_for_login.connect(self.on_login_waiting)
        self.worker.finished.connect(self.on_task_finished)
        self.worker.failed.connect(self.on_task_failed)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.failed.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.cleanup_thread)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.start()

    @QtCore.Slot()
    def on_login_waiting(self) -> None:
        self.save_login_button.setEnabled(True)
        self.status_label.setText("等待保存登录状态")

    @QtCore.Slot(str)
    def on_task_finished(self, message: str) -> None:
        self.append_log(f"{message}\n")
        self.status_label.setText(message)

    @QtCore.Slot(str)
    def on_task_failed(self, error: str) -> None:
        self.append_log(error)
        self.status_label.setText("任务失败")
        QtWidgets.QMessageBox.critical(self, "任务失败", error[-1800:])

    @QtCore.Slot()
    def cleanup_thread(self) -> None:
        self.thread = None
        self.worker = None
        self.login_event = None
        self.set_busy(False)

    def set_busy(self, busy: bool) -> None:
        for widget in (
            self.choose_folder_button,
            self.login_button,
            self.parse_button,
            self.upload_button,
            self.run_button,
            self.dry_run_checkbox,
        ):
            widget.setEnabled(not busy)
        if not busy:
            self.save_login_button.setEnabled(False)

    @QtCore.Slot(str)
    def append_log(self, text: str) -> None:
        self.log_edit.moveCursor(QtGui.QTextCursor.MoveOperation.End)
        self.log_edit.insertPlainText(text)
        self.log_edit.moveCursor(QtGui.QTextCursor.MoveOperation.End)

    def closeEvent(self, event) -> None:
        if self.thread is not None:
            QtWidgets.QMessageBox.warning(self, "任务运行中", "请等待当前任务结束后再关闭。")
            event.ignore()
            return
        event.accept()


def main() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
