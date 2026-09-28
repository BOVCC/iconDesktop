"""主窗口：搜索栏 + 图标网格 + 右键菜单 + 设置。"""
import ctypes
import os
import shutil
import sys

from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor, QCursor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app import lnk_utils, scanner, title_bar
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
QWidget#topbar {{
    background: {c['titlebar']};
    border-bottom: 1px solid {c['border']};
}}
QWidget#topbar QPushButton {{
    background: {c['button']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 14px;
}}
QWidget#topbar QPushButton:hover {{
    background: {c['hover']};
}}
QWidget#topbar QPushButton:pressed {{
    background: {c['selected']};
}}
QWidget#topbar QToolButton {{
    background: {c['button']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 6px 12px;
}}
QWidget#topbar QToolButton:hover {{
    background: {c['hover']};
}}
QWidget#topbar QToolButton:pressed {{
    background: {c['selected']};
}}
QWidget#topbar QToolButton::menu-indicator {{
    subcontrol-origin: padding;
    subcontrol-position: center right;
    right: 4px;
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


def _app_icon_paths():
    """多尺寸 .ico 的查找路径：打包资源优先，其次源码目录。"""
    paths = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            paths.append(os.path.join(meipass, "icon", "iconDesktop.ico"))
    paths.append(
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "icon",
            "iconDesktop.ico",
        )
    )
    return paths


def make_app_icon():
    """应用图标：多尺寸 .ico（托盘/标题栏/任务栏共用），资源缺失时退回程序化绘制。"""
    for path in _app_icon_paths():
        if os.path.isfile(path):
            return QIcon(path)
    size = 64
    margin = size * 0.09
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#3d7eff"))
    painter.drawRoundedRect(
        QRectF(margin, margin, size - 2 * margin, size - 2 * margin),
        size * 0.22,
        size * 0.22,
    )
    painter.setBrush(Qt.white)
    dot = size * 0.17
    cell = (size - 2 * margin) / 2
    for row in range(2):
        for col in range(2):
            painter.drawEllipse(
                QPointF(margin + cell * (col + 0.5), margin + cell * (row + 0.5)),
                dot / 2,
                dot / 2,
            )
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.config = Config()
        self._max_drag_origin = None    # 最大化标题栏拖动监视的按下位置
        self._max_drag_timer = None
        self._force_quit = False        # 托盘「退出」为真关闭，普通关闭藏进托盘
        self.setWindowTitle("iconDesktop")
        self.resize(960, 640)
        self.setMinimumSize(560, 400)
        self._app_icon = make_app_icon()
        self.setWindowIcon(self._app_icon)
        # 隐藏系统边框，改用自绘标题栏；拖动/缩放/贴靠由 WM_NCHITTEST 交还系统
        self.setWindowFlag(Qt.FramelessWindowHint)
        self.title_bar = title_bar.TitleBar(self)
        self._apply_theme()
        self._restore_window()
        self._build_tray()
        # 顶部工具条：独立操作区面板，底边框与图标网格分隔
        self.search_box = QLineEdit()
        self.search_box.setObjectName("search")
        self.search_box.setPlaceholderText("搜索应用…")
        self.search_box.setClearButtonEnabled(True)

        add_exe_btn = QPushButton("添加EXE")
        add_exe_btn.clicked.connect(self.add_exe_files)

        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._reload_apps)

        topbar = QWidget()
        topbar.setObjectName("topbar")
        top = QHBoxLayout(topbar)
        top.setContentsMargins(12, 10, 12, 10)
        top.setSpacing(8)
        top.addWidget(self.search_box, 1)
        top.addWidget(add_exe_btn)
        top.addWidget(refresh_btn)
        top.addWidget(self._build_settings_button())

        # 图标网格
        self.grid = IconGrid()
        self.grid.set_launch_mode(self.config.settings["launch_on"])
        self.grid.app_launched.connect(self._on_app_launched)
        self.grid.launch_failed.connect(self._on_launch_failed)
        self.grid.delete_requested.connect(self.delete_app)
        self.grid.layout_changed.connect(self._persist_layout)
        self.search_box.textChanged.connect(self.grid.filter)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self.title_bar)
        outer.addWidget(topbar)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(12, 10, 12, 8)
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
                # Qt.Edge/Edges 不能转 int（新版 PySide6 的枚举），直接打印
                self._dbg(f"resize started edges={edges}")
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
        self.grid.populate(scanner.scan_folder(), self.config.order, self.config.positions)
        if self.grid.count():
            self.statusBar().showMessage(f"共 {self.grid.count()} 个应用")
        else:
            self.statusBar().showMessage(
                "快捷方式文件夹为空：请将 .lnk/.exe 放入用户数据目录的「快捷方式」文件夹"
            )

    def _persist_layout(self):
        """保存图标顺序与格子坐标；拖拽落位后立即调用，防托盘常驻时丢布局。"""
        self.config.set_order([a["path"] for a in self.grid.apps()])
        self.config.set_positions(self.grid.positions())
        self.config.save()

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

    def delete_app(self, app):
        """删除图标：连同「快捷方式」文件夹里的对应文件一并删除。"""
        path = app["path"]
        answer = QMessageBox.question(
            self,
            "删除应用",
            f"确定删除「{app['name']}」？\n将同时删除快捷方式文件夹中的 {os.path.basename(path)}",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if os.path.isfile(path):
                os.remove(path)
        except OSError as exc:
            QMessageBox.warning(self, "删除失败", f"无法删除 {os.path.basename(path)}：{exc}")
            return
        # 重新扫描并清理配置里已失效的隐藏/排序/坐标
        self.startup_cleanup()
        self.statusBar().showMessage(f"已删除: {app['name']}", 4000)

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

    # ---- 托盘 ----
    def _build_tray(self):
        """系统托盘：左键单击显示/隐藏主窗口，菜单里可真正退出。"""
        self.tray = QSystemTrayIcon(self._app_icon, self)
        self.tray.setToolTip("iconDesktop")
        menu = QMenu(self)
        toggle_action = QAction("显示/隐藏主窗口", menu)
        toggle_action.triggered.connect(self._toggle_from_tray)
        menu.addAction(toggle_action)
        menu.addSeparator()
        quit_action = QAction("退出", menu)
        quit_action.triggered.connect(self._save_and_quit)
        menu.addAction(quit_action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def present(self):
        """把主窗口唤到前台并置于最上（托盘唤回与第二个实例请求共用）。"""
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _toggle_from_tray(self):
        if self.isVisible() and not self.isMinimized():
            self.hide()
        else:
            self.present()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_from_tray()

    def _save_and_quit(self):
        """保存状态后退出：托盘菜单「退出」与 Ctrl+C 共用。

        窗口隐藏时 close() 不会触发 lastWindowClosed（应用看不到任何可见
        窗口在关闭），必须显式保存状态并结束事件循环。
        """
        self._force_quit = True
        self._save_state()
        QApplication.quit()

    # ---- 退出前持久化 ----
    def _save_state(self):
        """保存图标布局与窗口几何到配置。"""
        self._persist_layout()
        self.config.data["window"] = {
            "x": self.x(),
            "y": self.y(),
            "w": self.width(),
            "h": self.height(),
        }
        self.config.save()

    def closeEvent(self, event):
        self._save_state()
        if not self._force_quit and self.tray.isVisible():
            # 关闭按钮 = 最小化到托盘；真正退出走托盘菜单的「退出」
            event.ignore()
            self.hide()
            return
        super().closeEvent(event)
