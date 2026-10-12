"""解析与创建 .lnk 快捷方式（pywin32）。"""
import os
from pathlib import Path

_shell = None


def _get_shell():
    global _shell
    if _shell is None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        _shell = win32com.client.Dispatch("WScript.Shell")
    return _shell


def resolve_lnk(lnk_path):
    """返回 (target, arguments, workdir)；解析失败时各字段为空串。"""
    if not str(lnk_path).lower().endswith(".lnk") or not os.path.exists(lnk_path):
        return "", "", ""
    try:
        shortcut = _get_shell().CreateShortCut(str(lnk_path))
        return (
            shortcut.Targetpath or "",
            shortcut.Arguments or "",
            shortcut.WorkingDirectory or "",
        )
    except Exception:
        return "", "", ""


def get_icon_location(lnk_path):
    """返回 lnk 的自定义图标位置（形如 "path,index"），无则空串。"""
    if not str(lnk_path).lower().endswith(".lnk") or not os.path.exists(lnk_path):
        return ""
    try:
        return str(_get_shell().CreateShortCut(str(lnk_path)).IconLocation or "")
    except Exception:
        return ""


def unique_lnk_path(folder, name):
    """在 folder 中为 name 取一个不重复的 .lnk 路径（"name (2).lnk" 依次递增）。"""
    base = (name or "应用").strip()
    stem, ext = os.path.splitext(base)
    ext = ext or ".lnk"
    candidate = Path(folder) / f"{stem}{ext}"
    index = 2
    while candidate.exists():
        candidate = Path(folder) / f"{stem} ({index}){ext}"
        index += 1
    return candidate


def create_shortcut(folder, name, target, args="", workdir="", icon_location=""):
    """在 folder 中创建名为 name 的快捷方式，返回创建或复用的路径。

    同名快捷方式若指向同一目标则直接复用，避免重复添加产生副本。
    """
    folder = Path(folder)
    base = (name or "").strip() or Path(str(target)).stem or "应用"
    lnk_path = folder / f"{os.path.splitext(base)[0]}.lnk"
    if lnk_path.exists():
        existing_target, _, _ = resolve_lnk(lnk_path)
        if existing_target and os.path.normcase(existing_target) == os.path.normcase(
            str(target)
        ):
            return lnk_path
        lnk_path = unique_lnk_path(folder, base)
    shortcut = _get_shell().CreateShortCut(str(lnk_path))
    shortcut.Targetpath = str(target)
    if args:
        shortcut.Arguments = args
    if workdir:
        shortcut.WorkingDirectory = workdir
    if icon_location:
        shortcut.IconLocation = icon_location
    shortcut.save()
    return lnk_path


def icon_source(lnk_path):
    """返回 (图标文件, 图标索引)；失败返回 ("", 0)。

    .lnk 自身经外壳提取会带蓝色箭头覆盖，这里改为从 lnk 的自定义图标位置
    （IconLocation，形如 "path,index"）或目标文件提取；索引一并返回，让
    "app.exe,3" 这类指定第 N 个图标的快捷方式真正生效（外壳路径只会给出
    文件的第一个图标）。两者都无效时返回 ("", 0)，由调用方回退为 lnk 自身
    图标。
    """
    if not str(lnk_path).lower().endswith(".lnk") or not os.path.exists(lnk_path):
        return "", 0
    try:
        shortcut = _get_shell().CreateShortCut(str(lnk_path))
        icon_location = shortcut.IconLocation or ""
        target = shortcut.Targetpath or ""
    except Exception:
        return "", 0
    for candidate in (icon_location, target):
        file_path, _, raw_index = str(candidate).partition(",")
        file_path = file_path.strip()
        if not file_path or not os.path.exists(file_path):
            continue
        try:
            return file_path, int(raw_index)
        except ValueError:
            return file_path, 0
    return "", 0
