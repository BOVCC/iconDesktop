"""JSON 配置读写，存放在用户数据目录下（便携版由打包脚本注入环境变量后
放 C 盘 %APPDATA%\\iconDesktop 用户目录；数据跟随 exe 的版本存 exe/脚本
同级目录，见 app/scanner.py 的 data_dir()）。

旧版本把配置放在 %APPDATA%\\iconDesktop\\config.json，首次启动时自动改读
旧文件完成迁移；旧文件中的 manual_apps（手动添加应用）由主窗口迁移成
「快捷方式」文件夹里的 .lnk 后即被丢弃，配置文件本身不再保存应用列表。
"""
import copy
import json
import os
from pathlib import Path

from app.scanner import data_dir

DATA_DIR = data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
LEGACY_CONFIG_PATH = (
    Path(os.environ.get("APPDATA", str(Path.home()))) / "iconDesktop" / "config.json"
)

DEFAULTS = {
    "hidden": [],     # 被隐藏的快捷方式文件夹条目名称
    "order": [],      # 图标显示顺序（分页布局按此顺序紧凑排布）
    "positions": {},  # 旧版坐标遗留键：加载时迁移进 order，此后不再写入
    "settings": {
        "launch_on": "double",            # click | double
        "minimize_after_launch": True,
        "theme": "dark",                  # light | dark
        "icon_scale": 1.0,                # 图标缩放级别，格子宽高比固定 2:3
    },
}


class Config:
    def __init__(self):
        self.data = copy.deepcopy(DEFAULTS)
        self.legacy_manual_apps = []  # 旧版配置里的手动应用，供启动迁移用
        self.load()

    @staticmethod
    def _read(path):
        try:
            with open(path, encoding="utf-8") as f:
                stored = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        return stored if isinstance(stored, dict) else None

    def load(self):
        stored = self._read(CONFIG_PATH)
        if stored is None:
            stored = self._read(LEGACY_CONFIG_PATH)
            if stored is not None:
                manual = stored.get("manual_apps")
                if isinstance(manual, list):
                    self.legacy_manual_apps = [a for a in manual if isinstance(a, dict)]
        if stored is None:
            return
        for key in ("hidden", "order"):
            if isinstance(stored.get(key), list):
                self.data[key] = stored[key]
        if isinstance(stored.get("positions"), dict):
            self.data["positions"] = stored["positions"]
        if isinstance(stored.get("window"), dict):
            self.data["window"] = stored["window"]
        if isinstance(stored.get("settings"), dict):
            self.data["settings"] = {**DEFAULTS["settings"], **stored["settings"]}
        if self._migrate_positions():
            # 旧坐标布局一次性迁移为顺序，立即落盘避免下次重复迁移
            try:
                self.save()
            except OSError:
                pass

    def _migrate_positions(self):
        """旧版 positions（{路径: [列, 行]}）按行列次序合并进 order。

        分页布局只按顺序紧凑排布，不再保存格子坐标；返回是否发生迁移。
        """
        positions = self.data.get("positions")
        if not isinstance(positions, dict) or not positions:
            return False

        def cell_key(item):
            cell = item[1]
            try:
                return (int(cell[1]), int(cell[0]))  # 行优先
            except (TypeError, ValueError, IndexError, KeyError):
                return (1 << 30, 1 << 30)

        merged = []
        for path, _cell in sorted(positions.items(), key=cell_key):
            if path not in merged:
                merged.append(path)
        for path in self.data["order"]:
            if path not in merged:
                merged.append(path)
        self.data["order"] = merged
        self.data["positions"] = {}
        return True

    def save(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ---- 排序与坐标 ----
    # hidden 键：旧版「隐藏图标」功能遗留，现在右键是直接删除文件，键仅
    # 为兼容旧配置而保留（读写照常、不再参与过滤），失效条目由 prune_stale 清理
    def prune_stale(self, names, paths):
        """删除已不在快捷方式文件夹中的隐藏/排序/坐标信息，返回是否有变更。"""
        old_hidden, old_order = list(self.data["hidden"]), list(self.data["order"])
        old_positions = dict(self.data["positions"])
        self.data["hidden"] = [n for n in old_hidden if n in names]
        self.data["order"] = [p for p in old_order if p in paths]
        self.data["positions"] = {
            p: c for p, c in old_positions.items() if p in paths
        }
        return (
            self.data["hidden"] != old_hidden
            or self.data["order"] != old_order
            or self.data["positions"] != old_positions
        )

    @property
    def order(self):
        return list(self.data["order"])

    def set_order(self, paths):
        self.data["order"] = list(paths)

    # ---- 其他设置 ----
    @property
    def settings(self):
        return self.data["settings"]
