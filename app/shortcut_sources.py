"""收集开始菜单与桌面上的快捷方式（「全部快捷方式」窗口的数据来源）。

只做廉价的文件扫描与按名称去重，不解析 .lnk（解析一个要走 COM，约 2.4ms；
三百多个快捷方式要 0.8s，会让窗口打开明显变慢）。快捷方式的目标解析留在
真正添加时由 lnk_utils 做，因此这里给出的只是「路径 + 显示名 + 来源」。

同名重复（同一个应用在用户/所有用户的开始菜单里各有一份是常见情况）只保留
第一份，来源优先级与 ROOTS 的顺序一致。
"""
import os
from pathlib import Path


def _start_menu_dirs():
    appdata = os.environ.get("APPDATA", "")
    programdata = os.environ.get("ProgramData", "")
    return (
        (Path(appdata) / "Microsoft/Windows/Start Menu/Programs", "开始菜单"),
        (Path(programdata) / "Microsoft/Windows/Start Menu/Programs", "所有用户开始菜单"),
    )


def _desktop_dirs():
    userprofile = os.environ.get("USERPROFILE", "")
    public = os.environ.get("PUBLIC", "")
    return (
        (Path(userprofile) / "Desktop", "桌面"),
        (Path(public) / "Desktop", "公共桌面"),
    )


def source_roots():
    """(目录, 来源标签) 列表；顺序决定同名重复时保留哪一份。"""
    return _start_menu_dirs() + _desktop_dirs()


def collect_shortcuts(roots=None):
    """返回 [{name, path, args, workdir, source, tip}]，按名称排序。

    目录不存在会被跳过（例如某些系统没有公共桌面），可传入 roots 覆盖
    （测试用：[ (目录, 标签), ... ]）。
    """
    entries = {}
    for folder, label in (roots if roots is not None else source_roots()):
        folder = Path(folder)
        if not folder.is_dir():
            continue
        try:
            paths = sorted(folder.rglob("*.lnk"))
        except OSError:
            continue
        for path in paths:
            try:
                if not path.is_file():
                    continue
            except OSError:
                continue
            name = path.stem.strip()
            key = name.lower()
            if not name or key in entries:
                continue
            entries[key] = {
                "name": name,
                "path": str(path),
                "args": "",
                "workdir": "",
                "source": label,
                "tip": f"{label}：{path}",
            }
    return sorted(entries.values(), key=lambda e: e["name"].lower())
