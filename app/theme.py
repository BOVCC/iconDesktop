"""配色主题：浅色 / 深色两套，统一通过 QPalette 应用到 QApplication。

注意：
- 背景色一律通过 QPalette 设置。若改用样式表给 QMainWindow/central 等
  容器设置 background，会触发 Qt 的调色板重置，导致子控件文字渲染成白色。
- 调色板要应用到 QApplication 上；设在单个窗口上会与样式表冲突，
  同样出现子控件文字变白的问题。
- 样式表仅用于叶子控件（QListWidget、QLineEdit 等），颜色取自 colors()
  返回的当前主题；运行时切换主题后必须重新生成样式表。
"""
import ctypes
import sys

from PySide6.QtGui import QColor, QPalette

LIGHT = {
    "bg": "#e8eaed",        # 窗口/网格背景（淡灰）
    "titlebar": "#f0f2f4",  # 自定义标题栏底色（比背景略浅）
    "field": "#f5f6f7",     # 输入框底色（比背景略浅）
    "button": "#eef0f2",    # 按钮底色（比背景略浅，避免深色模式的深色按钮）
    "text": "#1f2933",      # 正文文字色
    "border": "#c8cdd3",    # 输入框描边
    "hover": "#d9dcdf",     # 图标悬停背景
    "selected": "#c9ced4",  # 图标选中背景
    "placeholder": "#8a939c",   # 输入框占位文字
    "disabled": "#a7adb4",      # 禁用态文字
    "tooltip_bg": "#f5f6f7",    # 气泡提示底色
}

DARK = {
    "bg": "#1f242b",
    "titlebar": "#242b33",
    "field": "#29313a",
    "button": "#2b333c",
    "text": "#e7eaee",
    "border": "#3c4550",
    "hover": "#343e48",
    "selected": "#3e4a55",
    "placeholder": "#7c8794",
    "disabled": "#66707c",
    "tooltip_bg": "#2a323c",
}

THEMES = {"light": LIGHT, "dark": DARK}
DEFAULT_MODE = "dark"

_mode = DEFAULT_MODE


def mode():
    """当前主题名（light | dark）。"""
    return _mode


def colors():
    """当前主题的颜色表。"""
    return THEMES[_mode]


def apply_theme(target, theme=DEFAULT_MODE):
    """把指定主题的调色板应用到 QApplication 或 QWidget。"""
    global _mode
    _mode = theme if theme in THEMES else DEFAULT_MODE
    c = THEMES[_mode]
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(c["bg"]))
    palette.setColor(QPalette.WindowText, QColor(c["text"]))
    palette.setColor(QPalette.Base, QColor(c["field"]))
    palette.setColor(QPalette.AlternateBase, QColor(c["bg"]))
    palette.setColor(QPalette.Button, QColor(c["button"]))
    palette.setColor(QPalette.ButtonText, QColor(c["text"]))
    palette.setColor(QPalette.Text, QColor(c["text"]))
    palette.setColor(QPalette.PlaceholderText, QColor(c["placeholder"]))
    palette.setColor(QPalette.Highlight, QColor(c["selected"]))
    palette.setColor(QPalette.HighlightedText, QColor(c["text"]))
    palette.setColor(QPalette.ToolTipBase, QColor(c["tooltip_bg"]))
    palette.setColor(QPalette.ToolTipText, QColor(c["text"]))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        palette.setColor(QPalette.Disabled, role, QColor(c["disabled"]))
    target.setPalette(palette)


def apply_titlebar_theme(widget, theme=DEFAULT_MODE):
    """把 Windows 窗口标题栏切到对应深浅（Win10 1809+ / Win11）。

    其他平台或系统不支持时静默跳过；运行时切换主题可重复调用。
    """
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1 if theme == "dark" else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE，旧版 Win10 为 19
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                break
    except Exception:
        pass
