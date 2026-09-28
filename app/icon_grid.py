"""图标网格：QListWidget IconMode，支持点击启动、拖拽排序、右键菜单、搜索过滤。"""
from PySide6.QtCore import QFileInfo, QSize, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QFileIconProvider, QListWidget, QListWidgetItem, QMenu

from app import launcher, lnk_utils

DATA_ROLE = Qt.UserRole


class IconGrid(QListWidget):
    app_launched = Signal(dict)
    launch_failed = Signal(str)
    hide_requested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._provider = QFileIconProvider()
        self._icons = {}
        self._launch_mode = "click"

        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(64, 64))
        self.setGridSize(QSize(108, 122))
        self.setSpacing(6)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Snap)
        self.setWordWrap(True)
        self.setDragDropMode(QListWidget.InternalMove)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.itemClicked.connect(self._on_clicked)
        self.itemActivated.connect(self._on_activated)

    # ---- 数据 ----
    def populate(self, apps, order=None):
        """apps: [{name, path, args, workdir, is_manual}]，按 order 中的路径优先排列。"""
        self.clear()
        order = order or []
        rank = {p: i for i, p in enumerate(order)}

        def sort_key(app):
            return (rank.get(app["path"], len(rank)), app["name"].lower())

        for app in sorted(apps, key=sort_key):
            item = QListWidgetItem(self._icon_for(app["path"]), app["name"])
            item.setData(DATA_ROLE, app)
            tip = app["path"]
            if app.get("args"):
                tip += f" {app['args']}"
            item.setToolTip(tip)
            self.addItem(item)

    def apps(self):
        """按当前视觉顺序返回应用列表。"""
        return [self.item(i).data(DATA_ROLE) for i in range(self.count())]

    def set_launch_mode(self, mode):
        self._launch_mode = mode

    def filter(self, text):
        text = text.strip().lower()
        for i in range(self.count()):
            hit = not text or text in self.item(i).text().lower()
            self.setRowHidden(i, not hit)

    # ---- 图标 ----
    def _icon_for(self, path):
        if path not in self._icons:
            self._icons[path] = self._extract_icon(path)
        return self._icons[path]

    def _extract_icon(self, path):
        path = str(path)
        if path.lower().endswith(".lnk"):
            # 从 lnk 指向的目标提取图标，避免 QFileIconProvider 自带的快捷方式箭头
            source = lnk_utils.icon_source(path)
            if source:
                icon = self._provider.icon(QFileInfo(source))
                if not icon.isNull():
                    return icon
        icon = self._provider.icon(QFileInfo(path))
        if icon.isNull():
            icon = self._provider.icon(QFileIconProvider.File)
        return icon

    # ---- 交互 ----
    def _on_clicked(self, item):
        if self._launch_mode == "click":
            self._launch(item)

    def _on_activated(self, item):
        # Enter 键或双击触发；单击模式下启动已由 _on_clicked 处理
        if self._launch_mode != "click":
            self._launch(item)

    def _launch(self, item):
        app = item.data(DATA_ROLE)
        try:
            launcher.launch(app["path"], app.get("args", ""), app.get("workdir", ""))
        except launcher.LaunchError as exc:
            self.launch_failed.emit(str(exc))
            return
        self.app_launched.emit(app)

    def _show_menu(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return
        app = item.data(DATA_ROLE)
        menu = QMenu(self)
        act_open = menu.addAction("打开(&O)")
        act_hide = menu.addAction("隐藏(&H)")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_open:
            self._launch(item)
        elif chosen is act_hide:
            self.hide_requested.emit(app)
