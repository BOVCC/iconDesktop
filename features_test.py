"""新功能回归测试（离屏运行：python features_test.py）。

覆盖五项改动：
1. 图标刷新：应用更新覆盖了 exe 后，重新提取（刷新按钮做的事）立即换新图标，
   不必重启程序；文件没变时复用缓存
2. 拖拽中滚轮翻页：自管拖拽（不进 QDrag 的 OLE 模态循环）里滚轮即翻页，
   翻页后松手可跨页落位
3. 翻页栏：页位点鼠标放上去即翻页（拖动图标时同样生效），松手在翻页栏 =
   取消本次拖动；外部文件拖到翻页栏也能添加
4. 「全部快捷方式」窗口：收集开始菜单/桌面快捷方式（按名去重、跳过非 lnk、
   已有项打角标）、多选、加入图标桌面
5. 文件拖放：exe/lnk 拖到网格或窗口其它位置都会自动添加，非法文件忽略
6. 删除图标：界面立即更新（不需要再点刷新），配置与图标缓存同步清理
7. 多选选择模式：没有橡皮筋框选，单击切换/Shift 连选/全选照常
"""
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (  # noqa: E402
    QEvent,
    QEventLoop,
    QMimeData,
    QPoint,
    QPointF,
    QSize,
    Qt,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import app.config as config_module  # noqa: E402
import app.shortcut_sources as shortcut_sources  # noqa: E402
from app import lnk_utils, scanner, win_icons  # noqa: E402
from app.all_shortcuts_dialog import AllShortcutsDialog  # noqa: E402
from app.icon_grid import BADGE_ROLE, DATA_ROLE, IconGrid, PageBar  # noqa: E402
from app.main_window import MainWindow  # noqa: E402

# 拖拽是自管实现（不走 QDrag 的 OLE 模态循环）：合成鼠标事件就是真实路径，
# 不需要替换任何方法，拖动中滚轮翻页也一并覆盖

NOTEPAD = r"C:\Windows\System32\notepad.exe"
CALC = r"C:\Windows\System32\calc.exe"
WINVER = r"C:\Windows\System32\winver.exe"
SHELL32 = r"C:\Windows\System32\shell32.dll"


# ---- 事件工具 ----
class StubDragEvent:
    """拖放事件替身：只提供本程序用到的接口（source/position/mimeData）。"""

    def __init__(self, source=None, pos=QPoint(0, 0), mime=None):
        self._source = source
        self._pos = pos
        self._mime = mime if mime is not None else QMimeData()
        self.accepted = False

    def source(self):
        return self._source

    def position(self):
        return QPointF(self._pos)

    def mimeData(self):
        return self._mime

    def acceptProposedAction(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


def make_event(etype, pos, button, buttons):
    return QMouseEvent(etype, QPointF(pos), button, buttons, Qt.NoModifier)


def mouse_press(view, pos):
    QApplication.sendEvent(
        view.viewport(),
        make_event(QEvent.Type.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton),
    )


def mouse_move(view, pos):
    QApplication.sendEvent(
        view.viewport(),
        make_event(QEvent.Type.MouseMove, pos, Qt.NoButton, Qt.LeftButton),
    )


def mouse_release(view, pos):
    QApplication.sendEvent(
        view.viewport(),
        make_event(QEvent.Type.MouseButtonRelease, pos, Qt.LeftButton, Qt.NoButton),
    )


def click(view, pos):
    mouse_press(view, pos)
    mouse_release(view, pos)


def key_press(widget, key, mods=Qt.NoModifier):
    QApplication.sendEvent(widget, QKeyEvent(QEvent.Type.KeyPress, key, mods))


def wheel(view, delta, ctrl=False):
    center = QPointF(view.viewport().rect().center())
    mods = Qt.ControlModifier if ctrl else Qt.NoModifier
    QApplication.sendEvent(
        view.viewport(),
        QWheelEvent(
            center, center, QPoint(), QPoint(0, delta),
            Qt.NoButton, mods, Qt.ScrollUpdate, False,
        ),
    )


def move_mouse(widget, pos):
    """给 PageBar 这类普通控件发鼠标移动（鼠标跟踪已开）。"""
    QApplication.sendEvent(
        widget, make_event(QEvent.Type.MouseMove, pos, Qt.NoButton, Qt.NoButton)
    )


def wait_ms(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def apps(n, folder="C:/apps"):
    return [
        {"name": f"App{i:02d}", "path": f"{folder}/app{i}.exe", "args": "", "workdir": ""}
        for i in range(n)
    ]


def make_grid(n, w=608, h=470):
    grid = IconGrid()
    grid.resize(w, h)
    grid.show()
    QApplication.processEvents()
    grid.populate(apps(n))
    QApplication.processEvents()
    return grid


def item_center(grid, row):
    return grid.visualItemRect(grid.item(row)).center()


def cell_center(grid, col, row):
    cw, ch = grid._cell.width(), grid._cell.height()
    return QPoint(grid._x_offset + col * cw + cw // 2, row * ch + ch // 2)


def icon_digest(item):
    image = item.icon().pixmap(QSize(256, 256)).toImage()
    return hashlib.md5(bytes(image.constBits())).hexdigest()


def names_of(grid):
    return [a["name"] for a in grid.apps()]


def tmp_lnk(folder, name, target, icon_location=""):
    return Path(
        lnk_utils.create_shortcut(str(folder), name, target, icon_location=icon_location)
    )


# ---- 1. 图标刷新 ----
def test_icon_refresh(app):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        target = tmp_path / "app.exe"
        target.write_bytes(Path(NOTEPAD).read_bytes())

        grid = IconGrid()
        grid.resize(600, 400)
        grid.show()
        app.processEvents()
        grid.populate(
            [{"name": "被更新的应用", "path": str(target), "args": "", "workdir": ""}]
        )
        app.processEvents()
        before = icon_digest(grid.item(0))
        assert win_icons.extract_icon_image(str(target)) is not None

        # 文件没变 → 复用同一个 QIcon 对象（不重复提取）
        path = str(target)
        assert grid._icon_for(path) is grid._icon_for(path)
        cached = grid._icon_for(path)

        # 模拟应用更新：同路径覆盖成另一个程序（图标不同）
        wait_ms(30)
        target.write_bytes(Path(CALC).read_bytes())
        after_reload = None
        grid.reload_icons()
        app.processEvents()
        after_reload = icon_digest(grid.item(0))
        assert after_reload != before, "刷新后图标未更新（外壳缓存未被绕过）"
        assert grid._icon_for(path) is not cached, "图标缓存未随时间戳失效"

        # 不点刷新、仅重新 populate 也应拿到新图标
        wait_ms(30)
        target.write_bytes(Path(NOTEPAD).read_bytes())
        grid.populate(
            [{"name": "被更新的应用", "path": str(target), "args": "", "workdir": ""}]
        )
        app.processEvents()
        assert icon_digest(grid.item(0)) == before, "回滚后应恢复原图标（说明按内容重取）"
        print("[OK] 应用更新后刷新即换新图标（直读文件资源，不用重启程序）")

    # lnk 的自定义图标索引（"shell32.dll,13"）应真正生效
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        idx13 = tmp_lnk(tmp_path, "索引13", NOTEPAD, f"{SHELL32},13")
        idx0 = tmp_lnk(tmp_path, "索引0", NOTEPAD, f"{SHELL32},0")
        assert lnk_utils.icon_source(str(idx13)) == (SHELL32, 13)
        assert lnk_utils.icon_source(str(idx0)) == (SHELL32, 0)
        grid = IconGrid()
        grid.resize(600, 400)
        grid.populate(
            [
                {"name": "索引13", "path": str(idx13), "args": "", "workdir": ""},
                {"name": "索引0", "path": str(idx0), "args": "", "workdir": ""},
            ]
        )
        app.processEvents()
        assert icon_digest(grid.item(0)) != icon_digest(grid.item(1)), (
            "不同图标索引应显示不同图标"
        )
        print("[OK] 快捷方式的自定义图标索引（path,index）生效")


# ---- 2. 拖拽中滚轮翻页 ----
def test_wheel_paging_while_dragging(app):
    grid = make_grid(20)
    assert grid.page_count() == 2, grid.page_count()
    mouse_press(grid, item_center(grid, 0))
    mouse_move(grid, cell_center(grid, 2, 0))
    assert grid._drag_active, "拖拽应已激活"
    wheel(grid, -120)
    assert grid.current_page() == 1, "拖拽中滚轮向下应翻到下一页"
    wheel(grid, 120)
    assert grid.current_page() == 0, "拖拽中滚轮向上应翻回上一页"
    key_press(grid, Qt.Key_Escape)
    mouse_release(grid, cell_center(grid, 2, 0))
    assert not grid._drag_active
    # 拖拽结束：滚轮回到常规翻页，不再有过滤器接管
    wheel(grid, -120)
    assert grid.current_page() == 1
    print("[OK] 拖拽中滚轮翻页（拖动图标到其他页）")


# ---- 3. 翻页栏悬停翻页 ----
def bar_with_pages(total=3, current=0, height=300):
    bar = PageBar()
    bar.resize(PageBar.WIDTH, height)
    bar.show()
    QApplication.processEvents()
    bar.set_pages(current, total)
    return bar


def dot_pos(bar, page):
    dots = bar._dots_rect()
    slot = dots.height() / bar._total
    return QPoint(bar.width() // 2, int(dots.top() + slot * (page + 0.5)))


def make_grid_with_bar(n, w=608, h=470):
    """网格 + 右侧翻页栏的组合（与主窗口同一布局关系）。"""
    from PySide6.QtWidgets import QHBoxLayout, QWidget

    holder = QWidget()
    holder.resize(w + PageBar.WIDTH + 16, h + 20)
    layout = QHBoxLayout(holder)
    layout.setContentsMargins(8, 8, 8, 8)
    layout.setSpacing(8)
    grid = IconGrid()
    bar = PageBar()
    layout.addWidget(grid, 1)
    layout.addWidget(bar)
    holder.show()
    QApplication.processEvents()
    grid.populate(apps(n))
    grid.page_changed.connect(bar.set_pages)
    bar.page_requested.connect(grid.goto_page)
    grid.set_page_bar(bar)
    bar.set_pages(grid.current_page(), grid.page_count())
    QApplication.processEvents()
    return holder, grid, bar


def test_hover_paging(app):
    # 1) 不拖动时：鼠标停在别的页位点上就翻页，掠过不翻页
    requests = []
    bar = bar_with_pages(3, 0)
    bar.page_requested.connect(requests.append)

    move_mouse(bar, dot_pos(bar, 2))
    assert requests == [], "停留时间不足时不应翻页"
    wait_ms(PageBar.HOVER_DELAY + 120)
    assert requests == [2], requests
    bar.set_pages(2, 3)          # 真实运行时由 page_changed 驱动

    move_mouse(bar, dot_pos(bar, 2))
    wait_ms(PageBar.HOVER_DELAY + 120)
    assert requests == [2], "停在当前页位点上不应翻页"

    move_mouse(bar, dot_pos(bar, 0))
    move_mouse(bar, QPoint(bar.width() // 2, 2))     # 迅速移到上箭头区
    wait_ms(PageBar.HOVER_DELAY + 120)
    assert requests == [2], "掠过不应翻页"

    move_mouse(bar, dot_pos(bar, 0))
    wait_ms(PageBar.HOVER_DELAY + 120)
    assert requests == [2, 0], requests

    # 2) 拖动图标时：鼠标移到右侧页位点上照样翻页（拖动中鼠标被网格独占，
    #    网格按全局坐标代转给翻页栏），松手在翻页栏上 = 取消本次拖动
    holder, grid, bar = make_grid_with_bar(40)
    order_before = grid.order()
    assert grid.page_count() >= 2, grid.page_count()
    mouse_press(grid, item_center(grid, 0))
    mouse_move(grid, cell_center(grid, 2, 0))
    assert grid._drag_active, "拖拽应已激活"
    # 光标移到第 2 个页位点上（换算成视口坐标后投递，模拟鼠标被网格独占）
    target_local = grid.viewport().mapFromGlobal(bar.mapToGlobal(dot_pos(bar, 1)))
    mouse_move(grid, target_local)
    assert grid.current_page() == 0, "停留时间不足时不应翻页"
    wait_ms(PageBar.HOVER_DELAY + 120)
    assert grid.current_page() == 1, "拖动中停在页位点上应翻页"
    assert grid._drag_active, "翻页后拖拽应继续"
    mouse_release(grid, target_local)
    assert not grid._drag_active
    assert grid.order() == order_before, "松手在翻页栏上应取消本次拖动（顺序不变）"
    assert not grid._drag_image.isVisible(), "取消后拖影应隐藏"

    # 3) 外部文件拖到翻页栏：不翻页，但照样接住（落在窗口任何位置都能添加）
    page_before = grid.current_page()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(NOTEPAD)])
    bar.dragEnterEvent(StubDragEvent(mime=mime))
    bar.dragMoveEvent(StubDragEvent(mime=mime, pos=dot_pos(bar, 0)))
    wait_ms(PageBar.HOVER_DELAY + 120)
    assert grid.current_page() == page_before, "拖文件时不应翻页"
    dropped = []
    bar.files_dropped.connect(dropped.extend)
    bar.dropEvent(StubDragEvent(mime=mime, pos=dot_pos(bar, 0)))
    assert dropped == [NOTEPAD], dropped
    print("[OK] 翻页栏悬停翻页（含拖动图标与拖文件两种情况）")


# ---- 4. 全部快捷方式窗口 ----
def make_source_roots(tmp_path):
    start = tmp_path / "开始菜单"
    desktop = tmp_path / "桌面"
    (start / "子目录").mkdir(parents=True)
    desktop.mkdir(parents=True)
    tmp_lnk(start, "记事本", NOTEPAD)
    tmp_lnk(start / "子目录", "计算器", CALC)
    tmp_lnk(start, "重复项", NOTEPAD)
    tmp_lnk(desktop, "重复项", CALC)          # 同名 → 保留开始菜单里的那份
    tmp_lnk(desktop, "桌面程序", CALC)
    (start / "说明.txt").write_text("不应被收集", encoding="utf-8")
    return [
        (start, "开始菜单"),
        (tmp_path / "不存在的目录", "公共开始菜单"),
        (desktop, "桌面"),
    ]


def test_shortcut_collection(app):
    with tempfile.TemporaryDirectory() as tmp:
        roots = make_source_roots(Path(tmp))
        entries = shortcut_sources.collect_shortcuts(roots)
        names = [e["name"] for e in entries]
        assert names == sorted(names, key=str.lower), names
        assert set(names) == {"重复项", "桌面程序", "计算器", "记事本"}, names
        by_name = {e["name"]: e for e in entries}
        assert by_name["重复项"]["source"] == "开始菜单", "同名应保留先扫描到的那份"
        assert by_name["计算器"]["source"] == "开始菜单"           # 子目录也收
        assert by_name["桌面程序"]["source"] == "桌面"
        assert all(e["path"].lower().endswith(".lnk") for e in entries)
        assert "开始菜单" in by_name["记事本"]["tip"]
        print(f"[OK] 收集快捷方式 {len(entries)} 项（子目录、去重、来源标注）")


def test_all_shortcuts_dialog(app):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        roots = make_source_roots(tmp_path)
        folder = tmp_path / "快捷方式"
        folder.mkdir()
        tmp_lnk(folder, "记事本", NOTEPAD)          # 已在图标桌面上（同名）

        original_roots = shortcut_sources.source_roots
        original_folder = scanner.shortcut_folder
        original_config = config_module.CONFIG_PATH
        shortcut_sources.source_roots = lambda: roots
        scanner.shortcut_folder = lambda: folder
        config_module.CONFIG_PATH = tmp_path / "config.json"
        try:
            dialog = AllShortcutsDialog()
            grid = dialog.grid
            assert grid.count() == 4, grid.count()
            assert grid.count() == len(shortcut_sources.collect_shortcuts(roots))
            # 懒加载图标：先摆名称，图标分批补齐
            assert grid.pending_icons() == grid.count(), grid.pending_icons()
            assert not dialog.add_btn.isEnabled(), "未选中时不应可添加"
            dialog.resize(880, 600)
            dialog.show()
            app.processEvents()

            # 已有项打角标
            badge_paths = [
                grid.item(i).data(DATA_ROLE)["path"]
                for i in range(grid.count())
                if grid.item(i).data(BADGE_ROLE)
            ]
            assert len(badge_paths) == 1, badge_paths
            assert Path(badge_paths[0]).stem == "记事本"

            wait_ms(400)
            assert grid.pending_icons() == 0, grid.pending_icons()
            assert all(not grid.item(i).icon().isNull() for i in range(grid.count()))

            # 多选：单击切换选中，可跨项累加
            click(grid, item_center(grid, 0))
            click(grid, item_center(grid, 3))
            assert len(grid.selected_paths()) == 2, grid.selected_paths()
            assert dialog.add_btn.isEnabled()
            assert "（2）" in dialog.add_btn.text(), dialog.add_btn.text()
            click(grid, item_center(grid, 3))          # 再点一次 = 取消选中
            assert len(grid.selected_paths()) == 1
            key_press(grid, Qt.Key_A, Qt.ControlModifier)
            assert len(grid.selected_paths()) == grid.count(), "Ctrl+A 应全选"
            dialog.grid_clear_selection()
            assert grid.selected_paths() == []

            # 选中项加入图标桌面（复用主窗口的添加逻辑）
            row = next(
                i for i in range(grid.count())
                if grid.item(i).text() == "计算器"
            )
            click(grid, item_center(grid, row))
            chosen = dialog.selected_apps()
            assert [a["name"] for a in chosen] == ["计算器"], chosen
            win = MainWindow()
            assert win.grid.count() == 1, win.grid.count()
            assert win._add_to_folder(chosen[0]) is True
            win._reload_apps()
            assert win.grid.count() == 2, "选中项应加入图标桌面"
            assert (folder / "计算器.lnk").exists(), os.listdir(folder)
            assert lnk_utils.resolve_lnk(str(folder / "计算器.lnk"))[0] == CALC
            dialog.close()
            win.close()
        finally:
            shortcut_sources.source_roots = original_roots
            scanner.shortcut_folder = original_folder
            config_module.CONFIG_PATH = original_config
        print("[OK] 「全部快捷方式」窗口：收集、角标、多选、加入图标桌面")


# ---- 5. 文件拖放添加 ----
def test_file_drop(app):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        folder = tmp_path / "快捷方式"
        folder.mkdir()
        source = tmp_path / "拖进来的程序.exe"
        source.write_bytes(Path(NOTEPAD).read_bytes())
        lnk_source = tmp_lnk(tmp_path, "拖进来的快捷方式", NOTEPAD)
        note = tmp_path / "说明.txt"
        note.write_text("不是启动项", encoding="utf-8")

        original_folder = scanner.shortcut_folder
        original_config = config_module.CONFIG_PATH
        scanner.shortcut_folder = lambda: folder
        config_module.CONFIG_PATH = tmp_path / "config.json"
        try:
            mime = QMimeData()
            mime.setUrls([
                QUrl.fromLocalFile(str(source)),
                QUrl.fromLocalFile(str(note)),          # 非 exe/lnk → 忽略
                QUrl.fromLocalFile(str(source)),        # 重复 → 只算一次
            ])
            assert scanner.file_paths_from_mime(mime) == [
                os.path.normpath(str(source))
            ], scanner.file_paths_from_mime(mime)

            win = MainWindow()
            assert win.grid.count() == 0
            hover = []
            win.grid.file_drag_hover.connect(hover.append)

            # 拖到网格上：拖动中亮提示，松手即添加
            enter = StubDragEvent(mime=mime)
            win.grid.dragEnterEvent(enter)
            assert enter.accepted and win.grid._file_hover and hover == [True]
            assert not win.grid.viewport().grab().isNull()
            drop = StubDragEvent(mime=mime)
            win.grid.dropEvent(drop)
            assert drop.accepted and not win.grid._file_hover and hover[-1] is False
            app.processEvents()
            assert win.grid.count() == 1, win.grid.count()
            assert (folder / "拖进来的程序.lnk").exists(), os.listdir(folder)
            assert os.path.normcase(
                lnk_utils.resolve_lnk(str(folder / "拖进来的程序.lnk"))[0]
            ) == os.path.normcase(str(source))
            assert win.grid.item(0).text() == "拖进来的程序"

            # 非启动项拖进来：不接收
            bad_mime = QMimeData()
            bad_mime.setUrls([QUrl.fromLocalFile(str(note))])
            bad = StubDragEvent(mime=bad_mime)
            win.grid.dragEnterEvent(bad)
            assert not bad.accepted, "txt 不应被接收"
            assert not win.grid._file_hover

            # 拖到窗口其它位置（工具条/标题栏）：窗口自己接手
            win_enter = StubDragEvent(mime=mime)
            win.dragEnterEvent(win_enter)
            assert win_enter.accepted, "窗口应接收 exe 拖放"
            win_drop = StubDragEvent(mime=mime)
            win.dropEvent(win_drop)
            app.processEvents()
            assert win.grid.count() == 1, "同目标重复添加应复用已有快捷方式"

            # lnk 拖进来同样可以（按快捷方式加入，保留目标信息）
            lnk_mime = QMimeData()
            lnk_mime.setUrls([QUrl.fromLocalFile(str(lnk_source))])
            win.grid.dropEvent(StubDragEvent(mime=lnk_mime))
            app.processEvents()
            assert win.grid.count() == 2, win.grid.count()
            assert (folder / "拖进来的快捷方式.lnk").exists(), os.listdir(folder)
            win.close()
        finally:
            scanner.shortcut_folder = original_folder
            config_module.CONFIG_PATH = original_config
        print("[OK] exe/lnk 拖到网格或窗口其它位置自动添加（含拖放提示）")


# ---- 6. 删除图标后界面立即更新 ----
def test_delete_immediate_refresh(app):
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        folder = tmp_path / "快捷方式"
        folder.mkdir()
        for name, target in (("甲", NOTEPAD), ("乙", CALC), ("丙", WINVER)):
            tmp_lnk(folder, name, target)

        original_folder = scanner.shortcut_folder
        original_config = config_module.CONFIG_PATH
        original_legacy = config_module.LEGACY_CONFIG_PATH
        original_question = QMessageBox.question
        scanner.shortcut_folder = lambda: folder
        config_module.CONFIG_PATH = tmp_path / "config.json"
        config_module.LEGACY_CONFIG_PATH = tmp_path / "legacy.json"
        # 关键：「丙」是刚拖进来、还没写进配置的条目（order 里只有甲、乙）。
        # 删除它时 prune_stale 会判定「配置无变化」—— 界面仍必须立刻更新。
        config_module.CONFIG_PATH.write_text(
            json.dumps({"order": [str(folder / "甲.lnk"), str(folder / "乙.lnk")]}),
            encoding="utf-8",
        )
        QMessageBox.question = lambda *a, **k: QMessageBox.StandardButton.Yes
        try:
            win = MainWindow()
            app.processEvents()
            assert win.grid.count() == 3, names_of(win.grid)

            victim = next(a for a in win.grid.apps() if a["name"] == "丙")
            assert win.grid._icon_for(victim["path"]) is not None

            # 只调 delete_app，不点刷新、不重新 populate
            win.delete_app(victim)
            app.processEvents()
            assert "丙" not in names_of(win.grid), f"删除后仍显示: {names_of(win.grid)}"
            assert win.grid.count() == 2, names_of(win.grid)
            assert not (folder / "丙.lnk").exists(), os.listdir(folder)
            assert str(victim["path"]) not in win.grid._icons, "图标缓存未随删除清理"

            # 删除配置里有的条目同样立即生效，并把 order 落盘
            victim = next(a for a in win.grid.apps() if a["name"] == "乙")
            win.delete_app(victim)
            app.processEvents()
            assert names_of(win.grid) == ["甲"], names_of(win.grid)
            assert not (folder / "乙.lnk").exists()
            saved = json.loads(config_module.CONFIG_PATH.read_text(encoding="utf-8"))
            assert saved["order"] == [str(folder / "甲.lnk")], saved["order"]
            win.close()
        finally:
            scanner.shortcut_folder = original_folder
            config_module.CONFIG_PATH = original_config
            config_module.LEGACY_CONFIG_PATH = original_legacy
            QMessageBox.question = original_question
        print("[OK] 删除图标后界面立即更新（配置无变化时也重载，缓存与配置同步清理）")


# ---- 7. 多选模式没有框选 ----
def mod_click(view, pos, mods):
    for etype, buttons in (
        (QEvent.Type.MouseButtonPress, Qt.LeftButton),
        (QEvent.Type.MouseButtonRelease, Qt.NoButton),
    ):
        QApplication.sendEvent(
            view.viewport(),
            QMouseEvent(etype, QPointF(pos), Qt.LeftButton, buttons, mods),
        )


def test_no_marquee_in_select_mode(app):
    grid = IconGrid()
    grid.resize(608, 470)
    grid.show()
    app.processEvents()
    grid.populate(apps(6))
    grid.set_select_mode(True)
    app.processEvents()
    assert not grid.isSelectionRectVisible(), "选择模式应关掉橡皮筋框选"

    # 空白处按住左键斜拖到某个图标上：不应框选到任何项
    empty = QPoint(grid.viewport().width() - 24, grid.viewport().height() - 24)
    target = item_center(grid, 2)
    mouse_press(grid, empty)
    for t in (0.3, 0.6, 1.0):
        cur = QPointF(empty) + (QPointF(target) - QPointF(empty)) * t
        mouse_move(grid, cur.toPoint())
    mouse_release(grid, target)
    app.processEvents()
    assert grid.selected_paths() == [], f"不应出现框选: {grid.selected_paths()}"

    # 框选没了，但单击切换 / Shift 连选 / Ctrl+A 照常
    click(grid, target)
    assert len(grid.selected_paths()) == 1, grid.selected_paths()
    click(grid, target)
    assert grid.selected_paths() == [], "再点一次应取消选中"

    mod_click(grid, item_center(grid, 0), Qt.NoModifier)
    mod_click(grid, item_center(grid, 3), Qt.ShiftModifier)
    assert len(grid.selected_paths()) == 4, grid.selected_paths()
    key_press(grid, Qt.Key_A, Qt.ControlModifier)
    assert len(grid.selected_paths()) == grid.count()

    # 拖拽整理/拖出在图标桌面照常，选择模式里不启动
    grid.set_select_mode(False)
    assert grid.isSelectionRectVisible(), "回到图标桌面应恢复默认行为"
    mouse_press(grid, item_center(grid, 0))
    mouse_move(grid, cell_center(grid, 2, 0))
    assert grid._drag_active, "图标桌面仍需支持拖动整理"
    key_press(grid, Qt.Key_Escape)
    mouse_release(grid, cell_center(grid, 2, 0))
    grid.close()
    print("[OK] 多选窗口无框选（单击切换/Shift 连选/全选照常）")


def main():
    app = QApplication(sys.argv)
    test_icon_refresh(app)
    test_wheel_paging_while_dragging(app)
    test_hover_paging(app)
    test_shortcut_collection(app)
    test_all_shortcuts_dialog(app)
    test_file_drop(app)
    test_delete_immediate_refresh(app)
    test_no_marquee_in_select_mode(app)
    print("\n全部新功能测试通过")


if __name__ == "__main__":
    main()
