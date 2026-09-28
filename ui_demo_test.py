"""演示桌面程序的 UI 测试手段：程序化截图 + 交互模拟。

不点真实鼠标 —— 用 Qt 事件与信号链模拟用户操作，让程序自己把界面渲染成 PNG。
在临时目录生成真实 .lnk 夹具并让扫描指向它（不影响用户的「快捷方式」文件夹）。
包含五个环节：
1. 生成夹具 → 选中第一项 → 完整界面截图（附带采样选中项/背景颜色）
2. 模拟搜索框输入 → 过滤后截图
3. 模拟右键点击图标 → 真实右键菜单弹出后截屏并关闭
4. 清理临时夹具
5. 退出
"""
import faulthandler
import shutil
import sys
import tempfile
from pathlib import Path

faulthandler.dump_traceback_later(30, exit=True)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QContextMenuEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from app import scanner  # noqa: E402
import app.config as config_module  # noqa: E402
from app.main_window import MainWindow  # noqa: E402

FIXTURES = [("记事本", "C:/Windows/System32/notepad.exe"),
            ("关于Windows", "C:/Windows/System32/winver.exe"),
            ("命令提示符", "C:/Windows/System32/cmd.exe")]


def make_fixtures():
    folder = Path(tempfile.mkdtemp(prefix="iconDesktop_ui_"))
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    shell = win32com.client.Dispatch("WScript.Shell")
    for name, target in FIXTURES:
        shortcut = shell.CreateShortCut(str(folder / f"{name}.lnk"))
        shortcut.Targetpath = target
        shortcut.save()
    return folder


def main():
    print("[1] 生成临时快捷方式夹具", flush=True)
    fixture_dir = make_fixtures()
    original_scan = scanner.scan_folder
    scanner.scan_folder = lambda: original_scan(fixture_dir)

    # 配置重定向到临时目录：测试全程（包括 app.quit() 触发 closeEvent 落盘）
    # 都不会读写用户真实的 config.json
    original_config = (config_module.CONFIG_PATH, config_module.LEGACY_CONFIG_PATH)
    config_dir = Path(tempfile.mkdtemp(prefix="iconDesktop_cfg_"))
    config_module.CONFIG_PATH = config_dir / "config.json"
    config_module.LEGACY_CONFIG_PATH = config_dir / "legacy.json"

    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # 与 main.py 保持一致
    win = MainWindow()
    win.show()
    total = win.grid.count()
    print(f"[2] 主窗口就绪，共 {total} 个应用", flush=True)

    def step1():
        # 选中第一项，验证选中态配色；同时采样关键像素颜色
        if total:
            win.grid.setCurrentRow(0)
        win.grab().save("ui_full.png")
        image = win.grid.viewport().grab().toImage()
        if total:
            rect = win.grid.visualItemRect(win.grid.item(0))
            sel = image.pixelColor(rect.left() + 8, rect.top() + 8)
            print(f"[3] 选中项背景色: {sel.name()}", flush=True)
        bg = image.pixelColor(image.width() - 20, image.height() // 2)
        print(f"[3] 界面背景色: {bg.name()}", flush=True)
        print("[3] 完整界面截图完成", flush=True)
        # 模拟用户在搜索框输入第一项名称前两个字符（触发实时过滤）
        win.search_box.setText(win.grid.item(0).text()[:2] if total else "无")
        QTimer.singleShot(600, step2)

    def step2():
        win.grab().save("ui_filtered.png")
        visible = sum(
            0 if win.grid.isRowHidden(i) else 1 for i in range(win.grid.count())
        )
        print(f"[4] 过滤后可见 {visible} 个应用", flush=True)

        # 右键点击第一个"可见"图标（过滤后靠前的图标可能已被隐藏）
        target = next(
            (
                win.grid.item(i)
                for i in range(win.grid.count())
                if not win.grid.isRowHidden(i)
            ),
            None,
        )
        if target is None:
            app.quit()
            return
        rect = win.grid.visualItemRect(target)
        pos = rect.center()
        # Qt 的 CustomContextMenu 策略监听 QContextMenuEvent（而非鼠标事件）
        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, pos, win.grid.mapToGlobal(pos)
        )
        # 关键时序：菜单的 exec 会阻塞在 sendEvent 内部的嵌套事件循环里，
        # 捕获定时器必须先注册，它才会在嵌套循环中触发
        QTimer.singleShot(500, step3)
        QApplication.sendEvent(win.grid.viewport(), event)
        # 兜底：若菜单未打开（sendEvent 立即返回），稍后退出
        QTimer.singleShot(800, app.quit)

    def step3():
        # 菜单此刻正以弹出窗口形式打开（阻塞在 exec 里），抓取并关闭它
        popup = QApplication.activePopupWidget()
        if isinstance(popup, QMenu):
            popup.grab().save("ui_menu.png")
            items = [a.text() for a in popup.actions() if a.text()]
            print(f"[5] 右键菜单已捕获，菜单项: {items}", flush=True)
            popup.close()
        else:
            print("[5] 未捕获到弹出菜单", flush=True)
        QTimer.singleShot(400, step4)

    def step4():
        scanner.scan_folder = original_scan
        shutil.rmtree(fixture_dir, ignore_errors=True)
        print("[6] 临时夹具已清理", flush=True)
        app.quit()

    try:
        QTimer.singleShot(2500, step1)
        app.exec()
    finally:
        scanner.scan_folder = original_scan
        config_module.CONFIG_PATH, config_module.LEGACY_CONFIG_PATH = original_config
        shutil.rmtree(fixture_dir, ignore_errors=True)
    print("[7] 应用正常退出", flush=True)


if __name__ == "__main__":
    main()
