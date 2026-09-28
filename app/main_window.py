"""主窗口：搜索栏 + 图标网格 + 右键菜单 + 设置。"""
import ctypes
import os
import shutil
import sys

from PySide6.QtCore import QEvent, QRect, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import lnk_utils, scanner, title_bar
from app.add_dialog import AppDialog
from app.config import Config
from app.icon_grid import IconGrid
from app.theme import apply_theme, apply_titlebar_theme
from app.theme import colors as theme_colors


def build_style(c):
    """叶子控件样式表：颜色取自当前主题，切换主题后需重新调用。"""
    return f"""
QListWidget {{
    background: {c['bg']};
    border: none;
}}
QListWidget::item {{
    border-radius: 8px;
    padding: 4px 2px;
    color: {c['text']};
}}
QListWidget::item:hover {{
    background: {c['hover']};
}}
QListWidget::item:selected {{
    background: {c['selected']};
    color: {c['text']};
}}
QLineEdit#search {{
    background: {c['field']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 15px;
    padding: 5px 12px;
}}
QWidget#titlebar {{
    background: {c['titlebar']};
    border-bottom: 1px solid {c['border']};
}}
QWidget#titlebar QLabel {{
    background: transparent;
    color: {c['text']};
}}
QToolButton#winbtn {{
    background: transparent;
    border: none;
}}
QToolButton#winbtn:hover {{
    background: {c['hover']};
}}
QToolButton#winbtn:pressed {{
    background: {c['selected']};
}}
QToolButton#closebtn {{
    background: transparent;
    border: none;
}}
QToolButton#closebtn:hover {{
    background: #e81123;
}}
QToolButton#closebtn:pressed {{
    background: #c50f1f;
}}
"""


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = Config()
        self._max_drag_origin = None    # 最大化标题栏拖动监视的按下位置
        self._max_drag_timer = None
        self.setWindowTitle("iconDesktop")
        self.resize(960, 640)
        self.setMinimumSize(560, 400)
        # 隐藏系统边框，改用自绘标题栏；拖动/缩放/贴靠由 WM_NCHITTEST 交还系统
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.title_bar = title_bar.TitleBar(self)
        self._apply_theme()
        self._restore_window()
        # 顶部工具条
        self.search_box = QLineEdit()
        self.search_box.setObjectName("search")
        self.search_box.setPlaceholderText("搜索应用…")
        self.search_box.setClearButtonEnabled(True)

        add_exe_btn = QPushButton("添加EXE")
        add_exe_btn.clicked.connect(self.add_exe_files)

        add_btn = QPushButton("添加应用")
        add_btn.clicked.connect(self.add_app)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._reload_apps)

        top = QHBoxLayout()
        top.addWidget(self.search_box, 1)
        top.addWidget(add_exe_btn)
        top.addWidget(add_btn)
        top.addWidget(refresh_btn)
        top.addWidget(self._build_settings_button())

        # 图标网格
        self.grid = IconGrid()
        self.grid.set_launch_mode(self.config.settings["launch_on"])
        self.grid.app_launched.connect(self._on_app_launched)
        self.grid.launch_failed.connect(self._on_launch_failed)
        self.grid.hide_requested.connect(self.hide_app)
        self.search_box.textChanged.connect(self.grid.filter)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.title_bar)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 12, 12, 8)
        layout.addLayout(top)
        layout.addWidget(self.grid, 1)
        outer.addWidget(body, 1)
        self.setCentralWidget(central)

        self._reload_apps()

    # ---- 主题 ----
    def _apply_theme(self):
        """把配置里的主题应用到整个应用，并刷新窗口样式表与标题栏。"""
        theme = self.config.settings["theme"]
        app = QApplication.instance()
        apply_theme(app, theme)
        self.setStyleSheet(build_style(theme_colors()))
        self.title_bar.refresh(theme_colors())
        apply_titlebar_theme(self, theme)

    # ---- 原生窗口行为 ----
    def _dbg(self, text):
        import os
        if os.environ.get("ICONDBG"):
            print(f"[DBG] {text}", flush=True)

    def event(self, event):
        # Qt 会吞掉非客户区鼠标消息，原生 WM_NCLBUTTONDOWN 的缩放循环不会
        # 触发：边缘按下时改调 startSystemResize 让系统接手缩放
        if event.type() == QEvent.Type.NonClientAreaMouseButtonPress:
            handle = self.windowHandle()
            edges = title_bar.resize_edges_at(self, self.mapFromGlobal(QCursor.pos()))
            if handle is not None and edges and handle.startSystemResize(edges):
                self._dbg(f"resize started edges={int(edges)}")
                return True
        elif event.type() == QEvent.Type.NonClientAreaMouseButtonRelease:
            self._stop_caption_drag_watch()
        return super().event(event)

    def nativeEvent(self, eventType, message):
        """窗口原生消息：缩放光标 + WM_NCHITTEST + 最大化标题栏拖动/双击。"""
        cursor = title_bar.handle_set_cursor(eventType, message)
        if cursor is not None:
            return True, cursor
        result = title_bar.handle_hit_test(self, eventType, message)
        if result is not None:
            return True, result
        if title_bar.is_caption_press(self, eventType, message):
            if self.isMaximized():
                # 最大化时吞下标题栏按下：放行会让 Qt 立即启动移动并瞬间
                # 还原窗口（双击还原时表现为闪烁）。改由拖动监视器实现
                # "拖动先还原再移动"；普通状态放行，走 Qt 的移动逻辑
                self._begin_max_caption_drag()
                return True, 0
            return super().nativeEvent(eventType, message)
        if title_bar.handle_caption_dblclick(self, eventType, message):
            self._stop_caption_drag_watch()
            return True, 0
        return super().nativeEvent(eventType, message)

    def _begin_max_caption_drag(self):
        """最大化时按下标题栏：开始监视，拖动超过阈值先还原再交给系统拖动。"""
        self._max_drag_origin = QCursor.pos()
        if self._max_drag_timer is None:
            self._max_drag_timer = QTimer(self)
            self._max_drag_timer.setInterval(25)
            self._max_drag_timer.timeout.connect(self._check_max_caption_drag)
        self._max_drag_timer.start()

    def _stop_caption_drag_watch(self):
        self._max_drag_origin = None
        if self._max_drag_timer is not None:
            self._max_drag_timer.stop()

    def _check_max_caption_drag(self):
        if sys.platform != "win32":
            return
        if not ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000:  # 左键已松开
            self._stop_caption_drag_watch()
            return
        origin = self._max_drag_origin
        if origin is None or (QCursor.pos() - origin).manhattanLength() < 10:
            return
        self._stop_caption_drag_watch()
        self._restore_and_drag(QCursor.pos())

    def _restore_and_drag(self, cursor):
        """还原窗口，让光标按原水平比例落在标题栏上，再交给系统继续拖动。"""
        max_rect = self.geometry()
        normal = self.normalGeometry()
        if normal.width() < 100 or normal.height() < 100:
            normal = QRect(0, 0, 960, 640)
        ratio = max(0.0, min(1.0, (cursor.x() - max_rect.left()) / max_rect.width()))
        self.showNormal()
        self.setGeometry(
            round(cursor.x() - ratio * normal.width()),
            max(0, cursor.y() - 19),
            normal.width(),
            normal.height(),
        )
        handle = self.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            self.title_bar.sync_maximize_state()

    # ---- 设置菜单 ----
    def _build_settings_button(self):
        menu = QMenu(self)
        self.dark_action = QAction("深色模式", menu, checkable=True)
        self.dark_action.setChecked(self.config.settings["theme"] == "dark")
        self.dark_action.toggled.connect(self._on_theme_toggled)
        menu.addAction(self.dark_action)
        menu.addSeparator()

        self.minimize_action = QAction(
            "启动后最小化窗口", menu, checkable=True
        )
        self.minimize_action.setChecked(
            self.config.settings["minimize_after_launch"]
        )
        self.minimize_action.toggled.connect(self._on_minimize_toggled)
        menu.addAction(self.minimize_action)
        menu.addSeparator()

        group = QActionGroup(menu)
        self.click_action = QAction("单击启动", menu, checkable=True)
        self.double_action = QAction("双击启动", menu, checkable=True)
        for act in (self.click_action, self.double_action):
            group.addAction(act)
            menu.addAction(act)
        default = self.config.settings["launch_on"]
        (self.click_action if default == "click" else self.double_action).setChecked(
            True
        )
        self.click_action.toggled.connect(self._on_launch_mode_changed)

        button = QToolButton()
        button.setText("设置")
        button.setMenu(menu)
        button.setPopupMode(QToolButton.InstantPopup)
        return button

    # ---- 启动清理 ----
    def startup_cleanup(self):
        """启动时执行：迁移旧版手动应用到快捷方式文件夹，并清理失效配置。

        配置里已找不到对应图标（文件夹中的 .lnk/.exe）的隐藏、排序信息
        会被一并删除。
        """
        changed = bool(self.config.legacy_manual_apps)
        for app in self.config.legacy_manual_apps:
            self._add_to_folder(app)
        self.config.legacy_manual_apps = []

        scanned = scanner.scan_folder()
        names = {a["name"] for a in scanned}
        paths = {a["path"] for a in scanned}
        if self.config.prune_stale(names, paths):
            changed = True
        if changed:
            self.config.save()
            self._reload_apps()

    # ---- 数据装载 ----
    def _reload_apps(self):
        hidden = self.config.hidden
        apps = [a for a in scanner.scan_folder() if a["name"] not in hidden]
        self.grid.populate(apps, self.config.order)
        if apps:
            self.statusBar().showMessage(f"共 {self.grid.count()} 个应用")
        else:
            self.statusBar().showMessage(
                "快捷方式文件夹为空：请将 .lnk/.exe 放入程序同级的「快捷方式」文件夹"
            )

    def _restore_window(self):
        win = self.config.data.get("window")
        if not isinstance(win, dict):
            return
        try:
            rect = QRect(int(win["x"]), int(win["y"]), int(win["w"]), int(win["h"]))
        except (KeyError, TypeError, ValueError):
            return
        self.setGeometry(rect)

    # ---- 增删改 ----
    def add_exe_files(self):
        """直接选择 exe/lnk 文件，多选后以快捷方式形式加入文件夹。"""
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择要添加的程序", "", "程序 (*.exe *.lnk);;所有文件 (*.*)"
        )
        if not paths:
            return
        added = 0
        for path in paths:
            name = os.path.splitext(os.path.basename(path))[0]
            data = {
                "name": name,
                "path": os.path.normpath(path),
                "args": "",
                "workdir": "",
            }
            if self._add_to_folder(data):
                added += 1
        if added:
            self._reload_apps()

    def add_app(self):
        dialog = AppDialog(self)
        if dialog.exec() == QDialog.Accepted and dialog.app_data:
            if self._add_to_folder(dialog.app_data):
                self._reload_apps()

    def _add_to_folder(self, app):
        """把选中的程序以快捷方式形式放入「快捷方式」文件夹。

        目标已失效（文件不存在）时直接忽略并返回 False，由调用方决定提示。
        """
        path = app["path"]
        if not path or not os.path.exists(path):
            return False
        name = app["name"]
        args = app.get("args", "")
        workdir = app.get("workdir", "")
        folder = scanner.shortcut_folder()
        try:
            if path.lower().endswith(".lnk"):
                target, src_args, src_workdir = lnk_utils.resolve_lnk(path)
                if target:
                    lnk_utils.create_shortcut(
                        folder,
                        name,
                        target,
                        args or src_args,
                        workdir or src_workdir,
                        lnk_utils.get_icon_location(path),
                    )
                else:
                    # 解析不出目标（如商店应用）：原样复制，保留全部信息
                    shutil.copyfile(path, lnk_utils.unique_lnk_path(folder, name))
            else:
                lnk_utils.create_shortcut(folder, name, path, args, workdir)
        except Exception as exc:
            QMessageBox.warning(self, "添加失败", f"无法创建快捷方式：{exc}")
            return False
        return True

    def hide_app(self, app):
        self.config.hide(app["name"])
        self.config.save()
        self._reload_apps()

    # ---- 启动反馈 ----
    def _on_app_launched(self, app):
        self.statusBar().showMessage(f"已启动: {app['name']}")
        if self.minimize_action.isChecked():
            self.showMinimized()

    def _on_launch_failed(self, message):
        self.statusBar().clearMessage()
        QMessageBox.warning(self, "启动失败", message)

    # ---- 设置变更 ----
    def _on_theme_toggled(self, checked):
        theme = "dark" if checked else "light"
        self.config.settings["theme"] = theme
        self.config.save()
        self._apply_theme()

    def _on_minimize_toggled(self, checked):
        self.config.settings["minimize_after_launch"] = checked
        self.config.save()

    def _on_launch_mode_changed(self):
        mode = "click" if self.click_action.isChecked() else "double"
        self.config.settings["launch_on"] = mode
        self.config.save()
        self.grid.set_launch_mode(mode)

    # ---- 退出前持久化 ----
    def closeEvent(self, event):
        self.config.set_order([a["path"] for a in self.grid.apps()])
        self.config.data["window"] = {
            "x": self.x(),
            "y": self.y(),
            "w": self.width(),
            "h": self.height(),
        }
        self.config.save()
        super().closeEvent(event)
