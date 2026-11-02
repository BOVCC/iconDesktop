"""解析与创建 .lnk 快捷方式（pywin32）。"""
import os
from pathlib import Path

_shell = None

# lnk 解析结果缓存：{(路径, mtime, size): (target, args, workdir, icon)}
# 解析一个 lnk 要走 COM，约 2.4ms；判重时要扫整个文件夹，逐个添加时
# 会反复解析同一批文件，因此按文件时间戳缓存（文件改了自动失效）。
_lnk_cache = {}
_CACHE_LIMIT = 512


def _cache_get(key):
    return _lnk_cache.get(key)


def _cache_put(key, value):
    """写入缓存；条目过多时整体清空（快捷方式文件夹很小，够用）。"""
    if len(_lnk_cache) >= _CACHE_LIMIT:
        _lnk_cache.clear()
    _lnk_cache[key] = value


def _get_shell():
    global _shell
    if _shell is None:
        import pythoncom
        import win32com.client

        pythoncom.CoInitialize()
        _shell = win32com.client.Dispatch("WScript.Shell")
    return _shell


def _lnk_stamp(path):
    """lnk 的 (mtime_ns, size)；取不到返回 None。"""
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def resolve_lnk(lnk_path):
    """返回 (target, arguments, workdir)；解析失败时各字段为空串。"""
    if not str(lnk_path).lower().endswith(".lnk") or not os.path.exists(lnk_path):
        return "", "", ""
    key = (os.path.normcase(os.path.abspath(str(lnk_path))), _lnk_stamp(lnk_path))
    cached = _cache_get(key)
    if cached is not None:
        return cached[0], cached[1], cached[2]
    try:
        shortcut = _get_shell().CreateShortCut(str(lnk_path))
        result = (
            shortcut.Targetpath or "",
            shortcut.Arguments or "",
            shortcut.WorkingDirectory or "",
        )
    except Exception:
        return "", "", ""
    _cache_put(key, result + ("",))
    return result


def get_icon_location(lnk_path):
    """返回 lnk 的自定义图标位置（形如 "path,index"），无则空串。"""
    if not str(lnk_path).lower().endswith(".lnk") or not os.path.exists(lnk_path):
        return ""
    key = (os.path.normcase(os.path.abspath(str(lnk_path))), _lnk_stamp(lnk_path))
    cached = _cache_get(key)
    if cached is not None and cached[3]:
        return cached[3]
    try:
        icon = str(_get_shell().CreateShortCut(str(lnk_path)).IconLocation or "")
    except Exception:
        return ""
    if cached is not None:
        _cache_put(key, cached[:3] + (icon,))
    return icon


def normalize_path(path):
    """路径归一化：绝对化 + 解析 8.3 短名/符号链接 + 忽略大小写。

    同一个文件可能有多种写法（"C:\\PROGRA~1\\App\\a.exe" 与
    "C:\\Program Files\\App\\a.exe"、"C:\\a.exe" 与 "c:\\A.EXE"），比较
    是否同一个目标时必须先归一化，否则会当成两个不同的程序。
    """
    text = str(path or "")
    if not text:
        return ""
    try:
        text = os.path.realpath(os.path.abspath(text))
    except (OSError, ValueError):
        text = os.path.abspath(text)
    return os.path.normcase(os.path.normpath(text))


def same_target(a, b):
    """两个路径是否指向同一个文件。"""
    left, right = normalize_path(a), normalize_path(b)
    return bool(left) and left == right


def _icon_path_key(path):
    """图标文件路径归一化（忽略大小写；绝对路径顺带解析 8.3 短名）。"""
    text = str(path or "").strip()
    if not text:
        return ""
    if os.path.isabs(text):
        return normalize_path(text)
    return os.path.normcase(os.path.normpath(text))


def _icon_key(icon_location):
    """图标位置归一化：(图标文件, 索引)；无图标时返回 ('', 0)。

    图标位置形如 "C:\\Windows\\System32\\shell32.dll,13"。注意"没有自定义
    图标"时外壳返回的是 ",0"（路径为空、索引 0），不能把它当成"没有逗号
    的相对路径"去解析，否则会被拼成当前目录下的文件名。
    """
    text = str(icon_location or "").strip()
    if not text:
        return "", 0
    file_path, sep, raw_index = text.rpartition(",")
    if not sep:
        return _icon_path_key(text), 0
    try:
        index = int(raw_index)
    except ValueError:
        index = 0
    return _icon_path_key(file_path), index


def find_by_target(folder, target):
    """在 folder 中找出指向同一 target 的启动项路径；没有则返回 None。

    .lnk 按其目标比较（同名、不同名的都找），直接放进来的 .exe 按自身
    路径比较。这是「防止重复添加」的基础：同一个程序无论以什么名字
    加进来过，都不再生成第二份。

    只比较目标，不看图标与参数——同一个程序不该在桌面上出现两次。
    """
    key = normalize_path(target)
    if not key:
        return None
    folder = Path(folder)
    if not folder.is_dir():
        return None
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix == ".exe":
            if normalize_path(path) == key:
                return str(path)
        elif suffix == ".lnk":
            existing, _, _ = resolve_lnk(str(path))
            if existing and normalize_path(existing) == key:
                return str(path)
    return None


def find_entry(folder, name, target, args="", workdir="", icon_location=""):
    """找出 folder 中与给定入口完全一致的启动项；没有则返回 None。

    判重条件 = 同名 + 同目标 + 同参数 + 同工作目录 + 同图标。同名是必要的：
    同一个程序挂不同名字（如「重复项」与「桌面程序」指向同一个 exe）属于
    不同条目，不该被合并掉。
    """
    key = normalize_path(target)
    stem = os.path.splitext(str(name or "").strip())[0].lower()
    if not key or not stem:
        return None
    folder = Path(folder)
    if not folder.is_dir():
        return None
    want_args = str(args or "").strip()
    want_workdir = str(workdir or "").strip()
    want_icon = _icon_key(icon_location)
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        if path.stem.strip().lower() != stem:
            continue
        suffix = path.suffix.lower()
        if suffix == ".exe":
            # 直接放进来的 exe 没有参数与自定义图标
            if want_args or want_workdir or want_icon[0]:
                continue
            if normalize_path(path) == key:
                return str(path)
        elif suffix == ".lnk":
            existing, ex_args, ex_workdir = resolve_lnk(str(path))
            if not existing or normalize_path(existing) != key:
                continue
            if str(ex_args or "").strip() != want_args:
                continue
            if str(ex_workdir or "").strip() != want_workdir:
                continue
            if _icon_key(get_icon_location(str(path))) != want_icon:
                continue
            return str(path)
    return None


def find_duplicate_copy(folder, source):
    """找出 folder 中与 source 内容完全相同的 .lnk 副本；没有则返回 None。

    用于解析不出目标的 .lnk（商店应用等）：这种快捷方式没法按目标比较，
    只能按文件内容（复制出来的副本与源文件逐字节相同）判定重复。
    """
    folder = Path(folder)
    if not folder.is_dir():
        return None
    try:
        source_size = os.path.getsize(source)
    except OSError:
        return None
    for path in sorted(folder.rglob("*.lnk")):
        if not path.is_file():
            continue
        try:
            if os.path.getsize(path) != source_size:
                continue
            with open(path, "rb") as fp:
                data = fp.read()
            with open(source, "rb") as fs:
                if data == fs.read():
                    return str(path)
        except OSError:
            continue
    return None


def unique_lnk_path(folder, name):
    """在 folder 中为 name 取一个不重复的 .lnk 路径（"name (2).lnk" 依次递增）。

    扩展名固定为 .lnk：名字里带 ".exe" 之类时若沿用原扩展名，会生成
    "应用 (2).exe" 这种非快捷方式文件。
    """
    base = (name or "应用").strip()
    stem = os.path.splitext(base)[0] or "应用"
    candidate = Path(folder) / f"{stem}.lnk"
    index = 2
    while candidate.exists():
        candidate = Path(folder) / f"{stem} ({index}).lnk"
        index += 1
    return candidate


def create_shortcut(folder, name, target, args="", workdir="", icon_location=""):
    """在 folder 中创建名为 name 的快捷方式，返回创建或复用的路径。

    同名且完全相同的入口（目标+参数+工作目录+图标）已存在时直接复用，
    不会重复生成文件。名字被别的条目占着时退让为 "名称 (2).lnk"。

    注意「同一个程序不许出现两次」是在添加流程里判的（见 find_by_target）：
    同一个 exe 用不同名字加进来属于不同条目，这里按名字分开建。
    """
    folder = Path(folder)
    base = (name or "").strip() or Path(str(target)).stem or "应用"
    stem = os.path.splitext(base)[0] or "应用"
    # 已有同名且完全相同的入口 → 直接复用
    reused = find_entry(folder, stem, target, args, workdir, icon_location)
    if reused:
        return Path(reused)
    # 名字被别的条目占着 → 退让为 "名称 (2).lnk"
    lnk_path = folder / f"{stem}.lnk"
    if lnk_path.exists():
        lnk_path = unique_lnk_path(folder, stem)
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
