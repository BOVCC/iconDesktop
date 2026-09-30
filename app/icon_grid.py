"""图标网格：分页式紧凑布局，支持点击启动、拖拽整理、右键菜单、搜索过滤、缩放。

布局模型（与手机桌面一致）：
- 所有图标按 _order 顺序紧凑铺满每一页，页容量 = 列数 × 行数，由视口尺寸与
  缩放级别共同决定；不存在空洞，也没有任何滚动条（既不左右滚也不上下滚）。
- 新加入的应用自动追加到顺序末尾（最后一页的空位），不会与旧图标重叠。
- 格子宽高比固定 2:3；缩小窗口/缩放级别时图标跟着变小，最小到 40×60
  （宽2高3），再小就减少每页行列数、靠翻页容纳。
- 缩放：Ctrl+滚轮；翻页：滚轮、A/D、←/→、PgUp/PgDn、Home/End，以及右侧
  翻页栏（PageBar，点击跳转/翻页并指示当前页）。

拖拽整理为自实现：按下超过拖拽阈值后启动 QDrag，不透明的「图标+名称」
像素图由系统带着跟随光标（像素级丝滑，不吸附格子）；落点阴影（半透明
预览 + 描边）吸附到插入点格子，作为落位指引。落点分区按光标在目标
格子内的横向位置分三个区（与手机桌面一致，任意位置的图标都能触发，
不局限于屏幕两侧）：
- 中间 50% 宽度 → 与目标图标互换；
- 左 1/4 边缘 → 插入到目标图标之前：落点到原位之间的图标向原位方向
  顺移一格补位（原位在右侧时整体右移、在左侧时整体左移）；
- 右 1/4 边缘 → 对称地插入到目标图标之后；
- 拖动悬停时，受影响的图标实时动画偏移到插入后的位置（中心区不偏移），
  松手落位与预览一致，Esc 取消恢复；
- 落到页尾空白处 = 移到本页最后一个可见项之后；插入点钳制在本页内，
  不会把图标挤出本页。
"""
import math

from PySide6.QtCore import (
    QEasingCurve,
    QFileInfo,
    QMimeData,
    QPoint,
    QPointF,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF, QDrag
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileIconProvider,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QStyle,
    QStyleOptionViewItem,
    QWidget,
)

from app import launcher, lnk_utils
from app.theme import colors as theme_colors

DATA_ROLE = Qt.UserRole

DRAG_OPACITY = 0.45     # 落点阴影透明度

BASE_CELL_W = 96        # 缩放 1.0 时的格子宽度
CELL_RATIO = 1.5        # 格子 高/宽，即宽:高 = 2:3
MIN_CELL_W = 40         # 最小缩小宽度（对应高 60）
MAX_CELL_W = 200        # 最大放大宽度
ZOOM_MIN = 0.4
ZOOM_MAX = 2.2
ZOOM_STEP = 1.12        # Ctrl+滚轮每格的缩放系数

ICON_RENDER_SIZE = 256  # 图标归一化边长（覆盖最大图标尺寸 120px 及高分屏请求）


class IconGrid(QListWidget):
    app_launched = Signal(dict)
    launch_failed = Signal(str)
    delete_requested = Signal(dict)
    layout_changed = Signal()       # 拖拽落位后发出，供主窗口立即保存顺序
    page_changed = Signal(int, int)  # (当前页, 总页数)，均为 0 基
    scale_changed = Signal(float)    # 缩放级别变化（供配置保存）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._provider = QFileIconProvider()
        self._icons = {}
        self._launch_mode = "click"
        self._order = []            # 显示顺序（路径），紧凑无空洞
        self._items = {}            # path -> QListWidgetItem
        self._scale = 1.0
        self._page = 0
        self._total_pages = 1
        self._filter_text = ""
        # 布局缓存（_relayout 时更新）
        self._cols = 1
        self._rows = 1
        self._cell = QSize(BASE_CELL_W, int(BASE_CELL_W * CELL_RATIO))
        self._x_offset = 0
        self._per_page = 1
        self._page_slots = []       # 当前页展示的顺序号

        self.setViewMode(QListWidget.IconMode)
        self.setIconSize(QSize(56, 56))
        self.setGridSize(self._cell)
        self.setSpacing(6)
        self.setResizeMode(QListWidget.Fixed)
        self.setMovement(QListWidget.Free)
        self.setDragDropMode(QListWidget.NoDragDrop)
        # 自实现拖拽：QDrag 由 _begin_drag 主动发起，拖拽事件由本类
        # dragEnter/dragMove/drop 处理；保持 NoDragDrop 关闭 Qt 内置搬移
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setWordWrap(True)
        self.setSelectionMode(QListWidget.SingleSelection)
        # 分页布局：不出现任何滚动条
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
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
        self._origin_cell = (-1, -1)    # 拖动条目在当前页的格子
        self._target_cell = (-1, -1)    # 当前吸附到的格子
        self._drop_zone = "center"      # 光标在格子内的分区 left/center/right
        self._ghost_cell = (-1, -1)     # 落点阴影吸附的格子（插入点/互换目标）
        self._cursor_pos = QPoint()
        # 悬停预览动画：受影响图标从当前位置滑向插入后的位置
        self._live_pos = {}             # 各图标最近一次设置的位置 {路径: QPoint}
        self._anim_from = {}
        self._anim_to = {}
        self._drag_anim = QVariantAnimation(self)
        self._drag_anim.setDuration(180)
        self._drag_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._drag_anim.valueChanged.connect(self._anim_tick)

    # ---- 数据 ----
    def populate(self, apps, order=None):
        """apps: [{name, path, args, workdir}]；order: 期望显示顺序（路径列表）。

        显示顺序 = order 中仍存在的路径，新出现的应用按名称次序追加到末尾
        （最后一页的空位），因此新应用永远自动排列、不会压在旧图标下面。
        """
        self.clear()
        self._items = {}
        app_by_path = {}
        for app in apps:
            app_by_path[str(app["path"])] = app
        kept = []
        seen = set()
        for path in order or []:
            path = str(path)
            if path in app_by_path and path not in seen:
                kept.append(path)
                seen.add(path)
        new_apps = sorted(
            (a for p, a in app_by_path.items() if p not in seen),
            key=lambda a: a["name"].lower(),
        )
        self._order = kept + [a["path"] for a in new_apps]
        for app in app_by_path.values():
            item = QListWidgetItem(self._icon_for(app["path"]), app["name"])
            item.setData(DATA_ROLE, app)
            tip = app["path"]
            if app.get("args"):
                tip += f" {app['args']}"
            item.setToolTip(tip)
            self._items[app["path"]] = item
            self.addItem(item)
        self._relayout()

    def order(self):
        """当前显示顺序（路径列表，供配置保存）。"""
        return list(self._order)

    def apps(self):
        """按显示顺序返回应用列表。"""
        result = []
        for path in self._order:
            item = self._items.get(path)
            if item is not None:
                try:
                    result.append(item.data(DATA_ROLE))
                except RuntimeError:  # 条目已随 populate 清空销毁
                    continue
        return result

    def set_launch_mode(self, mode):
        self._launch_mode = mode

    def filter(self, text):
        self._filter_text = text.strip().lower()
        self._page = 0  # 过滤后从第一页看起
        self._relayout()

    # ---- 缩放与翻页 ----
    def set_scale(self, scale):
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            return
        scale = min(ZOOM_MAX, max(ZOOM_MIN, scale))
        if abs(scale - self._scale) < 1e-3:
            return
        self._scale = scale
        self._relayout()
        self.scale_changed.emit(self._scale)

    def scale(self):
        return self._scale

    def page_count(self):
        return self._total_pages

    def current_page(self):
        return self._page

    def goto_page(self, page):
        page = min(max(0, int(page)), self._total_pages - 1)
        if page == self._page:
            return
        self._page = page
        self._relayout()
        if self._drag_active:
            # 翻页后落点吸附与悬停预览跟着光标刷新
            self._update_drag(self._cursor_pos, force=True)

    def next_page(self):
        self.goto_page(self._page + 1)

    def prev_page(self):
        self.goto_page(self._page - 1)

    # ---- 布局 ----
    def _visible_order(self):
        """匹配当前过滤条件的顺序号列表。"""
        text = self._filter_text
        result = []
        for idx, path in enumerate(self._order):
            item = self._items.get(path)
            if item is None:
                continue
            try:
                name = item.text()
            except RuntimeError:  # 条目已随 populate 清空销毁
                continue
            if not text or text in name.lower():
                result.append(idx)
        return result

    def _compute_metrics(self):
        """由视口尺寸与缩放级别计算每页行列数与格子尺寸。

        格子先按缩放取期望宽度决定列数，再均分视口宽度（窗口缩小时图标跟着
        缩小），上下限截断：最小 40×60（宽2高3），再小就减少列数靠翻页。
        """
        vp = self.viewport()
        vw = max(1, vp.width())
        vh = max(1, vp.height())
        pref_w = BASE_CELL_W * self._scale
        cols = max(1, int(vw // pref_w))
        cell_w = vw / cols
        if cell_w < MIN_CELL_W:
            cell_w = MIN_CELL_W
            cols = max(1, int(vw // cell_w))
        elif cell_w > MAX_CELL_W:
            cell_w = MAX_CELL_W
        cell_h = cell_w * CELL_RATIO
        rows = max(1, int(vh // cell_h))
        if rows == 1 and cell_h > vh:
            # 极矮窗口：按高度收缩一格（保持 2:3），保证一行完整可见
            cell_h = max(MIN_CELL_W * CELL_RATIO, vh)
            cell_w = min(cell_w, cell_h / CELL_RATIO)
        cw, ch = int(cell_w), int(cell_h)
        self._cols = cols
        self._rows = rows
        self._cell = QSize(cw, ch)
        self._x_offset = max(0, (vw - cols * cw) // 2)
        self.setGridSize(QSize(cw, ch))

    def _relayout(self):
        """把顺序号切页：当前页摆进视口，其余隐藏。"""
        self._compute_metrics()
        visible = self._visible_order()
        per_page = max(1, self._cols * self._rows)
        self._per_page = per_page
        self._total_pages = max(1, math.ceil(len(visible) / per_page))
        if self._page >= self._total_pages:
            self._page = self._total_pages - 1
        if self._page < 0:
            self._page = 0
        slots = visible[self._page * per_page:(self._page + 1) * per_page]
        self._page_slots = slots
        # 隐藏/显示必须按「路径」判断，不能按行号：QListWidget 的行序是
        # 扫描次序，与拖拽排序/旧配置迁移后的显示顺序不一致，按行号会留下
        # 错误的可见条目压在旧位置上（表现为图标叠在一起）
        visible_paths = {self._order[oi] for oi in slots}
        rows_changed = False
        for i in range(self.count()):
            item = self.item(i)
            hide = True
            if item is not None:
                try:
                    hide = item.data(DATA_ROLE)["path"] not in visible_paths
                except (RuntimeError, TypeError, KeyError, IndexError):
                    hide = True
            if self.isRowHidden(i) != hide:
                self.setRowHidden(i, hide)
                rows_changed = True
        # 拖动中拖动项所在行保持隐藏（由落点阴影代表）。_page_slots 仍包含
        # 它：互换/插入的落点计算都要用到它的原位，行隐藏不影响这些数学
        if self._drag_path is not None:
            drag_item = self._items.get(self._drag_path)
            if drag_item is not None:
                try:
                    row = self.row(drag_item)
                    if not self.isRowHidden(row):
                        self.setRowHidden(row, True)
                        rows_changed = True
                except RuntimeError:  # 条目已随 populate 清空销毁
                    pass
        if rows_changed:
            self._schedule_reassert()
        side = max(12, int(self._cell.width() * 0.6))
        if self.iconSize().width() != side:
            self.setIconSize(QSize(side, side))
        self._assert_page_positions()
        self.page_changed.emit(self._page, self._total_pages)

    def _assert_page_positions(self):
        """把当前页图标重新摆回网格槽位。"""
        cw, ch = self._cell.width(), self._cell.height()
        for slot, order_idx in enumerate(self._page_slots):
            item = self._items.get(self._order[order_idx])
            if item is None:
                continue
            try:
                item.setSizeHint(QSize(cw, ch))
                self._set_item_pos(self._order[order_idx], self._slot_pos(slot))
            except RuntimeError:  # 条目已随 populate 清空销毁
                continue

    def _schedule_reassert(self):
        """行隐藏集合变化后，安排一次「重申本页坐标」。

        QListView 对行隐藏集合的任何变更都会排队一次自身重排，把图标从
        setPositionForIndex 摆好的位置上挪走（满页时拖动项一隐藏，尾部图标
        整体后移一格、被顶出页面，表现为整个界面图标混乱）。Qt 的重排与本
        任务同为队列任务（FIFO），本任务在其后运行，把图标摆回网格。
        """
        QTimer.singleShot(0, self._after_rows_changed)

    def _after_rows_changed(self):
        self._assert_page_positions()
        if self._drag_active and self._target_cell[0] >= 0:
            # 隐藏集合变化打断了悬停预览动画，按当前落点重放
            self._apply_drag_preview(self._target_cell)
        self.viewport().update()

    def _slot_pos(self, slot):
        """槽位在视口中的位置。"""
        col = slot % self._cols
        row = slot // self._cols
        return QPoint(self._x_offset + col * self._cell.width(),
                      row * self._cell.height())

    def _set_item_pos(self, path, pos):
        """设置图标位置并记录实时位置（悬停动画中途重定向时平滑衔接）。"""
        item = self._items.get(path)
        if item is None:
            return
        try:
            self.setPositionForIndex(QPoint(pos), self.indexFromItem(item))
        except RuntimeError:  # 条目已随 populate 清空销毁
            return
        self._live_pos[path] = QPoint(pos)

    def showEvent(self, event):
        super().showEvent(event)
        # 首次显示时视口尺寸才真正就绪
        QTimer.singleShot(0, self._relayout)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout()
        if self._drag_active:
            # 视口尺寸变了，悬停预览偏移要按新格子重算
            self._apply_drag_preview(self._target_cell)

    # ---- 图标 ----
    def _icon_for(self, path):
        if path not in self._icons:
            self._icons[path] = self._normalized_icon(self._extract_icon(path))
        return self._icons[path]

    def _normalized_icon(self, icon):
        """把图标重包成统一边长的像素图 QIcon。

        Windows 外壳图标引擎对个别快捷方式（如 rustdesk/Magpie/devcpp）给
        不出真正的大图：请求 256px 时返回一张大画布，内容却只是贴在角落的
        48px 小图（jumbo 变体提取失败），网格里表现为小图悬在格子中间。
        因此统一重包：请求大图后裁出实际不透明内容，不足 80% 画布的放大
        铺满，再以像素图重包——此后任何缩放级别都从这张大图平滑缩放。
        """
        if icon.isNull():
            return icon
        pix = icon.pixmap(QSize(ICON_RENDER_SIZE, ICON_RENDER_SIZE))
        if pix.isNull():
            return icon
        pix.setDevicePixelRatio(1.0)
        image = pix.toImage()
        box = self._opaque_bbox(image)
        if box is not None:
            x, y, w, h = box
            if w < ICON_RENDER_SIZE * 0.8 or h < ICON_RENDER_SIZE * 0.8:
                # 内容只占画布一角（外壳把小图标贴进大画布）：裁出内容放大铺满
                margin = 2
                crop = QRect(
                    max(0, x - margin), max(0, y - margin), w + 2 * margin, h + 2 * margin,
                ).intersected(image.rect())
                pix = QPixmap.fromImage(image.copy(crop).scaled(
                    ICON_RENDER_SIZE, ICON_RENDER_SIZE,
                    Qt.KeepAspectRatio, Qt.SmoothTransformation,
                ))
        return QIcon(pix)

    @staticmethod
    def _opaque_bbox(image):
        """图中不透明内容的包围盒 (x, y, w, h)；全透明返回 None。"""
        w, h = image.width(), image.height()
        if w == 0 or h == 0:
            return None
        bits = image.constBits()      # ARGB32：每像素 4 字节，A 是第 4 字节
        stride = image.bytesPerLine()
        min_x, min_y, max_x, max_y = w, h, -1, -1
        for y in range(h):
            base = y * stride
            alphas = bytes(bits[base + 3:base + w * 4:4])
            if not alphas.strip(b"\x00"):
                continue              # 整行全透明
            left = w - len(alphas.lstrip(b"\x00"))
            right = len(alphas.rstrip(b"\x00")) - 1
            if left < min_x:
                min_x = left
            if right > max_x:
                max_x = right
            if min_y == h:
                min_y = y
            max_y = y
        if max_x < 0:
            return None
        return (min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)

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

    # ---- 鼠标与键盘交互 ----
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
            if self._begin_drag():  # QDrag 循环阻塞到松手/取消
                if self._drag_active:
                    # 同步模拟拖拽（离屏测试）时 exec 被替换为空转，拖拽仍在
                    # 进行：用本次移动初始化落点。真实运行到这里拖拽已结束
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
            self._relayout()  # 恢复悬停预览偏移之前的布局
            event.accept()
            return
        key = event.key()
        mods = event.modifiers() & (
            Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier
        )
        if not mods:
            if key in (Qt.Key_A, Qt.Key_Left):
                self.prev_page()
                event.accept()
                return
            if key in (Qt.Key_D, Qt.Key_Right):
                self.next_page()
                event.accept()
                return
        if key == Qt.Key_PageUp:
            self.prev_page()
            event.accept()
            return
        if key == Qt.Key_PageDown:
            self.next_page()
            event.accept()
            return
        if key == Qt.Key_Home:
            self.goto_page(0)
            event.accept()
            return
        if key == Qt.Key_End:
            self.goto_page(self._total_pages - 1)
            event.accept()
            return
        super().keyPressEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if event.modifiers() & Qt.ControlModifier:
            if delta:
                # 按增量比例缩放：鼠标一格 120° 缩一级，触控板捏合小步长平滑缩放
                self.set_scale(self._scale * (ZOOM_STEP ** (delta / 120)))
            event.accept()
            return
        if delta == 0:
            delta = event.angleDelta().x()
        if delta:
            if delta < 0:
                self.next_page()
            else:
                self.prev_page()
        event.accept()

    # ---- 拖拽整理 ----
    def dragEnterEvent(self, event):
        if self._drag_active and event.source() is self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        # QDrag 循环期间光标移动走这里（普通 mouseMoveEvent 不再收到）
        if self._drag_active and event.source() is self:
            self._update_drag(event.position().toPoint())
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        # 光标离开视口（如移到翻页栏/标题栏）：预览冻结，回来自动刷新
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        if self._drag_active and event.source() is self:
            self._finish_drag(event.position().toPoint())
            event.acceptProposedAction()
        else:
            event.ignore()

    def _begin_drag(self):
        """启动拖拽：不透明像素图随 QDrag 跟光标；返回是否确实启动。

        QDrag.exec 阻塞到松手或取消：窗口内松手经 dropEvent → _finish_drag
        落位；Esc/丢到窗口外由 _exec_drag 收尾恢复原布局。
        """
        item = self._press_item
        self._press_item = None
        if item is None:
            return False
        try:
            path = item.data(DATA_ROLE)["path"]
            pixmap, hotspot = self._drag_pixmap(item)  # 须在隐藏行之前渲染
        except RuntimeError:  # 条目已随 populate 清空销毁
            return False
        self._drag_item = item
        self._drag_path = path
        self._origin_cell = self._cell_of(path)
        self._target_cell = self._origin_cell
        self._ghost_cell = self._origin_cell
        self._drag_active = True
        # 行级隐藏（不能用 item.setHidden）：与 _relayout 同一机制，且隐藏
        # 集合变化后由 _schedule_reassert 抵消 Qt 的自身重排
        try:
            row = self.row(item)
            if not self.isRowHidden(row):
                self.setRowHidden(row, True)
                self._schedule_reassert()
        except RuntimeError:  # 条目已随 populate 清空销毁
            self._drag_active = False
            self._drag_item = None
            self._drag_path = None
            return False
        self.viewport().setCursor(Qt.ClosedHandCursor)

        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(path)
        drag.setMimeData(mime)
        drag.setPixmap(pixmap)
        drag.setHotSpot(hotspot)
        # 隐藏拖拽自带的箭头/移动角标：拖动中只显示被抓着的图标像素图
        # （热区仍在原抓取点，手感像直接捏着图标）；移到不可落区时系统
        # 的「禁止」光标仍保留作提示
        blank_cursor = QPixmap(16, 16)
        blank_cursor.fill(Qt.transparent)
        drag.setDragCursor(blank_cursor, Qt.MoveAction)
        self._exec_drag(drag)
        return True

    def _drag_pixmap(self, item):
        """渲染拖拽跟随的像素图（不透明图标+名称、透明底）与热区偏移。"""
        rect = self.visualItemRect(item)
        if rect.isValid():
            try:
                dpr = self.devicePixelRatioF()
                pix = QPixmap(
                    max(1, round(rect.width() * dpr)),
                    max(1, round(rect.height() * dpr)),
                )
                pix.setDevicePixelRatio(dpr)
                pix.fill(Qt.transparent)
                painter = QPainter(pix)
                opt = QStyleOptionViewItem()
                self.initViewItemOption(opt)
                opt.rect = QRect(0, 0, rect.width(), rect.height())
                opt.state = QStyle.State_Enabled | QStyle.State_Open
                self.itemDelegate().paint(painter, opt, self.indexFromItem(item))
                painter.end()
                offset = QPoint(
                    min(max(0, self._press_pos.x() - rect.left()), rect.width()),
                    min(max(0, self._press_pos.y() - rect.top()), rect.height()),
                )
                return pix, offset
            except RuntimeError:  # 条目已随 populate 清空销毁
                pass
        fallback = item.icon().pixmap(self.iconSize())
        return fallback, QPoint(fallback.width() // 2, fallback.height() // 2)

    def _exec_drag(self, drag):
        """QDrag 拖拽循环，阻塞到松手/取消；离屏测试以同步事件模拟时替换本方法。"""
        drag.exec(Qt.MoveAction)
        if self._drag_active:
            # exec 返回但仍在拖拽态 = 没有发生 drop（Esc 取消/丢到窗口外）
            self._end_drag()
            self._relayout()  # 恢复悬停预览偏移之前的布局

    def _cell_of(self, path):
        """路径在当前页的格子；不在当前页（如过滤中）返回 (-1, -1)。"""
        try:
            o_idx = self._order.index(path)
            slot = self._page_slots.index(o_idx)
        except ValueError:
            return (-1, -1)
        return (slot % self._cols, slot // self._cols)

    def _slot_at(self, pos):
        """光标吸附到的当前页格子（列, 行），视口外夹回边界。"""
        if self._cell.width() <= 0 or self._cell.height() <= 0:
            return (0, 0)
        vp = self.viewport().rect()
        x = min(max(pos.x(), 0), vp.right())
        y = min(max(pos.y(), 0), vp.bottom())
        cw, ch = self._cell.width(), self._cell.height()
        col = min(max((x - self._x_offset) // cw, 0), self._cols - 1)
        row = min(max(y // ch, 0), self._rows - 1)
        return (int(col), int(row))

    def _update_drag(self, pos, force=False):
        self._cursor_pos = pos
        cell = self._slot_at(pos)
        zone = self._zone_at(pos, cell)
        if force or cell != self._target_cell or zone != self._drop_zone:
            self._target_cell = cell
            self._drop_zone = zone
            self._apply_drag_preview(cell)
            self.viewport().update()

    def _zone_at(self, pos, cell):
        """光标在落点格子内的横向分区：'left'（插前）/ 'center'（互换）/ 'right'（插后）。

        分区按目标格子自身的宽度算（左右各 1/4、中间 50%），与手机桌面一致：
        把图标拖到任意图标的左右边缘都能插入，而不是只能瞄准屏幕两侧的竖条。
        """
        cw = self._cell.width()
        if cw <= 0:
            return "center"
        col = cell[0]
        local = pos.x() - (self._x_offset + col * cw)
        if local < cw / 4:
            return "left"
        if local > cw * 3 / 4:
            return "right"
        return "center"

    def _finish_drag(self, pos):
        path = self._drag_path
        self._end_drag()
        if path is None or path not in self._items:
            return
        try:
            o_idx = self._order.index(path)
        except ValueError:
            return
        cell = self._slot_at(pos)
        new_order = self._moved_order(o_idx, cell, self._zone_at(pos, cell))
        if new_order is None or new_order == self._order:
            return
        self._order[:] = new_order
        self._relayout()
        self.layout_changed.emit()

    def _moved_order(self, o_idx, cell, zone):
        """按落点分区计算整理后的顺序；无需移动返回 None。

        - 格子内中间 50% 区：与目标图标互换；
        - 左 1/4 边缘：插到目标图标之前；右 1/4 边缘：插到目标之后；
          落点到原位之间的图标向原位方向顺移一格补位（手机桌面式）；
        - 页尾空白：移到本页最后一个可见项之后；
        - 插入点钳制在本页内，不会把图标挤出本页。
        """
        col, row = cell
        slot = row * self._cols + col
        order = list(self._order)
        slots = self._page_slots
        in_left = zone == "left"
        in_right = zone == "right"
        if slot < len(slots) and not (in_left or in_right):
            # 中间区：换位
            p_idx = slots[slot]
            if p_idx == o_idx:
                return None
            order[o_idx], order[p_idx] = order[p_idx], order[o_idx]
            return order
        v = self._insertion_pos(cell, zone)
        if v is None:
            return None
        visible = self._visible_order()
        try:
            o_pos = visible.index(o_idx)
        except ValueError:
            return None
        v = min(v, len(visible))
        v_adj = v - 1 if v > o_pos else v
        if v_adj == o_pos:
            return None
        dragged = order.pop(o_idx)
        if v < len(visible):
            # 插到可见序中第 v 项之前；该项在原位之后的，删位后下标前移一
            insert_at = visible[v]
            if insert_at > o_idx:
                insert_at -= 1
        else:
            insert_at = len(order)
        order.insert(insert_at, dragged)
        return order

    # ---- 拖拽悬停预览 ----
    def _insertion_pos(self, cell, zone):
        """落点对应的插入点（可见序下标）；格子内中间 50% 区返回 None。

        左 1/4 边缘插到目标之前，右 1/4 边缘插到目标之后；插入点不越过
        本页最后一项（满页末尾插入＝拖动图标占住末位、原末项顺移到下页开头）。
        """
        col, row = cell
        slot = row * self._cols + col
        slots = self._page_slots
        page_start = self._page * self._per_page
        if slot >= len(slots):
            return page_start + len(slots)  # 页尾空白（仅末页）：本页末尾
        in_left = zone == "left"
        in_right = zone == "right"
        if not (in_left or in_right):
            return None
        v = page_start + slot + (1 if in_right else 0)
        max_v = page_start + min(len(slots), self._per_page - 1)
        return min(v, max_v)

    def _drag_preview(self, cell):
        """拖动悬停预览：返回 ({路径: 目标槽位}, 拖动项落点槽位)。"""
        v = self._insertion_pos(cell, self._drop_zone)
        if v is None:
            return None
        try:
            o_idx = self._order.index(self._drag_path)
        except ValueError:
            return None
        visible = self._visible_order()
        try:
            o_pos = visible.index(o_idx)
        except ValueError:
            return None
        v = min(v, len(visible))
        v_adj = v - 1 if v > o_pos else v
        preview = visible[:o_pos] + visible[o_pos + 1:]
        preview.insert(v_adj, o_idx)
        page_start = self._page * self._per_page
        mapping = {}
        drag_slot = None
        for i, oi in enumerate(preview[page_start:page_start + self._per_page]):
            if oi == o_idx:
                drag_slot = i
            else:
                mapping[self._order[oi]] = i
        return mapping, drag_slot

    def _apply_drag_preview(self, cell):
        """悬停时让受影响的图标动画偏移到插入后的位置；中心区不偏移。"""
        if not self._drag_active or self._drag_path is None:
            return
        base = {self._order[oi]: self._slot_pos(slot)
                for slot, oi in enumerate(self._page_slots)}
        preview = self._drag_preview(cell)
        if preview is None:
            targets = base
            self._ghost_cell = cell
        else:
            mapping, drag_slot = preview
            targets = {path: self._slot_pos(slot) for path, slot in mapping.items()}
            if drag_slot is not None:
                self._ghost_cell = (drag_slot % self._cols, drag_slot // self._cols)
            else:
                self._ghost_cell = cell
        targets.pop(self._drag_path, None)  # 拖动项由落点阴影代表，不参与偏移
        self._anim_from = {}
        self._anim_to = {}
        for path, end in targets.items():
            start = self._live_pos.get(path)
            if start is None:
                item = self._items.get(path)
                if item is None:
                    continue
                try:
                    rect = self.visualItemRect(item)
                    start = rect.topLeft() if not rect.isNull() else end
                except RuntimeError:
                    continue
            self._anim_from[path] = QPoint(start)
            self._anim_to[path] = QPoint(end)
        self._drag_anim.stop()
        self._drag_anim.setStartValue(0.0)
        self._drag_anim.setEndValue(1.0)
        self._drag_anim.start()

    def _anim_tick(self, t):
        for path, start in self._anim_from.items():
            end = self._anim_to.get(path)
            if end is None:
                continue
            self._set_item_pos(path, QPoint(
                round(start.x() + (end.x() - start.x()) * t),
                round(start.y() + (end.y() - start.y()) * t),
            ))

    def _end_drag(self):
        self._drag_active = False
        self._drag_anim.stop()
        self._anim_from = {}
        self._anim_to = {}
        if self._drag_item is not None:
            try:
                row = self.row(self._drag_item)
                if self.isRowHidden(row):
                    self.setRowHidden(row, False)
                    self._schedule_reassert()
            except RuntimeError:  # 条目已随 populate 清空销毁
                pass
        self._drag_item = None
        self._drag_path = None
        self._origin_cell = (-1, -1)
        self._target_cell = (-1, -1)
        self._drop_zone = "center"
        self._ghost_cell = (-1, -1)
        self._cursor_pos = QPoint()
        self.viewport().unsetCursor()
        self.setState(QAbstractItemView.State.NoState)
        self.viewport().update()

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
        if self._ghost_cell[0] < 0 or self._ghost_cell == self._origin_cell:
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
        """落点阴影吸附的格子（插入点/互换目标）在视口中的矩形。"""
        if self._ghost_cell[0] < 0:
            return QRect()
        cw, ch = self._cell.width(), self._cell.height()
        return QRect(
            QPoint(
                self._x_offset + self._ghost_cell[0] * cw,
                self._ghost_cell[1] * ch,
            ),
            QSize(cw, ch),
        )


class PageBar(QWidget):
    """右侧翻页栏：上下箭头 + 每页一个页位点，当前页显示为长条。

    样式保持极简：不画底板，只用主题色画箭头与页位点；点击箭头/页位点翻页
    或跳转，滚轮直接翻页。只有一页时整个栏自动隐藏。
    """

    page_requested = Signal(int)    # 目标页（0 基）

    WIDTH = 26
    ARROW = 22                      # 上下箭头区高度

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current = 0
        self._total = 1
        self._hover = None          # 'prev' | 'next' | 页序号 | None
        self.setFixedWidth(self.WIDTH)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_pages(self, current, total):
        total = max(1, int(total))
        current = min(max(0, int(current)), total - 1)
        changed = (current, total) != (self._current, self._total)
        self._current, self._total = current, total
        # 单页时隐藏整条翻页栏（可见性每次都刷新，避免初值相同被跳过）
        self.setVisible(total > 1)
        if changed:
            self.update()

    # ---- 几何与命中 ----
    def _dots_rect(self):
        """页位点活动区：间距封顶后整体在箭头之间的空间里垂直居中。"""
        avail = QRect(0, self.ARROW, self.width(), max(0, self.height() - 2 * self.ARROW))
        slot = min(36.0, avail.height() / max(1, self._total))
        used = slot * self._total
        top = avail.top() + (avail.height() - used) / 2
        return QRect(0, int(top), self.width(), int(used))

    def _hit_test(self, pos):
        """返回 'prev' | 'next' | 页序号（0 基）；未命中返回 None。"""
        if self._total <= 1:
            return None
        w = self.width()
        if QRect(0, 0, w, self.ARROW).contains(pos):
            return "prev"
        if QRect(0, self.height() - self.ARROW, w, self.ARROW).contains(pos):
            return "next"
        dots = self._dots_rect()
        if dots.height() > 0 and dots.contains(pos):
            slot = dots.height() / self._total
            page = int((pos.y() - dots.top()) / slot)
            return min(self._total - 1, max(0, page))
        return None

    # ---- 交互 ----
    def mouseMoveEvent(self, event):
        hit = self._hit_test(event.position().toPoint())
        if hit != self._hover:
            self._hover = hit
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover is not None:
            self._hover = None
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        hit = self._hit_test(event.position().toPoint())
        if hit == "prev":
            self.page_requested.emit(self._current - 1)
        elif hit == "next":
            self.page_requested.emit(self._current + 1)
        elif isinstance(hit, int):
            self.page_requested.emit(hit)
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.angleDelta().x()
        if delta:
            self.page_requested.emit(self._current + (1 if delta < 0 else -1))
        event.accept()

    # ---- 绘制 ----
    def paintEvent(self, event):
        if self._total <= 1:
            return
        c = theme_colors()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        cx = w / 2
        self._paint_chevron(
            painter, c, cy=self.ARROW / 2, up=True,
            enabled=self._current > 0, hovered=self._hover == "prev",
        )
        self._paint_chevron(
            painter, c, cy=self.height() - self.ARROW / 2, up=False,
            enabled=self._current < self._total - 1, hovered=self._hover == "next",
        )
        dots = self._dots_rect()
        slot = dots.height() / self._total
        hovered_dot = self._hover if isinstance(self._hover, int) else -1
        for i in range(self._total):
            cy = dots.top() + slot * (i + 0.5)
            if i == self._current:
                pill_h = max(6.0, min(16.0, slot - 4.0))
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(c["text"]))
                painter.drawRoundedRect(QRectF(cx - 2, cy - pill_h / 2, 4, pill_h), 2, 2)
            else:
                radius = 2.0 if slot >= 8 else 1.4
                color = c["hover"] if i == hovered_dot else c["border"]
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(color))
                painter.drawEllipse(QPointF(cx, cy), radius, radius)
        painter.end()

    def _paint_chevron(self, painter, c, cy, up, enabled, hovered):
        cx = self.width() / 2
        if enabled and hovered:
            color = QColor(c["text"])
        elif enabled:
            color = QColor(c["placeholder"])
        else:
            color = QColor(c["disabled"])
        pen = QPen(color)
        pen.setWidthF(1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        d, tip = 4.0, 2.2
        tip_y = cy - tip if up else cy + tip
        base_y = cy + tip if up else cy - tip
        painter.drawPolyline(
            QPolygonF([QPointF(cx - d, base_y), QPointF(cx, tip_y), QPointF(cx + d, base_y)])
        )
