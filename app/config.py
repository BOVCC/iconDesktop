"""JSON 配置读写：存放在 exe/源码同级目录下的 config.json。

旧版本把配置放在 %APPDATA%\\iconDesktop\\config.json，首次启动时自动改读
旧文件完成迁移；旧文件中的 manual_apps（手动添加应用）由主窗口迁移成
「快捷方式」文件夹里的 .lnk 后即被丢弃，配置文件本身不再保存应用列表。
"""
import copy
import json
import os
from pathlib import Path

from app.scanner import base_dir

CONFIG_PATH = base_dir() / "config.json"
LEGACY_CONFIG_PATH = (
    Path(os.environ.get("APPDATA", str(Path.home()))) / "iconDesktop" / "config.json"
)

DEFAULTS = {
    "hidden": [],   # 被隐藏的快捷方式文件夹条目名称
    "order": [],    # 图标路径顺序
    "settings": {
        "launch_on": "click",             # click | double
        "minimize_after_launch": True,
        "theme": "light",                 # light | dark
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
        if isinstance(stored.get("window"), dict):
            self.data["window"] = stored["window"]
        if isinstance(stored.get("settings"), dict):
            self.data["settings"] = {**DEFAULTS["settings"], **stored["settings"]}

    def save(self):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    # ---- 隐藏与排序 ----
    @property
    def hidden(self):
        return set(self.data["hidden"])

    def hide(self, name):
        if name not in self.data["hidden"]:
            self.data["hidden"].append(name)

    def prune_stale(self, names, paths):
        """删除已不在快捷方式文件夹中的隐藏/排序信息，返回是否有变更。"""
        old_hidden, old_order = list(self.data["hidden"]), list(self.data["order"])
        self.data["hidden"] = [n for n in old_hidden if n in names]
        self.data["order"] = [p for p in old_order if p in paths]
        return self.data["hidden"] != old_hidden or self.data["order"] != old_order

    @property
    def order(self):
        return list(self.data["order"])

    def set_order(self, paths):
        self.data["order"] = list(paths)

    # ---- 其他设置 ----
    @property
    def settings(self):
        return self.data["settings"]
