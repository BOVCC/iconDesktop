"""全局快捷键：Win+Space 显示/隐藏主窗口。

Windows 10/11 把 Win+Space 绑给了系统自己（按 Win+Space 会弹出搜索面板），
用 RegisterHotKey 注册会直接失败（错误 1409 ERROR_HOTKEY_ALREADY_REGISTERED）。
所以这里先试 RegisterHotKey，注册不了再退回低级键盘钩子（WH_KEYBOARD_LL）：

- RegisterHotKey：由系统投递 WM_HOTKEY，最省事，不占用按键本身；
- 低级键盘钩子：只是"看见"按键而不与系统争抢，所以系统占用时照样能用。

低级钩子回调有系统超时限制（LowLevelHooksTimeout，默认 300ms），必须
尽快返回：因此触发时只投递一个 0 延时定时器，真正的显示/隐藏交给事件
循环处理。

接管 Win+Space 要同时对付系统的两处反应（实测 Win11 22631）：
1. Win+Space 被系统绑成"打开搜索面板"——必须吃掉空格，否则系统自己的
   面板会弹出来；
2. 空格被吃掉后，系统在松开 Win 时看到的就是一次"孤零零的 Win 按下"，
   于是弹出开始菜单——钩子在吃掉空格时补一次 Shift 作为"伴随键"，系统
   看到 Win 旁边还按过别的键就不会弹开始菜单（详见 _companion_key）。

Win 的抬起照常放行，系统按键状态不留脏：否则之后单独敲个 E 会被当成
Win+E 弹出资源管理器。
"""
import ctypes
import sys
from ctypes import wintypes

from PySide6.QtCore import QObject, QTimer, Signal

WM_HOTKEY = 0x0312
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
VK_SPACE = 0x20
VK_LWIN = 0x5B
VK_RWIN = 0x5C

WH_KEYBOARD_LL = 13
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
KEYEVENTF_KEYUP = 0x0002
VK_SHIFT = 0x10           # 伴随键：系统看到 Win 旁边还按过别的键就不弹开始菜单

HOTKEY_ID = 0xB1C7

_ENABLED = sys.platform == "win32"

if _ENABLED:
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    class _MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
        ]

    class _KBDLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [
            ("vkCode", wintypes.DWORD),
            ("scanCode", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
        ]

    _HOOKPROC = ctypes.WINFUNCTYPE(
        ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
    )

    # 绑定签名：避免 64 位句柄被截断，也避免返回值被当成 32 位
    _user32.RegisterHotKey.argtypes = [
        wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT,
    ]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.UnregisterHotKey.restype = wintypes.BOOL
    _user32.SetWindowsHookExW.argtypes = [
        ctypes.c_int, _HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD,
    ]
    _user32.SetWindowsHookExW.restype = wintypes.HANDLE
    _user32.UnhookWindowsHookEx.argtypes = [wintypes.HANDLE]
    _user32.UnhookWindowsHookEx.restype = wintypes.BOOL
    _user32.CallNextHookEx.argtypes = [
        wintypes.HANDLE, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM,
    ]
    _user32.CallNextHookEx.restype = ctypes.c_ssize_t
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _user32.keybd_event.argtypes = [
        wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_ulonglong,
    ]
    _user32.keybd_event.restype = None
    _kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetModuleHandleW.restype = wintypes.HMODULE


def _win_key_down():
    """Win 键当前是否按下。"""
    return bool(
        _user32.GetAsyncKeyState(VK_LWIN) & 0x8000
        or _user32.GetAsyncKeyState(VK_RWIN) & 0x8000
    )


class GlobalHotkey(QObject):
    """Win+Space 全局快捷键；触发时发出 triggered 信号。

    优先用 RegisterHotKey（系统投递 WM_HOTKEY），被系统占用时退回低级
    键盘钩子。两种方式都可以用 unregister() 干净地撤销。
    """

    triggered = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._hwnd = None
        self._registered = False       # RegisterHotKey 成功
        self._hook_handle = None
        self._hook_proc = None
        self._space_down = False       # 空格已按下（等抬起，避免长按连发）
        self._win_down = False         # Win 键是否按住（钩子里自己跟踪）
        self._win_space = False        # 本次 Win 按下期间处理过 Win+Space

    # ---- 对外接口 ----
    def register(self, hwnd):
        """注册快捷键到窗口句柄；返回是否成功。"""
        self.unregister()
        if not _ENABLED or not hwnd:
            return False
        self._hwnd = hwnd
        if self._register_hotkey(hwnd):
            self._registered = True
            return True
        return self._install_hook()

    def unregister(self):
        """撤销注册（钩子与热键都清掉）。"""
        if self._registered and self._hwnd:
            try:
                _user32.UnregisterHotKey(self._hwnd, HOTKEY_ID)
            except OSError:
                pass
        self._registered = False
        if self._hook_handle:
            try:
                _user32.UnhookWindowsHookEx(self._hook_handle)
            except OSError:
                pass
        self._hook_handle = None
        self._hook_proc = None    # 释放回调引用
        self._space_down = False

    @property
    def active(self):
        """快捷键当前是否生效。"""
        return self._registered or self._hook_handle is not None

    def handle_native(self, event_type, message):
        """处理 WM_HOTKEY；返回 True 表示已处理（供 nativeEvent 调用）。"""
        if not _ENABLED or event_type != "windows_generic_MSG":
            return False
        try:
            msg = _MSG.from_address(int(message))
        except (TypeError, ValueError):
            return False
        if msg.message != WM_HOTKEY or msg.wParam != HOTKEY_ID:
            return False
        self._fire()
        return True

    # ---- 内部 ----
    def _register_hotkey(self, hwnd):
        """系统级注册；被系统占用（如 Win+Space 切输入法）时返回 False。"""
        try:
            return bool(
                _user32.RegisterHotKey(hwnd, HOTKEY_ID, MOD_WIN | MOD_NOREPEAT, VK_SPACE)
            )
        except OSError:
            return False

    def _install_hook(self):
        """低级键盘钩子：只看按键，不与系统争抢。"""
        proc = _HOOKPROC(self._hook_callback)
        module = _kernel32.GetModuleHandleW(None)
        handle = _user32.SetWindowsHookExW(WH_KEYBOARD_LL, proc, module, 0)
        if not handle:
            return False
        self._hook_proc = proc      # 必须保留引用，否则被回收后回调失效
        self._hook_handle = handle
        # 装钩子时 Win 键可能已经按着（如用户按住 Win 启动本程序）
        self._win_down = _win_key_down()
        return True

    def _hook_callback(self, n_code, w_param, l_param):
        """低级钩子回调：识别 Win+Space，吃掉空格，补一个伴随键。

        Win 键状态在钩子里自己跟踪，不用 GetAsyncKeyState：低级钩子是在
        按键被处理之前调用的，此时异步按键状态还没更新，拿它判断会时灵
        时不灵（松开 Win 后紧接着按空格会被误判成 Win+Space）。

        为什么要补伴随键（见 _companion_key）：Windows 自己把 Win+Space
        绑给了"打开搜索面板"，所以空格必须吃掉；但空格被吃掉后，系统在
        松开 Win 时看到的就是一次"孤零零的 Win 按下"，于是弹出开始菜单
        （用户反馈的现象）。补一次 Shift 让系统看到 Win 旁边还按过别的键，
        开始菜单就不会弹。
        """
        try:
            if n_code == HC_ACTION:
                message = int(w_param)
                if message in (WM_KEYDOWN, WM_SYSKEYDOWN, WM_KEYUP, WM_SYSKEYUP):
                    data = ctypes.cast(
                        l_param, ctypes.POINTER(_KBDLLHOOKSTRUCT)
                    ).contents
                    vk = data.vkCode
                    pressed = message in (WM_KEYDOWN, WM_SYSKEYDOWN)
                    if vk in (VK_LWIN, VK_RWIN):
                        # 跟踪 Win 键状态（按下为 True）
                        self._win_down = pressed
                        if pressed:
                            self._win_space = False
                    elif vk == VK_SPACE:
                        if self._win_down:
                            if pressed:
                                if not self._space_down:
                                    self._space_down = True
                                    self._win_space = True
                                    self._fire()
                                    # 空格被吃掉后，系统就看不到任何伴随键了，
                                    # 松开 Win 时会当成"孤零零的 Win 按下"而弹出
                                    # 开始菜单。补一个 Shift 当伴随键（见 _companion_key）
                                    self._companion_key()
                            else:
                                self._space_down = False
                            return 1    # 吃掉空格：系统不会按 Win+Space 打开搜索面板
                        self._space_down = False
        except Exception:              # 回调里绝不能抛异常（会被吞掉按键）
            pass
        return _user32.CallNextHookEx(self._hook_handle, n_code, w_param, l_param)

    def _companion_key(self):
        """注入一次 Shift（按下+松开）作为"伴随键"。

        系统只在松开 Win 时看到"孤零零的 Win 按下"才弹开始菜单；空格被
        吃掉后系统就看不到任何伴随键了，于是松开 Win 就会弹开始菜单
        （用户反馈的现象）。这里补一次 Shift：系统看到 Win 旁边还按过别的
        键，就不会再弹开始菜单。

        同时 Win 的抬起照常放行，系统按键状态不留脏——否则之后单独敲个
        E 会被当成 Win+E 弹出资源管理器。

        选 Shift 的原因：修饰键不产生字符，按下与松开成对，多数程序
        对它没有感知（实测系统确实把它当作伴随键）。
        """
        try:
            _user32.keybd_event(VK_SHIFT, 0, 0, 0)
            _user32.keybd_event(VK_SHIFT, 0, KEYEVENTF_KEYUP, 0)
        except Exception:
            pass

    def _fire(self):
        """触发快捷键：投递到事件循环，避免在钩子回调里做耗时操作。"""
        QTimer.singleShot(0, self.triggered.emit)
