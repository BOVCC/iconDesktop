"""分页网格回归测试：验证紧凑分页、分区整理、缩放限制、翻页键与翻页栏。

离屏运行（python drag_test.py），用合成鼠标/键盘事件驱动自实现的拖拽与翻页：
- 图标按顺序紧凑铺满每页，新应用自动追加到末尾空位（不会压在旧图标下）
- 落点按光标在目标格子内的横向位置分区（手机桌面式，任意图标都能触发）：
  中间 50% 宽度 → 与目标图标互换；左 1/4 边缘 → 插到目标之前；
  右 1/4 边缘 → 插到目标之后；区间图标向原位方向顺移一格补位
- 悬停时受影响图标实时动画偏移到插入后的位置（中间区不偏移），落位与预览一致
- 页尾空白落点 → 移到本页最后一个可见项之后
- A/D、←/→ 翻页；Ctrl+滚轮缩放、普通滚轮翻页
- 格子宽高比固定 2:3，最小缩到 40×60
- 翻页栏：箭头/页位点命中与跳转信号、单页自动隐藏
- 落点阴影吸附插入点、Esc 取消、无滚动条
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import (  # noqa: E402
    QEvent,
    QEventLoop,
    QPoint,
    QPointF,
    QRect,
    QSize,
    Qt,
    QTimer,
)
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QIcon,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.icon_grid import ICON_RENDER_SIZE, MIN_CELL_W, IconGrid, PageBar  # noqa: E402

# 离屏测试没有真实拖拽循环：把 QDrag.exec 换成空转，让合成鼠标事件继续
# 驱动 _update_drag/_finish_drag（真实运行时 _exec_drag 阻塞到松手/取消）
IconGrid._exec_drag = lambda self, drag: None


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


def key_press(grid, key, mods=Qt.NoModifier):
    QApplication.sendEvent(
        grid, QKeyEvent(QEvent.Type.KeyPress, key, mods)
    )


def wheel(grid, delta, ctrl=False):
    center = QPointF(grid.viewport().rect().center())
    mods = Qt.ControlModifier if ctrl else Qt.NoModifier
    QApplication.sendEvent(
        grid.viewport(),
        QWheelEvent(
            center, center, QPoint(), QPoint(0, delta),
            Qt.NoButton, mods, Qt.ScrollUpdate, False,
        ),
    )


def apps(n):
    return [
        {"name": f"App{i:02d}", "path": f"C:/apps/app{i}.exe", "args": "", "workdir": ""}
        for i in range(n)
    ]


def make_grid(n, order=None, w=608, h=470):
    grid = IconGrid()
    grid.resize(w, h)
    grid.show()
    QApplication.processEvents()
    grid.populate(apps(n), order)
    QApplication.processEvents()
    return grid


def names(grid):
    return [a["name"] for a in grid.apps()]


def visible_names(grid):
    return [
        grid.item(i).text()
        for i in range(grid.count())
        if not grid.isRowHidden(i)
    ]


def cell_center(grid, col, row):
    cw, ch = grid._cell.width(), grid._cell.height()
    return QPoint(grid._x_offset + col * cw + cw // 2, row * ch + ch // 2)


def cell_left(grid, col, row):
    """格子左 1/4 边缘内的点（插入到该格子图标之前）。"""
    cw, ch = grid._cell.width(), grid._cell.height()
    return QPoint(grid._x_offset + col * cw + max(1, cw // 8), row * ch + ch // 2)


def cell_right(grid, col, row):
    """格子右 1/4 边缘内的点（插入到该格子图标之后）。"""
    cw, ch = grid._cell.width(), grid._cell.height()
    return QPoint(grid._x_offset + col * cw + cw - 1 - max(1, cw // 8),
                  row * ch + ch // 2)


def item_center(grid, row):
    return grid.visualItemRect(grid.item(row)).center()


def rects(grid):
    return {grid.item(i).text(): grid.visualItemRect(grid.item(i)) for i in range(grid.count()) if not grid.isRowHidden(i)}


def drag(grid, from_row, to_pos):
    start = item_center(grid, from_row)
    mouse_press(grid, start)
    for t in (0.34, 0.67, 1.0):
        cur = start + (to_pos - start) * t
        mouse_move(grid, QPoint(cur.x(), cur.y()))
    assert grid._drag_active, f"拖拽未激活 (from_row={from_row})"
    mouse_release(grid, to_pos)


def click(widget, pos):
    QApplication.sendEvent(
        widget,
        make_event(QEvent.Type.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton),
    )
    QApplication.sendEvent(
        widget,
        make_event(QEvent.Type.MouseButtonRelease, pos, Qt.LeftButton, Qt.NoButton),
    )


def wait_anim():
    """等悬停预览动画播完（180ms + 余量）。"""
    loop = QEventLoop()
    QTimer.singleShot(300, loop.quit)
    loop.exec()


def main():
    app = QApplication(sys.argv)
    clicked, failed = [], []
    changes = []

    # 0. 基础布局：608×470 视口 → 每行 6 格（606/96），每页 6×3=18 格
    grid = make_grid(6)
    assert grid._cols == 6 and grid._rows == 3, (grid._cols, grid._rows)
    assert grid._per_page == 18
    assert grid.page_count() == 1 and grid.current_page() == 0
    assert not grid.horizontalScrollBar().isVisible(), "不应出现横向滚动条"
    assert not grid.verticalScrollBar().isVisible(), "不应出现纵向滚动条"
    print(f"[OK] 分页布局就绪：{grid._cols}×{grid._rows}/页，无滚动条")

    # 1. 初始摆放：紧凑铺满第一行，格子 2:3，互不重叠
    assert names(grid) == [f"App{i:02d}" for i in range(6)], names(grid)
    cw, ch = grid._cell.width(), grid._cell.height()
    assert abs(ch / cw - 1.5) < 0.05, f"格子比例应约 2:3: {cw}x{ch}"
    first = grid.visualItemRect(grid.item(0))
    assert first == QRect(grid._x_offset, 0, cw, ch), first
    all_rects = list(rects(grid).values())
    assert len(set(all_rects)) == len(all_rects), "图标矩形不应重叠"
    print(f"[OK] 初始紧凑摆放 {cw}×{ch}（约 2:3），无重叠")

    # 2. 新应用自动追加到末尾空位，不与旧图标重叠（旧坐标遗留问题回归）
    grid.populate(apps(8), grid.order())
    assert names(grid) == [f"App{i:02d}" for i in range(8)], names(grid)
    assert visible_names(grid) == [f"App{i:02d}" for i in range(8)]
    all_rects = list(rects(grid).values())
    assert len(set(all_rects)) == len(all_rects), "新图标不应压在旧图标下"
    assert (
        grid.visualItemRect(grid.item(6)).topLeft()
        == QPoint(grid._x_offset, ch)
    ), "第 7 个图标应换行到第 2 行行首"
    print("[OK] 新增应用自动排列到末尾空位")

    # 3. 格子内中间区落点 → 互换
    grid = make_grid(8)
    grid.layout_changed.connect(lambda: changes.append(1))
    drag(grid, 0, cell_center(grid, 3, 0))
    assert names(grid)[:5] == ["App03", "App01", "App02", "App00", "App04"], names(grid)
    assert changes, "落位后应发出 layout_changed"
    print("[OK] 格子内中间区落点互换")

    # 4. 目标格子左边缘落点且原位在右侧 → 整体右移一格
    grid = make_grid(8)
    drag(grid, 6, cell_left(grid, 0, 0))
    assert names(grid) == ["App06"] + [f"App{i:02d}" for i in range(6)] + ["App07"], names(grid)
    print("[OK] 左边缘落点整体右移让位")

    # 5. 左边缘落点但原位在落点左侧 → 插到目标之前，区间图标向原位方向（左）补位
    grid = make_grid(8)
    drag(grid, 0, cell_left(grid, 0, 1))
    assert names(grid) == ["App01", "App02", "App03", "App04", "App05", "App00", "App06", "App07"], names(grid)
    print("[OK] 左边缘插入：区间图标向原位方向补位")

    # 6. 目标格子右边缘落点且原位在左侧 → 整体左移一格
    grid = make_grid(8)
    drag(grid, 0, cell_right(grid, 5, 0))
    assert names(grid) == ["App01", "App02", "App03", "App04", "App05", "App00", "App06", "App07"], names(grid)
    print("[OK] 右边缘落点整体左移让位")

    # 7. 右边缘落点但原位在落点右侧 → 插到目标之后，区间图标向原位方向（右）补位
    grid = make_grid(8)
    drag(grid, 7, cell_right(grid, 5, 0))
    assert names(grid) == ["App00", "App01", "App02", "App03", "App04", "App05", "App07", "App06"], names(grid)
    print("[OK] 右边缘插入：区间图标向原位方向补位")

    # 8. 页尾空白落点 → 移到本页最后一个可见项之后
    grid = make_grid(5)
    drag(grid, 0, cell_center(grid, 5, 2))
    assert names(grid) == ["App01", "App02", "App03", "App04", "App00"], names(grid)
    print("[OK] 页尾空白落位到末尾")

    # 9. 落点阴影吸附格子；Esc 取消
    grid = make_grid(20)
    mouse_press(grid, item_center(grid, 0))
    mouse_move(grid, cell_center(grid, 2, 1))
    assert grid._target_cell == (2, 1), grid._target_cell
    assert grid._ghost_rect() == QRect(
        grid._x_offset + 2 * grid._cell.width(), 1 * grid._cell.height(),
        grid._cell.width(), grid._cell.height(),
    ), "阴影应吸附在落点格子"
    ghost = grid.viewport().grab()
    assert not ghost.isNull()
    ghost.save("drag_ghost.png")
    key_press(grid, Qt.Key_Escape)
    assert not grid._drag_active
    mouse_release(grid, cell_center(grid, 2, 1))
    assert names(grid)[0] == "App00", "Esc 取消后布局不变"
    print("[OK] 落点阴影与 Esc 取消")

    # 10. 翻页：A/D、←/→；滚轮翻页；Ctrl+滚轮缩放
    grid = make_grid(20)
    assert grid.page_count() == 2, grid.page_count()
    key_press(grid, Qt.Key_D)
    assert grid.current_page() == 1
    assert visible_names(grid) == ["App18", "App19"], visible_names(grid)
    assert (
        grid.visualItemRect(grid.item(18)).topLeft() == QPoint(grid._x_offset, 0)
    ), "翻页后首项应从页首格子开始"
    key_press(grid, Qt.Key_A)
    assert grid.current_page() == 0
    key_press(grid, Qt.Key_Right)
    assert grid.current_page() == 1
    key_press(grid, Qt.Key_Left)
    assert grid.current_page() == 0
    wheel(grid, -120)
    assert grid.current_page() == 1, "滚轮向下应翻到下一页"
    wheel(grid, 120)
    assert grid.current_page() == 0
    scale_before = grid.scale()
    wheel(grid, 120, ctrl=True)
    assert grid.scale() > scale_before, "Ctrl+滚轮向上应放大"
    assert grid.current_page() == 0, "缩放不应翻页"
    # 缩放后每页容量变小 → 页数变化
    grid.set_scale(2.2)
    assert (grid._cell.width(), grid._cell.height()) == (200, 300), (
        grid._cell.width(), grid._cell.height()
    )
    assert grid.page_count() > 2, "放大后应产生更多页"
    print("[OK] A/D、←/→、滚轮翻页与 Ctrl+滚轮缩放")

    # 11. 缩放边界：最小 40×60（宽2高3），比例恒定
    grid.set_scale(0.05)
    assert abs(grid.scale() - 0.4) < 1e-6, "缩放下限 0.4"
    assert (grid._cell.width(), grid._cell.height()) == (MIN_CELL_W, 60), (
        grid._cell.width(), grid._cell.height()
    )
    assert grid._cell.height() * 2 == grid._cell.width() * 3, "最小格子应为宽2高3"
    print("[OK] 最小缩放 40×60（宽2高3）")

    # 12. 过滤与分页联动
    grid = make_grid(20)
    grid.filter("app1")
    assert grid.page_count() == 1, grid.page_count()
    assert visible_names(grid) == [f"App1{i}" for i in range(10)], visible_names(grid)
    grid.filter("")
    assert grid.page_count() == 2 and grid.current_page() == 0
    print("[OK] 搜索过滤后按可见项重新分页")

    # 13. 单击链路仍触发启动（假路径发 launch_failed 即证明链路通了）
    grid = make_grid(6)
    grid.itemClicked.connect(lambda item: clicked.append(item.text()))
    grid.launch_failed.connect(lambda msg: failed.append(msg))
    mouse_press(grid, item_center(grid, 0))
    mouse_release(grid, item_center(grid, 0))
    assert clicked == ["App00"], clicked
    assert failed, "单击启动链路未触发"
    print("[OK] 普通单击仍触发启动链路")

    # 14. 翻页栏：单页隐藏、多页显示，箭头/页位点命中正确
    bar = PageBar()
    bar.resize(26, 300)
    bar.show()
    app.processEvents()
    requests = []
    bar.page_requested.connect(requests.append)
    bar.set_pages(0, 1)
    assert not bar.isVisible(), "单页时翻页栏应隐藏"
    bar.set_pages(0, 2)
    assert bar.isVisible(), "多页时翻页栏应显示"
    click(bar, QPoint(13, 10))            # 上箭头
    assert requests[-1] == -1, requests
    click(bar, QPoint(13, 289))           # 下箭头
    assert requests[-1] == 1, requests
    # 页位点：slot 封顶 36px 后居中，2 页时 dots 区在 114..186
    click(bar, QPoint(13, 168))           # 第 2 个页位点
    assert requests[-1] == 1, requests
    click(bar, QPoint(13, 132))           # 第 1 个页位点
    assert requests[-1] == 0, requests
    bar.set_pages(5, 6)
    assert bar.isVisible()
    print("[OK] 翻页栏显示/隐藏与命中跳转")

    # 15. 翻页栏与网格联动：点击页位点跳转
    grid = make_grid(20)
    bar = PageBar()
    bar.resize(26, 300)
    grid.page_changed.connect(bar.set_pages)
    bar.page_requested.connect(grid.goto_page)
    bar.set_pages(grid.current_page(), grid.page_count())
    click(bar, QPoint(13, 168))           # 第 2 个页位点
    assert grid.current_page() == 1
    assert visible_names(grid) == ["App18", "App19"]
    print("[OK] 翻页栏跳转联动")

    # 16. 显示顺序与条目行序不一致（拖拽排序/旧配置迁移后）时，缩放与翻页不串位不重叠
    grid = make_grid(20)
    grid.populate(apps(20), [f"C:/apps/app{i}.exe" for i in range(19, -1, -1)])
    QApplication.processEvents()
    # 第一页应是显示顺序的前 18 个（App19..App02）；visible_names 按行序遍历，按集合比较
    assert sorted(visible_names(grid)) == sorted(f"App{i:02d}" for i in range(19, 1, -1)), visible_names(grid)
    assert len(set(rects(grid).values())) == len(rects(grid)), "可见图标不应重叠"
    grid.set_scale(1.3)
    QApplication.processEvents()
    assert len(set(rects(grid).values())) == len(rects(grid)), "缩放后可见图标不应重叠"
    key_press(grid, Qt.Key_D)
    QApplication.processEvents()
    assert sorted(visible_names(grid)) == sorted(f"App{i:02d}" for i in range(11, 3, -1)), visible_names(grid)
    grid.set_scale(0.7)
    QApplication.processEvents()
    assert len(set(rects(grid).values())) == len(rects(grid)), "缩放后可见图标不应重叠"
    assert sorted(visible_names(grid)) == sorted(f"App{i:02d}" for i in range(20)), "缩放合并页后应显示全部"
    print("[OK] 显示顺序与行序不一致时，缩放/翻页不串位不重叠")

    # 17. 悬停预览动画：目标格子左边缘悬停时底下的图标向右偏移一格，中间区不偏移
    grid = make_grid(8)
    mouse_press(grid, item_center(grid, 7))
    mouse_move(grid, cell_left(grid, 0, 0))
    wait_anim()
    assert grid._ghost_cell == (0, 0), grid._ghost_cell
    assert grid.visualItemRect(grid.item(0)).topLeft() == QPoint(
        grid._x_offset + grid._cell.width(), 0
    ), "悬停左边缘时底下的图标应向右偏移一格"
    assert grid.visualItemRect(grid.item(6)).topLeft() == QPoint(
        grid._x_offset + grid._cell.width(), grid._cell.height()
    ), "区间内其他图标也应顺移补位"
    # 悬停中间区 → 图标回到原位（不偏移）
    mouse_move(grid, cell_center(grid, 3, 0))
    wait_anim()
    assert grid._ghost_cell == (3, 0), grid._ghost_cell
    assert grid.visualItemRect(grid.item(0)).topLeft() == QPoint(grid._x_offset, 0), "中间区不应偏移"
    mouse_release(grid, cell_center(grid, 3, 0))
    # 中间区释放 = 拖动项(App07)与落点图标(App03)互换
    assert names(grid) == ["App00", "App01", "App02", "App07", "App04", "App05", "App06", "App03"], names(grid)

    # 落位与悬停预览一致
    grid = make_grid(8)
    mouse_press(grid, item_center(grid, 7))
    mouse_move(grid, cell_left(grid, 0, 0))
    wait_anim()
    preview_rects = rects(grid)
    assert grid._drag_item.isHidden(), "拖动中自身应隐藏（由落点阴影代表）"
    mouse_release(grid, cell_left(grid, 0, 0))
    assert names(grid) == ["App07", "App00", "App01", "App02", "App03", "App04", "App05", "App06"], names(grid)
    assert not grid.item(7).isHidden(), "落位后拖动项应恢复显示"
    assert grid.visualItemRect(grid.item(0)).topLeft() == preview_rects["App00"].topLeft(), "落位应与悬停预览一致"
    print("[OK] 悬停预览偏移（左列区右移、中心区不动）且落位与预览一致")

    # 18. 起拖瞬间不挪动其他图标：满页时拖动项一隐藏，Qt 会排队一次自身
    #     重排把尾部图标顶出页面（曾表现为“刚拖动起来整个界面图标混乱”）
    grid = make_grid(18)  # 满页
    before = rects(grid)
    mouse_press(grid, item_center(grid, 5))
    mouse_move(grid, cell_center(grid, 5, 0) + QPoint(20, 20))
    assert grid._drag_active, "拖拽应已激活"
    wait_anim()  # 等 Qt 的延迟重排与坐标重申任务都跑完
    after = rects(grid)
    assert set(after) == set(before) - {"App05"}, "应只有拖动项隐藏"
    for name, pos in after.items():
        assert before[name].topLeft() == pos.topLeft(), f"{name} 起拖时被挪动"
    key_press(grid, Qt.Key_Escape)
    mouse_release(grid, cell_center(grid, 5, 0))
    assert names(grid) == [f"App{i:02d}" for i in range(18)], names(grid)
    assert not any(grid.isRowHidden(i) for i in range(grid.count())), "Esc 后应全部恢复显示"
    print("[OK] 起拖瞬间其余图标纹丝不动（满页）")

    # 19. 分区按目标格子内部计算：屏幕中间的图标左右边缘也能插入（回归：
    #     旧实现分区是屏幕两侧竖条，中间图标只能互换、要"间隔几个"才触发移位）
    grid = make_grid(8)
    drag(grid, 0, cell_left(grid, 3, 0))    # App03 在屏幕中部，其左边缘 → 插到它前面
    assert names(grid) == ["App01", "App02", "App00", "App03", "App04", "App05", "App06", "App07"], names(grid)
    grid = make_grid(8)
    drag(grid, 0, cell_right(grid, 3, 0))   # 右边缘 → 插到 App03 之后
    assert names(grid) == ["App01", "App02", "App03", "App00", "App04", "App05", "App06", "App07"], names(grid)

    # 同一格子内横向移动光标：左边缘=插入预览（App02 右移一格），中间=互换预览（回原位）
    grid = make_grid(8)
    mouse_press(grid, item_center(grid, 7))
    mouse_move(grid, cell_left(grid, 2, 0))
    wait_anim()
    assert grid.visualItemRect(grid.item(2)).topLeft() == QPoint(
        grid._x_offset + 3 * grid._cell.width(), 0
    ), "悬停 App02 左边缘应插入到它前面"
    mouse_move(grid, cell_center(grid, 2, 0))
    wait_anim()
    assert grid.visualItemRect(grid.item(2)).topLeft() == QPoint(
        grid._x_offset + 2 * grid._cell.width(), 0
    ), "同一格子内移到中间应切换为互换预览（图标回原位）"
    mouse_release(grid, cell_center(grid, 2, 0))
    assert names(grid) == ["App00", "App01", "App07", "App03", "App04", "App05", "App06", "App02"], names(grid)
    print("[OK] 格子内分区：中间图标边缘可插入，格子内横移切换插入/互换")

    # 20. 拖影像：QDrag 携带不透明的图标+名称像素图（尺寸=格子），热区在图内
    grid = make_grid(8)
    captured = {}

    def capture_exec(self, drag):
        captured["pixmap"] = drag.pixmap()
        captured["hotspot"] = drag.hotSpot()
        captured["cursor"] = drag.dragCursor(Qt.MoveAction)

    (IconGrid)._exec_drag = capture_exec
    mouse_press(grid, item_center(grid, 1))
    mouse_move(grid, cell_center(grid, 3, 0) + QPoint(20, 0))
    IconGrid._exec_drag = lambda self, drag: None  # 恢复默认空转
    mouse_release(grid, cell_center(grid, 3, 0))
    pix = captured["pixmap"]
    cw, ch = grid._cell.width(), grid._cell.height()
    assert not pix.isNull(), "QDrag 应携带拖影像素图"
    assert (pix.width(), pix.height()) == (cw, ch), (
        pix.width(), pix.height(), cw, ch
    )
    hs = captured["hotspot"]
    assert 0 <= hs.x() <= cw and 0 <= hs.y() <= ch, "热区应在像素图内（跟手）"
    assert not captured["cursor"].isNull(), "拖拽光标应设为自定义（透明，隐藏箭头）"
    print("[OK] 拖影像素图随 QDrag 跟光标（不透明、热区跟手、无箭头光标）")

    # 21. 图标归一化：外壳把小图标贴进大画布时（rustdesk/Magpie 等显示成
    #     小图的根因），裁出实际内容放大铺满；本就满幅的图标保持原样
    grid = make_grid(6)

    def make_icon(side_len):
        canvas = QPixmap(256, 256)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setBrush(QColor("#3a7bd5"))
        painter.setPen(Qt.NoPen)
        painter.drawRect(0, 0, side_len, side_len)
        painter.end()
        return QIcon(canvas)

    norm = grid._normalized_icon(make_icon(60))
    box = IconGrid._opaque_bbox(norm.pixmap(
        QSize(ICON_RENDER_SIZE, ICON_RENDER_SIZE)).toImage())
    assert box is not None and box[2] >= ICON_RENDER_SIZE * 0.9, f"小图内容应放大铺满: {box}"
    keep = grid._normalized_icon(make_icon(256))
    box2 = IconGrid._opaque_bbox(keep.pixmap(
        QSize(ICON_RENDER_SIZE, ICON_RENDER_SIZE)).toImage())
    assert box2[2] >= 250 and box2[3] >= 250, f"满幅图标不应被改动: {box2}"
    print("[OK] 图标归一化：小图贴大画布被裁出放大，满幅图标保持原样")

    print("\n全部分页网格测试通过")


if __name__ == "__main__":
    main()
