"""冒烟测试：离屏模式下验证扫描、配置、快捷方式创建与网格逻辑。"""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import app.config as config_module  # noqa: E402
from app import lnk_utils, scanner  # noqa: E402
from app.config import Config  # noqa: E402
from app.icon_grid import IconGrid  # noqa: E402


def main():
    app = QApplication(sys.argv)

    # 1. 快捷方式文件夹自动创建
    folder = scanner.shortcut_folder()
    assert folder.exists() and folder.name == "快捷方式", folder
    assert folder.parent == scanner.base_dir()
    print(f"[OK] 快捷方式文件夹就绪: {folder}")

    # 2. 扫描临时文件夹（模拟用户放入的 .lnk/.exe）
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "演示应用.exe").write_bytes(b"")
        (tmp_path / "说明.txt").write_text("不应被扫描", encoding="utf-8")
        sub = tmp_path / "子文件夹"
        sub.mkdir()
        (sub / "嵌套工具.exe").write_bytes(b"")
        # create_shortcut 生成真实 lnk；同目标重复创建应复用而不产生副本
        lnk_utils.create_shortcut(
            tmp_path, "记事本", r"C:\Windows\System32\notepad.exe"
        )
        lnk_utils.create_shortcut(
            tmp_path, "记事本", r"C:\Windows\System32\notepad.exe"
        )
        assert len(list(tmp_path.glob("*.lnk"))) == 1, "同目标快捷方式未复用"
        apps = scanner.scan_folder(tmp_path)
        names = {a["name"] for a in apps}
        assert names == {"演示应用", "记事本", "嵌套工具"}, names
        assert all(a["path"].endswith((".lnk", ".exe")) for a in apps)
        print(f"[OK] 扫描到 {len(apps)} 个启动项: {sorted(names)}")

        # 3. 网格填充 + 图标 + 过滤 + 顺序
        grid = IconGrid()
        grid.populate(apps)
        assert grid.count() == len(apps), "网格数量与扫描结果不一致"
        items_with_icon = sum(
            1 for i in range(grid.count()) if not grid.item(i).icon().isNull()
        )
        print(f"[OK] 网格填充 {grid.count()} 项，其中 {items_with_icon} 项取到图标")

        first = apps[0]["name"]
        grid.filter(first[:2].lower())
        visible = sum(0 if grid.isRowHidden(i) else 1 for i in range(grid.count()))
        assert 0 < visible <= len(apps), "过滤结果异常"
        grid.filter("")
        assert all(not grid.isRowHidden(i) for i in range(grid.count()))
        print(f"[OK] 搜索过滤正常（'{first[:2]}' 匹配 {visible} 项）")

        order = [a["path"] for a in grid.apps()]
        assert len(order) == len(apps)
        print("[OK] 视觉顺序导出正常")

    # 4. 文件夹不存在时返回空列表
    assert scanner.scan_folder(Path(tempfile.gettempdir()) / "不存在目录xyz") == []
    print("[OK] 目录缺失时扫描返回空列表")

    # 5. 配置：路径重定向到临时目录，避免改动真实配置
    with tempfile.TemporaryDirectory() as ctmp:
        ctmp_path = Path(ctmp)
        config_module.CONFIG_PATH = ctmp_path / "config.json"
        legacy = ctmp_path / "legacy.json"
        legacy.write_text(
            json.dumps(
                {
                    "manual_apps": [
                        {"name": "旧应用", "path": "C:/不存在/旧应用.exe"}
                    ],
                    "hidden": ["旧隐藏项"],
                    "order": ["C:/旧路径.exe"],
                }
            ),
            encoding="utf-8",
        )
        config_module.LEGACY_CONFIG_PATH = legacy

        config = config_module.Config()
        assert len(config.legacy_manual_apps) == 1, "旧版手动应用未读出"
        assert config.legacy_manual_apps[0]["name"] == "旧应用"
        config.hide("有效项")
        config.set_order(["C:/旧路径.exe", "C:/有效项.lnk"])
        # 启动清理：文件夹里已不存在的条目应被删除
        assert config.prune_stale({"有效项"}, {"C:/有效项.lnk"}) is True
        assert config.data["hidden"] == ["有效项"]
        assert config.data["order"] == ["C:/有效项.lnk"]
        config.save()
        assert config_module.CONFIG_PATH.exists(), "配置未写入 exe 同级目录"
        print("[OK] 配置读写、旧配置迁移与失效清理正常")

    print("\n全部冒烟测试通过")


if __name__ == "__main__":
    main()
