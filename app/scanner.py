"""扫描 exe 同级「快捷方式」文件夹中的 .lnk / .exe 启动项。"""
import os
import subprocess
import sys
from pathlib import Path

# 可启动的条目类型（扫描与文件拖放共用）
ENTRY_SUFFIXES = (".lnk", ".exe")


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
        if not path.is_file() or path.suffix.lower() not in ENTRY_SUFFIXES:
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


def file_paths_from_mime(mime):
    """从拖放的 MIME 数据里取出可添加的 exe/lnk 本地路径（去重、保持顺序）。"""
    if mime is None or not mime.hasUrls():
        return []
    paths, seen = [], set()
    for url in mime.urls():
        if not url.isLocalFile():
            continue
        path = url.toLocalFile()
        if not path or not path.lower().endswith(ENTRY_SUFFIXES):
            continue
        key = os.path.normcase(os.path.normpath(path))
        if key in seen:
            continue
        seen.add(key)
        paths.append(os.path.normpath(path))
    return paths


# ---- 系统命令与资源管理器 ----
def explorer_path():
    """系统文件资源管理器可执行文件路径（不存在时返回空串）。"""
    root = os.environ.get("SystemRoot") or os.environ.get("WINDIR") or r"C:\Windows"
    candidate = os.path.join(root, "explorer.exe")
    return candidate if os.path.isfile(candidate) else ""


def open_in_explorer(folder):
    """在资源管理器里打开一个文件夹；失败返回 False。

    用 explorer.exe 而不是 os.startfile：后者走系统的默认程序关联，
    在部分环境里文件夹可能被别的应用接管。explorer.exe 用绝对路径调用，
    不依赖 PATH 里有没有它。
    """
    folder = str(folder)
    if not os.path.isdir(folder):
        return False
    exe = explorer_path() or "explorer.exe"
    try:
        subprocess.Popen(
            [exe, folder],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False
    return True


def open_folder_of(target):
    """打开文件所在的文件夹；返回是否成功打开。

    不用 explorer.exe 的 /select, 语法：那个写法在路径带空格时会被
    Explorer 解析失败，它找不到路径就退回自己的默认目录（"文档"），
    结果是无论点哪个图标都打开"文档"。这里老老实实打开所在文件夹。
    """
    target = str(target or "")
    if not target:
        return False
    return open_in_explorer(os.path.dirname(target))
