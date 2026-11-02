"""端到端验证 Win+Space 全局快捷键（手动运行：python hotkey_e2e_test.py）。

用 keybd_event 注入真实按键（低级钩子看到的就是系统级输入），验证
「按 Win+Space 窗口隐藏、再按一次又显示」。

注意：脚本会真的往系统里注入 Win+Space 键，窗口会在屏幕上显隐一次，
因此没有并入默认测试（bugs_test.py 已用等价方式覆盖钩子的识别逻辑），
需要时手动跑。
"""
import ctypes
import os
import sys
import time
from ctypes import wintypes
from pathlib import Path

os.environ.pop("ICONDESKTOP_CONFIG_LOCATION", None)
os.environ.pop("QT_QPA_PLATFORM", None)
sys.path.insert(0, str(Path(__file__).parent))

from PySide6.QtWidgets import QApplication  # noqa: E402

import app.config as config_module  # noqa: E402
from app.main_window import MainWindow  # noqa: E402

user32 = ctypes.windll.user32

user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_ulonglong]
KEYEVENTF_KEYUP = 0x0002
VK_LWIN = 0x5B
VK_SPACE = 0x20


def send(vk, up=False):
    """注入一次真实按键（keybd_event：这台机器上 SendInput 不可用）。"""
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP if up else 0, 0)


def pump(app, ms=400):
    """空转事件循环 ms 毫秒。"""
    end = time.time() + ms / 1000
    while time.time() < end:
        app.processEvents()
        time.sleep(0.01)


def foreground_class():
    """前台窗口的类名（Windows 11 的开始菜单是 SearchHost 的 CoreWindow）。"""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(user32.GetForegroundWindow(), buf, 256)
    return buf.value


app = QApplication(sys.argv)
app.setStyle("Fusion")

import tempfile  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    config_module.CONFIG_PATH = Path(tmp) / "config.json"
    win = MainWindow()
    win.show()
    pump(app, 300)

    print("钩子已装    :", win.hotkey.active)
    print("初始可见    :", win.isVisible())

    # 真的按一次 Win+Space
    send(VK_LWIN)
    time.sleep(0.05)
    send(VK_SPACE)
    time.sleep(0.05)
    send(VK_SPACE, up=True)
    time.sleep(0.05)
    send(VK_LWIN, up=True)
    pump(app, 500)

    print("按下后可见  :", win.isVisible())
    toggled = not win.isVisible()

    # 再按一次，应该又显示回来
    send(VK_LWIN)
    time.sleep(0.05)
    send(VK_SPACE)
    time.sleep(0.05)
    send(VK_SPACE, up=True)
    time.sleep(0.05)
    send(VK_LWIN, up=True)
    pump(app, 500)
    print("再按后可见  :", win.isVisible())
    toggled = toggled and win.isVisible()

    # 副作用检查：松开 Win 不该弹出开始菜单/搜索面板，按键状态也不该留脏
    fg_class = foreground_class()
    start_menu = "Windows.UI.Core.CoreWindow" in fg_class
    win_stuck = bool(user32.GetAsyncKeyState(VK_LWIN) & 0x8000)
    print("前台窗口类  :", fg_class)
    print("开始菜单弹出:", start_menu, "← 应为 False")
    print("Win 状态残留:", win_stuck, "← 应为 False（残留会让之后敲 E 误开资源管理器）")

    win.hotkey.unregister()
    win.close()
    ok = toggled and not start_menu and not win_stuck
    print("\nWin+Space 端到端:", "通过" if ok else "失败")
    sys.exit(0 if ok else 1)
