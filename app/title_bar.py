"""自定义标题栏：无系统边框窗口的顶部导航栏。

Windows 上配合 MainWindow.nativeEvent 里的 WM_NCHITTEST 命中测试：
- 窗口边缘返回尺寸调整区，保留原生缩放；
- 标题栏空白处返回 HTCAPTION，拖动、双击最大化、Aero Snap、右键系统菜单
  全部由系统完成，行为与原生窗口一致；
- 按钮区域返回 HTCLIENT，保证按钮自身可点击。
"""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton,
    QHBoxLayout,
    QLabel,
    QToolButton,
    QWidget,
)

from app.theme import colors

WM_NCHITTEST = 0x0084
WM_SETCURSOR = 0x0020
WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONDBLCLK = 0x00A3
HTCLIENT = 1
HTCAPTION = 2
HTLEFT = 10
HTRIGHT = 11
HTTOP = 12
HTTOPLEFT = 13
HTTOPRIGHT = 14
HTBOTTOM = 15
HTBOTTOMLEFT = 16
HTBOTTOMRIGHT = 17

# 系统共享光标 ID：水平/垂直/两对角缩放
_IDC_SIZEWE = 32644
_IDC_SIZENS = 32645
_IDC_SIZENWSE = 32642
_IDC_SIZENESW = 32643
_RESIZE_CURSORS = {
    HTLEFT: _IDC_SIZEWE,
    HTRIGHT: _IDC_SIZEWE,
    HTTOP: _IDC_SIZENS,
    HTBOTTOM: _IDC_SIZENS,
    HTTOPLEFT: _IDC_SIZENWSE,
    HTBOTTOMRIGHT: _IDC_SIZENWSE,
    HTTOPRIGHT: _IDC_SIZENESW,
    HTBOTTOMLEFT: _IDC_SIZENESW,
}

EDGE = 6          # 可拖拽缩放的窗口边缘宽度（逻辑像素）
BAR_HEIGHT = 38   # 标题栏高度
BTN_WIDTH = 44    # 窗口按钮宽度
ICON_SIZE = 20    # 窗口按钮图标边长（逻辑像素）


class _MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


def _glyph_icon(kind, color, size=ICON_SIZE):
    """以 3x 超采样绘制 size px 的线性图标，任意缩放下都清晰。

    线条坐标按 48 画布设计（字形占约 3/4，四周仅留少量空白），
    通过 painter.scale 等比适配尺寸。
    """
    canvas = size * 3
    pixmap = QPixmap(canvas, canvas)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(canvas / 48, canvas / 48)
    pen = QPen(QColor(color))
    pen.setWidthF(3.6)
    pen.setCapStyle(Qt.FlatCap)
    painter.setPen(pen)
    if kind == "min":
        painter.drawLine(6, 24, 42, 24)
    elif kind == "max":
        painter.drawRect(6, 6, 36, 36)
    elif kind == "restore":
        painter.drawLine(15, 6, 42, 6)
        painter.drawLine(42, 6, 42, 33)
        painter.drawRect(6, 15, 27, 27)
    elif kind == "close":
        painter.drawLine(6, 6, 42, 42)
        painter.drawLine(42, 6, 6, 42)
    painter.end()
    return QIcon(pixmap)


class _WindowButton(QToolButton):
    """窗口控制按钮；悬停时切换高亮色图标（关闭按钮悬停为白 icon 红底）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icons = {}
        self.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        self.setFixedSize(BTN_WIDTH, BAR_HEIGHT)
        self.setFocusPolicy(Qt.NoFocus)

    def set_glyph(self, kind, color, hover_color):
        self._icons = {
            "normal": _glyph_icon(kind, color),
            "hover": _glyph_icon(kind, hover_color),
        }
        self.setIcon(self._icons["normal"])

    def enterEvent(self, event):
        self.setIcon(self._icons.get("hover") or self._icons.get("normal"))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setIcon(self._icons.get("normal"))
        super().leaveEvent(event)


class TitleBar(QWidget):
    """自定义标题栏：应用图标 + 标题 + 最小化/最大化/关闭按钮。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("titlebar")
        self.setFixedHeight(BAR_HEIGHT)

        self.icon_label = QLabel()
        self.icon_label.setFixedSize(16, 16)
        app_icon = self.window().windowIcon()
        if app_icon.isNull():
            self.icon_label.hide()
        else:
            self.icon_label.setPixmap(app_icon.pixmap(16, 16))

        self.title_label = QLabel(self.window().windowTitle(), self)

        self.min_button = _WindowButton(self)
        self.max_button = _WindowButton(self)
        self.close_button = _WindowButton(self)
        self.min_button.setObjectName("winbtn")
        self.max_button.setObjectName("winbtn")
        self.close_button.setObjectName("closebtn")
        self.min_button.clicked.connect(self.window().showMinimized)
        self.max_button.clicked.connect(self.toggle_maximize)
        self.close_button.clicked.connect(self.window().close)

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 0, 0)
        row.setSpacing(4)
        row.addWidget(self.icon_label)
        row.addWidget(self.title_label)
        row.addStretch(1)
        row.addWidget(self.min_button)
        row.addWidget(self.max_button)
        row.addWidget(self.close_button)
        self.refresh(colors())

    def refresh(self, c):
        """按当前主题刷新按钮图标颜色，切换主题后需重新调用。"""
        self.min_button.set_glyph("min", c["text"], c["text"])
        self.close_button.set_glyph("close", c["text"], "#ffffff")
        self.sync_maximize_state(c)

    def sync_maximize_state(self, c=None):
        """窗口最大化状态变化后，更新最大化/还原图标。"""
        c = c if c is not None else colors()
        kind = "restore" if self.window().isMaximized() else "max"
        self.max_button.set_glyph(kind, c["text"], c["text"])

    def toggle_maximize(self):
        """最大化/还原切换；标题栏双击与最大化按钮共用。"""
        window = self.window()
        if window.isMaximized():
            window.showNormal()
        else:
            window.showMaximized()


def resize_edges_at(window, local):
    """返回局部坐标所处的可缩放边缘（Qt.Edges），不在边缘时返回空。

    与 handle_hit_test 的边缘判定保持一致，供 startSystemResize 使用。
    """
    edges = Qt.Edges()
    if window.isMaximized():
        return edges
    if not (0 <= local.x() <= window.width() and 0 <= local.y() <= window.height()):
        return edges
    if local.x() <= EDGE:
        edges |= Qt.LeftEdge
    if local.x() >= window.width() - EDGE:
        edges |= Qt.RightEdge
    if local.y() <= EDGE:
        edges |= Qt.TopEdge
    if local.y() >= window.height() - EDGE:
        edges |= Qt.BottomEdge
    return edges


def is_caption_press(window, event_type, message):
    """是否为标题栏（HTCAPTION）的非客户区按下消息。"""
    if sys.platform != "win32" or event_type != "windows_generic_MSG":
        return False
    msg = _MSG.from_address(int(message))
    return msg.message == WM_NCLBUTTONDOWN and msg.wParam == HTCAPTION


def handle_caption_dblclick(window, event_type, message):
    """标题栏双击（0xA3）：切换最大化/还原，返回 True 表示已处理。

    必须在原生层处理——Qt 对该消息的处理时机不确定，原生切换与
    widget 事件切换可能叠加，出现"闪一下又回到原状态"。
    """
    if sys.platform != "win32" or event_type != "windows_generic_MSG":
        return False
    msg = _MSG.from_address(int(message))
    if msg.message != WM_NCLBUTTONDBLCLK or msg.wParam != HTCAPTION:
        return False
    window.title_bar.toggle_maximize()
    return True


def handle_set_cursor(event_type, message):
    """WM_SETCURSOR：在缩放边缘显示系统缩放光标。

    Qt 会用控件自身的光标覆盖非客户区光标形状，导致边缘悬停时
    不出现缩放箭头；这里对边缘命中码显式 SetCursor 并终止消息。
    返回 1 表示已处理，None 表示交给后续处理。
    """
    if sys.platform != "win32" or event_type != "windows_generic_MSG":
        return None
    msg = _MSG.from_address(int(message))
    if msg.message != WM_SETCURSOR:
        return None
    cursor_id = _RESIZE_CURSORS.get(msg.lParam & 0xFFFF)
    if cursor_id is None:
        return None
    user32 = ctypes.windll.user32
    user32.SetCursor(user32.LoadCursorW(None, cursor_id))
    return 1


def handle_hit_test(window, event_type, message):
    """处理 WM_NCHITTEST 命中测试；返回命中码，未涉及则返回 None。"""
    if sys.platform != "win32" or event_type != "windows_generic_MSG":
        return None
    msg = _MSG.from_address(int(message))
    if msg.message != WM_NCHITTEST:
        return None
    x = ctypes.c_short(msg.lParam & 0xFFFF).value
    y = ctypes.c_short((msg.lParam >> 16) & 0xFFFF).value
    # lParam 为物理屏幕坐标，Qt 全局坐标是逻辑像素，需先按 DPR 换算
    dpr = window.devicePixelRatioF() or 1.0
    local = window.mapFromGlobal(QPointF(x / dpr, y / dpr).toPoint())
    width, height = window.width(), window.height()
    if not (0 <= local.x() <= width and 0 <= local.y() <= height):
        return None

    # 窗口边缘为原生缩放区；最大化时不允许缩放
    if not window.isMaximized():
        left = local.x() <= EDGE
        right = local.x() >= width - EDGE
        top = local.y() <= EDGE
        bottom = local.y() >= height - EDGE
        if top and left:
            return HTTOPLEFT
        if top and right:
            return HTTOPRIGHT
        if bottom and left:
            return HTBOTTOMLEFT
        if bottom and right:
            return HTBOTTOMRIGHT
        if left:
            return HTLEFT
        if right:
            return HTRIGHT
        if top:
            return HTTOP
        if bottom:
            return HTBOTTOM

    # 标题栏空白处交给系统（拖动/双击/贴靠/系统菜单），按钮留给 Qt
    if local.y() <= window.title_bar.height():
        widget = window.childAt(local)
        while widget is not None and widget is not window.title_bar:
            if isinstance(widget, QAbstractButton):
                return HTCLIENT
            widget = widget.parentWidget()
        return HTCAPTION
    return HTCLIENT
