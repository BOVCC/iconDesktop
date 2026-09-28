"""拖拽排序回归测试：验证自由格子摆放、空格落位、占用互换与落点阴影。

离屏运行（python drag_test.py），用合成鼠标事件驱动自实现的拖拽流程：
- 拖到空白格子 → 图标停在该格（允许中间留空，与桌面图标一致）
- 拖到已占用格子 → 两个图标互换
- 阴影实时吸附光标所在格子（截屏存 drag_ghost.png 供人工确认）
- 视口外松手吸附到边缘、Esc 取消、边缘自动滚动、普通单击链路
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent, QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.icon_grid import DATA_ROLE, IconGrid  # noqa: E402

GW, GH = 108, 122


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
        make_event(
            QEvent.Type.MouseButtonRelease, pos, Qt.LeftButton, Qt.NoButton
        ),
    )


def cell_pos(col, row):
    return QPoint(col * GW + GW // 2, row * GH + GH // 2)


def cells(grid):
    return dict(grid._cells)


def center(grid, row):
    return grid.visualItemRect(grid.item(row)).center()


def lerp(a, b, t):
    return QPoint(
        round(a.x() + (b.x() - a.x()) * t),
        round(a.y() + (b.y() - a.y()) * t),
    )


def drag(grid, from_row, to_pos, via=None):
    """从 from_row 图标按住拖到 to_pos 松手；via 为途中必经点（绕行用）。"""
    start = center(grid, from_row)
    origin = via if via is not None else start
    waypoints = []
    if via is not None:
        waypoints.append(lerp(start, via, 0.5))
        waypoints.append(via)
    waypoints += [lerp(origin, to_pos, t) for t in (0.34, 0.67)]
    waypoints.append(to_pos)
    mouse_press(grid, start)
    for pos in waypoints:
        mouse_move(grid, pos)
    assert grid._drag_active, f"拖拽未激活 (from_row={from_row})"
    mouse_release(grid, to_pos)


def main():
    app = QApplication(sys.argv)
    grid = IconGrid()
    grid.resize(600, 500)
    grid.populate(
        [
            {"name": f"App{i}", "path": f"C:/apps/app{i}.exe", "args": "", "workdir": ""}
            for i in range(6)
        ]
    )
    grid.show()
    app.processEvents()

    clicked, failed = [], []
    grid.itemClicked.connect(lambda item: clicked.append(item.text()))
    grid.launch_failed.connect(lambda msg: failed.append(msg))

    # 初始摆放：无坐标时按名称次序流式填充（每行 5 格）
    assert cells(grid) == {
        "C:/apps/app0.exe": (0, 0),
        "C:/apps/app1.exe": (1, 0),
        "C:/apps/app2.exe": (2, 0),
        "C:/apps/app3.exe": (3, 0),
        "C:/apps/app4.exe": (4, 0),
        "C:/apps/app5.exe": (0, 1),
    }, cells(grid)
    print("[OK] 初始摆放按名称次序流式填充")

    # 1. 拖到空白格子 → 图标停在那一格，其他图标不动
    assert grid._target_cell_at(cell_pos(2, 1)) == (2, 1)
    mouse_press(grid, center(grid, 0))
    mouse_move(grid, cell_pos(2, 1))
    assert grid._target_cell == (2, 1), grid._target_cell
    assert grid._ghost_rect() == QRect(2 * GW, 1 * GH, GW, GH), "阴影应在空格上"
    ghost = grid.viewport().grab()
    assert not ghost.isNull()
    ghost.save("drag_ghost.png")
    mouse_release(grid, cell_pos(2, 1))
    assert grid._cells["C:/apps/app0.exe"] == (2, 1), grid._cells
    assert grid.visualItemRect(grid.item(0)) == QRect(2 * GW, 1 * GH, GW, GH)
    assert cells(grid)["C:/apps/app2.exe"] == (2, 0), "其他图标不应移动"
    print("[OK] 空白格子落位（允许留空）:", cells(grid))

    # 2. 拖到已占用格子 → 两个图标互换
    drag(grid, 0, center(grid, 2))
    assert grid._cells["C:/apps/app0.exe"] == (2, 0)
    assert grid._cells["C:/apps/app2.exe"] == (2, 1)
    print("[OK] 占用格子互换")

    # 3. 绕行后拖回自身格子 → 顺序与坐标不变
    before = cells(grid)
    drag(grid, 0, center(grid, 0), via=center(grid, 1))
    assert cells(grid) == before, cells(grid)
    print("[OK] 拖到自身不改变布局")

    # 4. 边缘自动滚动：拖到视口底边触发，移开后停止；落点互换
    mouse_press(grid, center(grid, 0))
    mouse_move(grid, QPoint(center(grid, 0).x(), grid.viewport().height() - 5))
    assert grid._scroll_step != 0 and grid._scroll_timer.isActive()
    mouse_move(grid, center(grid, 2))
    assert grid._scroll_step == 0 and not grid._scroll_timer.isActive()
    mouse_release(grid, center(grid, 2))
    assert grid._cells["C:/apps/app0.exe"] == (2, 1)
    assert grid._cells["C:/apps/app2.exe"] == (2, 0)
    print("[OK] 拖拽边缘自动滚动启停正常")

    # 5. 普通单击仍走点击链路（假路径会发 launch_failed，正好证明链路通了）
    mouse_press(grid, center(grid, 0))
    mouse_release(grid, center(grid, 0))
    assert clicked == ["App0"], clicked
    assert failed, "单击启动链路未触发"
    print("[OK] 普通单击仍触发启动链路")

    # 6. Esc 取消；随后在别的格子上松手不应触发单击
    before = cells(grid)
    mouse_press(grid, center(grid, 0))
    mouse_move(grid, center(grid, 3))
    assert grid._drag_active
    QApplication.sendEvent(
        grid, QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Escape, Qt.NoModifier)
    )
    assert not grid._drag_active
    mouse_release(grid, center(grid, 3))
    assert not clicked or clicked[-1] == "App0", "Esc 取消后不应触发单击"
    assert cells(grid) == before, cells(grid)
    print("[OK] Esc 取消拖拽")

    # 7. 视口外松手 → 吸附到视口边缘最近的格子（右下角远处 = (5,4)）
    drag(grid, 0, QPoint(1200, 900))
    assert grid._cells["C:/apps/app0.exe"] == (5, 4), grid._cells
    assert not grid._drag_active
    print("[OK] 视口外松手吸附边缘格子")

    # 8. 坐标导出：positions() 为 [列, 行] 列表；apps() 按行列排序
    exported = grid.positions()
    assert exported["C:/apps/app0.exe"] == [5, 4], exported
    assert grid.apps()[0]["name"] == "App1", grid.apps()
    assert grid.apps()[-1]["name"] == "App0", grid.apps()
    print("[OK] 坐标与顺序导出正常")

    print("\n全部拖拽测试通过")


if __name__ == "__main__":
    main()
