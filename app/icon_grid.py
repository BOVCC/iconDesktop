"""图标网格：QListWidget IconMode，自由格子摆放，支持点击启动、拖拽排序、右键菜单、搜索过滤。

每个图标占一个网格格子，坐标持久化在配置里，允许中间留空（与桌面图标一致）。
新图标放入第一个空格子；没有坐标的旧配置按 order 优先、名称次序摆放。

拖拽排序为自实现，不用 Qt 内置的 InternalMove（它在 IconMode 下落点与
显示网格错位，条目会跳格）：
- 按住图标移动超过系统拖拽阈值后进入拖拽态；
- 拖动全程在光标吸附到的网格格子上实时绘制半透明图标阴影，松手即落在
  阴影处：空格子直接落位，已占用的格子两个图标互换；
- 视口外松手吸附到视口边缘；按 Esc 取消；网格边缘自动滚动。
"""
from PySide6.QtCore import QFileInfo, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileIconProvider,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStyle,
    QStyleOptionViewItem,
)

from app import launcher, lnk_utils
from app.theme import colors as theme_colors

DATA_ROLE = Qt.UserRole

DRAG_EDGE = 28          # 距视口边缘多少像素内触发自动滚动
DRAG_OPACITY = 0.45     # 落点阴影透明度


class IconGrid(QListWidget):
    app_launched = Signal(dict)
    launch_failed = Signal(str)
    delete_requested = Signal(dict)
    layout_changed = Signal()   # 拖拽落位后发出，供主窗口立即保存坐标

    def __init__(self, parent=None):
        super().__init__(parent)
        self._provider = QFileIconProvider()
        self._icons = {}
        self._launch_mode = "click"
        self._cells = {}    # path -> (col, row)

        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(64, 64))
        self.setGridSize(QSize(108, 122))
        self.setSpacing(6)
        self.setResizeMode(QListWidget.Fixed)
        self.setMovement(QListWidget.Free)
        self.setDragDropMode(QListWidget.NoDragDrop)
        self.setWordWrap(True)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.itemClicked.connect(self._on_clicked)
        self.itemActivated.connect(self._on_activated)

        # 自实现拖拽状态
        self._press_item = None
        self._press_pos = QPoint()
        self._drag_active = False
        self._drag_item = None
        self._drag_path = None
        self._origin_cell = (-1, -1)    # 拖动条目的原格子
        self._target_cell = (-1, -1)    # 当前吸附到的格子
        self._cursor_pos = QPoint()
        self._scroll_step = 0
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(16)
        self._scroll_timer.timeout.connect(self._auto_scroll_tick)

    # ---- 数据 ----
    def populate(self, apps, order=None, positions=None):
        """apps: [{name, path, args, workdir}]。

        坐标取自 positions（{路径: [列, 行]}），无效或冲突的坐标忽略；
        没有坐标的条目在视口宽度就绪后按 order 优先、名称次序流式填充
        （见 _assign_pending_cells）。
        """
        self.clear()
        self._cells = {}
        occupied = set()
        paths = {a["path"] for a in apps}
        for path, cell in (positions or {}).items():
            if path not in paths or not self._valid_cell(cell):
                continue
            cell = (int(cell[0]), int(cell[1]))
            if cell in occupied:
                continue
            self._cells[path] = cell
            occupied.add(cell)

        rank = {p: i for i, p in enumerate(order or [])}

        def sort_key(app):
            return (rank.get(app["path"], len(rank)), app["name"].lower())

        for app in sorted(apps, key=sort_key):
            item = QListWidgetItem(self._icon_for(app["path"]), app["name"])
            item.setData(DATA_ROLE, app)
            item.setSizeHint(self.gridSize())
            tip = app["path"]
            if app.get("args"):
                tip += f" {app['args']}"
            item.setToolTip(tip)
            self.addItem(item)
        self._apply_positions()

    def apps(self):
        """按格子坐标（行优先）返回应用列表。"""
        entries = []
        for i in range(self.count()):
            item = self.item(i)
            path = item.data(DATA_ROLE)["path"]
            col, row = self._cells.get(path, (1 << 30, 1 << 30))
            entries.append(((row, col), i, item))
        entries.sort(key=lambda e: e[:2])
        return [e[2].data(DATA_ROLE) for e in entries]

    def positions(self):
        """当前格子坐标（供配置保存）。"""
        return {path: [c, r] for path, (c, r) in self._cells.items()}

    def set_launch_mode(self, mode):
        self._launch_mode = mode

    def filter(self, text):
        text = text.strip().lower()
        for i in range(self.count()):
            hit = not text or text in self.item(i).text().lower()
            self.setRowHidden(i, not hit)

    # ---- 摆放 ----
    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._assign_pending_cells)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self._assign_pending_cells)

    def _assign_pending_cells(self):
        """给还没有坐标的条目按流式顺序分配格子（需要视口宽度定每行列数）。"""
        pending = []
        for i in range(self.count()):
            try:
                path = self.item(i).data(DATA_ROLE)["path"]
            except RuntimeError:  # 条目已随 populate 清空销毁
                return
            if path not in self._cells:
                pending.append(path)
        if not pending:
            return
        cols = self._flow_cols()
        if cols <= 0:
            return  # 视口未就绪，等下一次 show/resize 再分配
        occupied = set(self._cells.values())
        for path in pending:
            cell = self._first_free_cell(occupied, cols)
            self._cells[path] = cell
            occupied.add(cell)
        self._apply_positions()

    def _flow_cols(self):
        """当前视口每行能放几个格子；未布局时返回 0。"""
        gw = self.gridSize().width()
        vp_w = self.viewport().width()
        if gw <= 0 or vp_w < gw:
            return 0
        return max(1, vp_w // gw)

    @staticmethod
    def _valid_cell(cell):
        try:
            return (
                isinstance(cell, (list, tuple))
                and len(cell) == 2
                and int(cell[0]) >= 0
                and int(cell[1]) >= 0
            )
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _first_free_cell(occupied, cols):
        """行优先扫第一个空格子：先补前排的洞，满了另起一行。"""
        max_row = max((r for _, r in occupied), default=-1)
        for row in range(max_row + 1):
            for col in range(cols):
                if (col, row) not in occupied:
                    return col, row
        return 0, max_row + 1

    def _apply_positions(self):
        """把 self._cells 的坐标应用到条目（内容坐标）。"""
        gw, gh = self.gridSize().width(), self.gridSize().height()
        for i in range(self.count()):
            item = self.item(i)
            cell = self._cells.get(item.data(DATA_ROLE)["path"])
            if cell is None:
                continue
            self.setPositionForIndex(
                QPoint(cell[0] * gw, cell[1] * gh), self.indexFromItem(item)
            )

    def _path_at_cell(self, cell):
        for path, c in self._cells.items():
            if c == cell:
                return path
        return None

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
        act_delete = menu.addAction("删除(&D)")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_open:
            self._launch(item)
        elif chosen is act_delete:
            self.delete_requested.emit(app)

    # ---- 拖拽排序 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_item = self.itemAt(event.position().toPoint())
            self._press_pos = event.position().toPoint()
        else:
            self._press_item = None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_active:
            self._update_drag(event.position().toPoint())
            event.accept()
            return
        if (
            self._press_item is not None
            and event.buttons() & Qt.LeftButton
            and (event.position().toPoint() - self._press_pos).manhattanLength()
            >= QApplication.startDragDistance()
        ):
            self._begin_drag()
            if self._drag_active:
                self._update_drag(event.position().toPoint())
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._drag_active:
            self._finish_drag(event.position().toPoint())
            event.accept()
            return
        self._press_item = None
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self._drag_active and event.key() == Qt.Key_Escape:
            self._end_drag()
            event.accept()
            return
        super().keyPressEvent(event)

    def _begin_drag(self):
        item = self._press_item
        self._press_item = None
        if item is None:
            return
        try:
            path = item.data(DATA_ROLE)["path"]
        except RuntimeError:  # 条目已随 populate 清空销毁
            return
        self._drag_item = item
        self._drag_path = path
        self._origin_cell = self._cells.get(path, (-1, -1))
        self._target_cell = self._origin_cell
        self._drag_active = True
        self.viewport().setCursor(Qt.ClosedHandCursor)

    def _update_drag(self, pos):
        self._cursor_pos = pos
        cell = self._target_cell_at(pos)
        if cell != self._target_cell:
            self._target_cell = cell
            self.viewport().update()
        self._update_autoscroll(pos)

    def _target_cell_at(self, pos):
        """光标吸附到的格子；视口外的位置先夹回视口。"""
        vp = self.viewport().rect()
        pos = QPoint(
            min(max(pos.x(), vp.left()), vp.right()),
            min(max(pos.y(), vp.top()), vp.bottom()),
        )
        gw, gh = self.gridSize().width(), self.gridSize().height()
        col = (pos.x() + self.horizontalScrollBar().value()) // gw
        row = (pos.y() + self.verticalScrollBar().value()) // gh
        return (int(col), int(row))

    def _finish_drag(self, pos):
        path = self._drag_path
        origin = self._origin_cell
        cell = self._target_cell_at(pos)
        self._end_drag()
        if path is None or cell == origin or origin[0] < 0:
            return
        other = self._path_at_cell(cell)
        self._cells[path] = cell
        if other is not None:
            self._cells[other] = origin
        self._apply_positions()
        self.layout_changed.emit()

    def _end_drag(self):
        self._drag_active = False
        self._drag_item = None
        self._drag_path = None
        self._origin_cell = (-1, -1)
        self._target_cell = (-1, -1)
        self._cursor_pos = QPoint()
        self._scroll_step = 0
        self._scroll_timer.stop()
        self.viewport().unsetCursor()
        self.setState(QAbstractItemView.State.NoState)
        self.viewport().update()

    # ---- 拖拽自动滚动 ----
    def _update_autoscroll(self, pos):
        height = self.viewport().height()
        distance = min(pos.y(), height - pos.y())
        if 0 <= distance < DRAG_EDGE:
            step = max(2, (DRAG_EDGE - distance) // 3)
            self._scroll_step = -step if pos.y() < height / 2 else step
        else:
            self._scroll_step = 0
        if self._scroll_step:
            self._scroll_timer.start()
        else:
            self._scroll_timer.stop()

    def _auto_scroll_tick(self):
        bar = self.verticalScrollBar()
        value = bar.value() + self._scroll_step
        if value == bar.value():
            self._scroll_timer.stop()
            return
        bar.setValue(value)
        # 滚动后光标下方的格子变了，落点预览要跟着刷新
        self._update_drag(self._cursor_pos)

    # ---- 落点阴影绘制 ----
    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._drag_active:
            return
        try:
            self._paint_drag_ghost()
        except RuntimeError:  # 拖拽中条目被 populate 清空
            self._end_drag()

    def _paint_drag_ghost(self):
        if self._target_cell[0] < 0 or self._target_cell == self._origin_cell:
            return
        rect = self._ghost_rect()
        if rect.isNull():
            return
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        # 落点格子描边
        pen = QPen(QColor(theme_colors()["selected"]))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(1, 1, -2, -2), 8, 8)
        # 半透明的图标 + 名称阴影；复用视图自身的 Item 选项，
        # 保证 IconMode 的排版（图标在上居中、文字在下）与真实条目一致
        painter.setOpacity(DRAG_OPACITY)
        opt = QStyleOptionViewItem()
        self.initViewItemOption(opt)
        opt.rect = rect
        opt.state = QStyle.State_Enabled | QStyle.State_Open
        self.itemDelegate().paint(painter, opt, self.indexFromItem(self._drag_item))
        painter.end()

    def _ghost_rect(self):
        """吸附格子在视口中的矩形。"""
        if self._target_cell[0] < 0:
            return QRect()
        gw, gh = self.gridSize().width(), self.gridSize().height()
        return QRect(
            QPoint(
                self._target_cell[0] * gw - self.horizontalScrollBar().value(),
                self._target_cell[1] * gh - self.verticalScrollBar().value(),
            ),
            QSize(gw, gh),
        )
