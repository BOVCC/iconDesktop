"""bugs.txt 里各项的回归测试（离屏运行：python bugs_test.py）。

覆盖六项：
1. 重复添加同一个 exe 不再产生 "名称 (2).lnk"，并提示「已存在」
2. 同一目标不同写法（大小写 / 8.3 短名）也算重复
3. 「打开文件夹」按钮：打开存放快捷方式的文件夹
4. 右键「打开所在文件夹」：定位到程序真正所在的目录
5. 「资源管理器」按钮：把 explorer.exe（系统命令）按现有方式加入图标桌面
6. Win+Space 全局快捷键：注册/注销，以及触发后窗口显隐切换
"""
import ctypes
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.pop("ICONDESKTOP_CONFIG_LOCATION", None)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu, QPushButton  # noqa: E402

import app.config as config_module  # noqa: E402
import app.hotkey as hotkey_module  # noqa: E402
import app.icon_grid as icon_grid_module  # noqa: E402
from app import hotkey, lnk_utils, scanner  # noqa: E402
from app.icon_grid import IconGrid  # noqa: E402
from app.main_window import MainWindow  # noqa: E402

NOTEPAD = r"C:\Windows\System32\notepad.exe"
CALC = r"C:\Windows\System32\calc.exe"


def find_button(window, text):
    """按文字找工具栏按钮。"""
    for button in window.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"没找到按钮：{text}")


def shortcut_files(folder):
    return sorted(p.name for p in Path(folder).glob("*.lnk"))


# ---- 1. 重复添加不再出现 "(2)" ----
def test_no_duplicate_entries(app):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        folder = tmp_path / "快捷方式"
        folder.mkdir()
        source = tmp_path / "记事本.exe"
        source.write_bytes(Path(NOTEPAD).read_bytes())

        original_folder = scanner.shortcut_folder
        original_cfg = config_module.CONFIG_PATH
        scanner.shortcut_folder = lambda: folder
        config_module.CONFIG_PATH = tmp_path / "config.json"
        try:
            win = MainWindow()
            win.add_files([str(source)])
            assert shortcut_files(folder) == ["记事本.lnk"], shortcut_files(folder)

            # 同一个程序再加一次：不应产生 "记事本 (2).lnk"
            win.add_files([str(source)])
            assert shortcut_files(folder) == ["记事本.lnk"], shortcut_files(folder)
            assert "已存在" in win.statusBar().currentMessage(), \
                win.statusBar().currentMessage()

            # 同一路径、不同写法（大小写）同样算重复
            win.add_files([str(source).upper()])
            assert shortcut_files(folder) == ["记事本.lnk"], shortcut_files(folder)

            # 换一个程序：正常新增，不受去重影响
            other = tmp_path / "计算器.exe"
            other.write_bytes(Path(CALC).read_bytes())
            win.add_files([str(other)])
            assert set(shortcut_files(folder)) == {"记事本.lnk", "计算器.lnk"}, \
                shortcut_files(folder)
            win.close()
        finally:
            scanner.shortcut_folder = original_folder
            config_module.CONFIG_PATH = original_cfg
    print("[OK] 重复添加同一个 exe 不再产生 (2)，并提示「已存在」")


# ---- 2. 同名不同目标：名字被占用才退让为 "(2)" ----
def test_same_name_different_target(app):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        first = tmp_path / "a.exe"
        second = tmp_path / "b.exe"
        first.write_bytes(Path(NOTEPAD).read_bytes())
        second.write_bytes(Path(CALC).read_bytes())
        p1 = lnk_utils.create_shortcut(tmp_path, "同名", str(first))
        p2 = lnk_utils.create_shortcut(tmp_path, "同名", str(second))
        assert Path(p1).name == "同名.lnk", Path(p1).name
        assert Path(p2).name == "同名 (2).lnk", Path(p2).name
        # 两个条目都指向各自的目标，没被合并
        assert lnk_utils.resolve_lnk(str(p1))[0].lower() == str(first).lower()
        assert lnk_utils.resolve_lnk(str(p2))[0].lower() == str(second).lower()
    print("[OK] 名字被占用时才退让为「(2)」，不同目标不会被合并")


# ---- 3. 「打开文件夹」按钮 ----
def test_open_shortcut_folder_button(app):
    opened = []
    original = scanner.open_in_explorer
    scanner.open_in_explorer = lambda path: opened.append(str(path)) or True
    try:
        win = MainWindow()
        find_button(win, "打开文件夹").click()
        assert opened, "点击后没有打开文件夹"
        assert Path(opened[0]).name == "快捷方式", opened[0]
        win.close()
    finally:
        scanner.open_in_explorer = original
    print("[OK] 「打开文件夹」按钮打开存放快捷方式的文件夹")


# ---- 4. 右键「打开所在文件夹」 ----
class FakeAction:
    """替身菜单项：只提供文字。"""

    def __init__(self, text):
        self._text = text

    def text(self):
        return self._text


class FakeMenu:
    """替身菜单：记录菜单项，并按文字选中其中一项。

    直接改写 QMenu.exec 不管用：PySide6 的实例方法调用不走 Python 类字典，
    真实 exec() 会在离屏模式下一直等输入（阻塞）。因此替换 icon_grid 模块
    里的 QMenu 名字。
    """

    picked = None

    def __init__(self, parent=None):
        self._actions = []

    def addAction(self, text):
        action = FakeAction(text)
        self._actions.append(action)
        return action

    def addSeparator(self):
        return None

    def actions(self):
        return list(self._actions)

    def exec(self, *args):
        FakeMenu.picked = [a.text() for a in self._actions]
        for action in self._actions:
            if "打开所在文件夹" in action.text():
                return action
        return None


def test_open_item_folder(app):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        folder = tmp_path / "快捷方式"
        folder.mkdir()
        lnk_utils.create_shortcut(folder, "记事本", NOTEPAD)

        original_folder = scanner.shortcut_folder
        original_cfg = config_module.CONFIG_PATH
        original_menu = icon_grid_module.QMenu
        opened = []
        original_open = scanner.open_folder_of
        scanner.shortcut_folder = lambda: folder
        config_module.CONFIG_PATH = tmp_path / "config.json"
        scanner.open_folder_of = lambda target: opened.append(str(target)) or True
        try:
            win = MainWindow()
            grid = win.grid
            assert grid.count() == 1, grid.count()

            # 右键菜单里要有「打开所在文件夹」，且点了会发信号
            icon_grid_module.QMenu = FakeMenu
            try:
                item = grid.item(0)
                rect = grid.visualItemRect(item)
                grid._show_menu(rect.center())
            finally:
                icon_grid_module.QMenu = original_menu

            assert FakeMenu.picked, "右键菜单没有打开"
            assert any("打开所在文件夹" in t for t in FakeMenu.picked), FakeMenu.picked

            # 主窗口收到信号后定位到程序真正所在的目录
            assert opened, "没有打开所在文件夹"
            assert Path(opened[0]).name.lower() == "notepad.exe", opened[0]
            assert Path(opened[0]).parent != folder, "应定位到程序目录而不是快捷方式目录"
            win.close()
        finally:
            scanner.open_folder_of = original_open
            scanner.shortcut_folder = original_folder
            config_module.CONFIG_PATH = original_cfg
    print("[OK] 右键「打开所在文件夹」定位到程序所在目录")


# ---- 4b. 打开所在文件夹：不能用 /select, 语法 ----
def test_open_folder_command(app):
    """打开所在文件夹时不能带 /select, 参数。

    explorer.exe /select,<路径> 在路径带空格时会被 Explorer 解析失败，
    它找不到路径就退回自己的默认目录（"文档"），表现为不管点哪个图标
    都打开"文档"。这里检查最终交给 explorer.exe 的命令行。
    """
    calls = []
    original_popen = scanner.subprocess.Popen

    def fake_popen(args, **kwargs):
        calls.append(list(args))
        return None

    scanner.subprocess.Popen = fake_popen
    try:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            folder = tmp_path / "带 空格的目录"
            folder.mkdir()
            target = folder / "某个程序.exe"
            target.write_bytes(b"")

            assert scanner.open_folder_of(str(target)) is True
            assert calls, "没有调用 explorer"
            argv = calls[-1]
            assert len(argv) == 2, argv
            assert not any(str(a).startswith("/select") for a in argv), \
                f"不能带 /select 参数：{argv}"
            assert argv[1] == str(folder), f"应打开所在文件夹：{argv}"
            assert " " in argv[1], "测试路径应含空格（那正是出问题的场景）"
    finally:
        scanner.subprocess.Popen = original_popen
    print("[OK] 打开所在文件夹用 explorer.exe <目录>，不带 /select")


# ---- 5. 文件资源管理器（系统命令）按现有方式加入 ----
def test_add_file_explorer(app):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        folder = tmp_path / "快捷方式"
        folder.mkdir()
        source = tmp_path / "记事本.exe"
        source.write_bytes(Path(NOTEPAD).read_bytes())

        original_folder = scanner.shortcut_folder
        original_cfg = config_module.CONFIG_PATH
        scanner.shortcut_folder = lambda: folder
        config_module.CONFIG_PATH = tmp_path / "config.json"
        try:
            win = MainWindow()
            win.add_files([str(source)])
            find_button(win, "资源管理器").click()

            assert "文件资源管理器.lnk" in shortcut_files(folder), shortcut_files(folder)
            lnk_path = folder / "文件资源管理器.lnk"
            target = lnk_utils.resolve_lnk(str(lnk_path))[0]
            assert target.lower().endswith("explorer.exe"), target
            # 图标能正常取到（走的是和其它条目一样的图标提取）
            assert win.grid.count() == 2, win.grid.count()

            # 再点一次不会产生第二份
            find_button(win, "资源管理器").click()
            assert shortcut_files(folder).count("文件资源管理器.lnk") == 1, \
                shortcut_files(folder)
            win.close()
        finally:
            scanner.shortcut_folder = original_folder
            config_module.CONFIG_PATH = original_cfg
    print("[OK] 「资源管理器」按钮把文件资源管理器按现有方式加入图标桌面")


# ---- 6. Win+Space 全局快捷键 ----
def test_global_hotkey(app):
    key = hotkey.GlobalHotkey()
    assert not key.active, "未注册时不应是激活状态"

    hwnd = int(MainWindow().winId())
    assert key.register(hwnd), "Win+Space 注册失败（RegisterHotKey 与钩子都不行）"
    assert key.active, "注册后应为激活状态"
    key.unregister()
    assert not key.active, "注销后不应是激活状态"
    print("[OK] Win+Space 快捷键可注册/注销")


def test_hotkey_toggles_window(app):
    win = MainWindow()
    win.show()
    app.processEvents()
    assert win.hotkey.active, "窗口显示后应已注册快捷键"
    assert win.isVisible()

    # 触发快捷键 → 隐藏；再触发 → 显示
    win.hotkey.triggered.emit()
    app.processEvents()
    assert not win.isVisible(), "触发后窗口应隐藏"

    win.hotkey.triggered.emit()
    app.processEvents()
    assert win.isVisible(), "再次触发后窗口应显示"

    win.hotkey.unregister()
    win.close()
    print("[OK] Win+Space 触发后窗口显隐切换")


def test_hotkey_detects_win_space(app):
    """低级钩子能认出 Win+Space，吃掉空格，并补一个伴随键。"""
    key = hotkey.GlobalHotkey()
    fired = []
    key.triggered.connect(lambda: fired.append(1))

    companions = []
    original_companion = hotkey.GlobalHotkey._companion_key
    hotkey.GlobalHotkey._companion_key = lambda self: companions.append(1)
    try:
        def hook(vk, message):
            data = hotkey_module._KBDLLHOOKSTRUCT()
            data.vkCode = vk
            buf = ctypes.create_string_buffer(ctypes.sizeof(data))
            ctypes.memmove(buf, ctypes.byref(data), ctypes.sizeof(data))
            address = ctypes.cast(buf, ctypes.c_void_p).value
            return key._hook_callback(hotkey_module.HC_ACTION, message, address)

        down, up = hotkey_module.WM_KEYDOWN, hotkey_module.WM_KEYUP
        win_key, space = hotkey_module.VK_LWIN, hotkey_module.VK_SPACE

        # 没按 Win 时，空格照常传给系统（返回值 0 = 不拦截）
        assert hook(space, down) == 0, "普通空格不应被拦截"
        app.processEvents()
        assert not fired, "普通空格不应触发"

        # 按下 Win（放行，系统要看到这次 Win 按下）
        assert hook(win_key, down) == 0, "Win 按下应放行"

        # 再按空格：应触发、吃掉空格，并补一个伴随键
        assert hook(space, down) == 1, "Win+空格应被吃掉"
        app.processEvents()      # 触发是投递到事件循环的
        assert len(fired) == 1, fired
        assert len(companions) == 1, "应补一个伴随键（否则松开 Win 会弹开始菜单）"

        # 长按空格不重复触发（空格没松开）
        assert hook(space, down) == 1, "长按空格仍应被吃掉"
        app.processEvents()
        assert len(fired) == 1, "长按空格不应重复触发"

        # 空格松开：仍被吃掉
        assert hook(space, up) == 1, "空格的抬起也应被吃掉"

        # 松开 Win：必须放行。吞掉它会让系统以为 Win 还按着，之后单独敲个
        # E 会被当成 Win+E 弹出资源管理器
        assert hook(win_key, up) == 0, "Win 的抬起应放行（保持系统按键状态干净）"

        # 松开 Win 后，普通空格不再被拦截、也不再触发
        assert hook(space, down) == 0, "松开 Win 后空格不应被拦截"
        app.processEvents()
        assert len(fired) == 1, "松开 Win 后不应再触发"
    finally:
        hotkey.GlobalHotkey._companion_key = original_companion
    print("[OK] 钩子识别 Win+Space、吃掉空格并补伴随键，Win 抬起放行")


def main():
    app = QApplication(sys.argv)
    test_no_duplicate_entries(app)
    test_same_name_different_target(app)
    test_open_shortcut_folder_button(app)
    test_open_item_folder(app)
    test_open_folder_command(app)
    test_add_file_explorer(app)
    test_global_hotkey(app)
    test_hotkey_toggles_window(app)
    test_hotkey_detects_win_space(app)
    print("\n全部 bug 回归测试通过")


if __name__ == "__main__":
    main()
