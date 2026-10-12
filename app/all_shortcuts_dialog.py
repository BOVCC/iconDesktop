"""「全部快捷方式」窗口：开始菜单与桌面上的快捷方式，多选后加入图标桌面。

布局与展示沿用主界面同一套：分页网格（IconGrid，可 Ctrl+滚轮缩放）、右侧
翻页栏、搜索过滤、格子宽高比 2:3 —— 因此看起来和图标桌面完全一致，只是换
成多选：单击切换选中、Shift 连选、Ctrl+A 全选。

已在图标桌面上的（同名快捷方式）会打对勾角标并淡化名称，仍然可以选中：
添加时会复用已有的那个快捷方式，不会产生重复图标。
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app import scanner
from app.icon_grid import IconGrid, PageBar
from app.shortcut_sources import collect_shortcuts
from app.theme import build_style
from app.theme import colors as theme_colors


class AllShortcutsDialog(QDialog):
    """多选开始菜单/桌面快捷方式，确定后由主窗口加入「快捷方式」文件夹。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("全部快捷方式")
        self.setStyleSheet(build_style(theme_colors()))
        self.resize(900, 620)
        self.setMinimumSize(560, 400)
        self._total = 0

        self.search_box = QLineEdit()
        self.search_box.setObjectName("search")
        self.search_box.setPlaceholderText("搜索快捷方式…")
        self.search_box.setClearButtonEnabled(True)

        reselect_btn = QPushButton("全选")
        reselect_btn.setToolTip("选中当前列表里的全部快捷方式")
        reselect_btn.clicked.connect(self.grid_select_all)
        clear_btn = QPushButton("清空选择")
        clear_btn.clicked.connect(self.grid_clear_selection)

        topbar = QWidget()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        top.setContentsMargins(12, 10, 12, 10)
        top.setSpacing(8)
        top.addWidget(self.search_box, 1)
        top.addWidget(reselect_btn)
        top.addWidget(clear_btn)

        self.grid = IconGrid()
        self.grid.set_select_mode(True)
        self.grid.selection_changed.connect(self._update_count)
        self.search_box.textChanged.connect(self.grid.filter)

        self.page_bar = PageBar()
        self.grid.page_changed.connect(self.page_bar.set_pages)
        self.page_bar.page_requested.connect(self.grid.goto_page)
        self.grid.set_page_bar(self.page_bar)

        body = QWidget()
        layout = QHBoxLayout(body)
        layout.setContentsMargins(12, 10, 12, 8)
        layout.setSpacing(8)
        layout.addWidget(self.grid, 1)
        layout.addWidget(self.page_bar)

        self.hint_label = QLabel("单击图标选中/取消，Shift 连选，滚轮或右侧页位点翻页")
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        self.add_btn = QPushButton("添加到图标桌面")
        self.add_btn.setEnabled(False)
        self.add_btn.setDefault(True)
        self.add_btn.clicked.connect(self.accept)

        footer = QWidget()
        footer.setObjectName("footerbar")
        bottom = QHBoxLayout(footer)
        bottom.setContentsMargins(12, 10, 12, 10)
        bottom.setSpacing(8)
        bottom.addWidget(self.hint_label)
        bottom.addStretch(1)
        bottom.addWidget(cancel_btn)
        bottom.addWidget(self.add_btn)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(topbar)
        outer.addWidget(body, 1)
        outer.addWidget(footer)

        self.reload()

    # ---- 数据 ----
    def reload(self):
        """重新收集开始菜单/桌面上的快捷方式并填充网格。"""
        entries = collect_shortcuts()
        existing = self._existing_names()
        for entry in entries:
            if entry["name"].lower() in existing:
                entry["tip"] = f"已在图标桌面（同名快捷方式）\n{entry['tip']}"
        self._total = len(entries)
        # 几百项一次性提取图标要好几秒：先摆好名称，图标分批补
        self.grid.populate(entries, lazy_icons=True)
        for entry in entries:
            if entry["name"].lower() in existing:
                self.grid.set_badge(entry["path"])
        self._update_count()

    @staticmethod
    def _existing_names():
        """图标桌面上已有的快捷方式名称（不含扩展名，小写）。"""
        names = set()
        for app in scanner.scan_folder():
            stem = os.path.splitext(os.path.basename(app["path"]))[0]
            if stem:
                names.add(stem.lower())
        return names

    def selected_apps(self):
        """选中的应用（按显示顺序），供主窗口加入「快捷方式」文件夹。"""
        return self.grid.selected_apps()

    # ---- 交互 ----
    def grid_select_all(self):
        self.grid.select_all()

    def grid_clear_selection(self):
        self.grid.clear_selection()

    def _update_count(self):
        count = len(self.grid.selected_paths())
        self.add_btn.setEnabled(count > 0)
        self.add_btn.setText(f"添加到图标桌面（{count}）" if count else "添加到图标桌面")
        if count:
            self.hint_label.setText(f"已选 {count} 项，共收集到 {self._total} 个快捷方式")
        else:
            self.hint_label.setText("单击图标选中/取消，Shift 连选，滚轮或右侧页位点翻页")

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.reject()
            return
        super().keyPressEvent(event)
