"""扫描 exe 同级「快捷方式」文件夹中的 .lnk / .exe 启动项。"""
import os
import sys
from pathlib import Path


def base_dir():
    """程序所在目录：打包后为 exe 所在目录，源码运行为项目根目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir():
    """用户数据目录（config.json 与「快捷方式」文件夹所在处）。

    便携版由打包脚本向 exe 注入环境变量 ICONDESKTOP_CONFIG_LOCATION=appdata
    （见 build.py），数据放 C 盘 %APPDATA%\\iconDesktop 用户目录，exe 放哪里
    （包括只读目录）都能跑；不带该变量时数据跟随 exe/脚本所在目录。
    """
    if os.environ.get("ICONDESKTOP_CONFIG_LOCATION") == "appdata":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "iconDesktop"
    return base_dir()


def shortcut_folder():
    """用户数据目录下的快捷方式文件夹，不存在时自动创建。"""
    folder = data_dir() / "快捷方式"
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return folder


def scan_folder(directory=None):
    """返回启动项列表 [{name, path, args, workdir}]。

    递归扫描文件夹中的 .lnk 与 .exe，按名称去重；文件夹内容由用户自己
    维护，因此不做卸载器过滤。
    """
    folder = Path(directory) if directory else shortcut_folder()
    if not folder.is_dir():
        return []
    entries = {}
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".lnk", ".exe"):
            continue
        name = path.stem.strip()
        if not name:
            continue
        entries.setdefault(
            name.lower(),
            {
                "name": name,
                "path": str(path),
                "args": "",
                "workdir": "",
            },
        )
    return sorted(entries.values(), key=lambda e: e["name"].lower())
