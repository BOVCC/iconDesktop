"""添加/编辑应用对话框。"""
import os

from PySide6.QtCore import QFileInfo
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFileIconProvider,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from app import lnk_utils

FILE_FILTER = "程序 (*.exe *.lnk);;所有文件 (*.*)"


class AppDialog(QDialog):
    def __init__(self, parent=None, app=None):
        super().__init__(parent)
        self.setWindowTitle("编辑应用" if app else "添加应用")
        self.setMinimumWidth(480)
        self.app_data = None
        self._provider = QFileIconProvider()

        self.name_edit = QLineEdit(app.get("name", "") if app else "")
        self.path_edit = QLineEdit(app.get("path", "") if app else "")
        self.args_edit = QLineEdit(app.get("args", "") if app else "")
        self.workdir_edit = QLineEdit(app.get("workdir", "") if app else "")

        browse_btn = QPushButton("浏览…")
        browse_btn.clicked.connect(self._browse_path)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse_btn)

        wd_btn = QPushButton("浏览…")
        wd_btn.clicked.connect(self._browse_workdir)
        wd_row = QHBoxLayout()
        wd_row.addWidget(self.workdir_edit, 1)
        wd_row.addWidget(wd_btn)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(48, 48)

        form = QFormLayout()
        form.addRow("图标", self.icon_label)
        form.addRow("名称", self.name_edit)
        form.addRow("路径", path_row)
        form.addRow("启动参数", self.args_edit)
        form.addRow("工作目录", wd_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.ok_button = buttons.button(QDialogButtonBox.Ok)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

        self.path_edit.textChanged.connect(self._on_path_changed)
        self.name_edit.textChanged.connect(lambda _: self._update_ok())
        self._on_path_changed(self.path_edit.text())
        if not self.name_edit.text():
            self.name_edit.setFocus()

    def _browse_path(self):
        start = self.path_edit.text() or os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(
            self, "选择程序或快捷方式", start, FILE_FILTER
        )
        if path:
            self.path_edit.setText(path)

    def _browse_workdir(self):
        start = (
            self.workdir_edit.text()
            or os.path.dirname(self.path_edit.text())
            or os.path.expanduser("~")
        )
        path = QFileDialog.getExistingDirectory(self, "选择工作目录", start)
        if path:
            self.workdir_edit.setText(path)

    def _on_path_changed(self, text):
        path = text.strip()
        icon_path = path
        if icon_path.lower().endswith(".lnk"):
            # 预览目标图标，避免 QFileIconProvider 自带的快捷方式箭头
            source = lnk_utils.icon_source(icon_path)
            if source:
                icon_path = source
        icon = self._provider.icon(QFileInfo(icon_path)) if icon_path else QIcon()
        self.icon_label.setPixmap(icon.pixmap(48, 48))

        if path.lower().endswith(".lnk"):
            target, args, workdir = lnk_utils.resolve_lnk(path)
            self.icon_label.setToolTip(f"目标: {target}" if target else "")
            if args and not self.args_edit.text().strip():
                self.args_edit.setText(args)
            if workdir and not self.workdir_edit.text().strip():
                self.workdir_edit.setText(workdir)
        else:
            self.icon_label.setToolTip("")

        if path and not self.name_edit.text().strip():
            self.name_edit.setText(os.path.splitext(os.path.basename(path))[0])
        self._update_ok()

    def _update_ok(self):
        ready = bool(
            self.path_edit.text().strip() and self.name_edit.text().strip()
        )
        self.ok_button.setEnabled(ready)

    def accept(self):
        self.app_data = {
            "name": self.name_edit.text().strip(),
            "path": os.path.normpath(self.path_edit.text().strip()),
            "args": self.args_edit.text().strip(),
            "workdir": self.workdir_edit.text().strip(),
        }
        super().accept()
