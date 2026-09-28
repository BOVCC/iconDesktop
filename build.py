#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iconDesktop 打包脚本：读取 build_config.json，生成 spec 后调用 PyInstaller。

日常用法（打包参数都在 build_config.json 里改，本脚本一般不带参数运行）：
    python build.py                 # 按 build_config.json 打包
    python build.py --mode onedir   # 本次临时改用 onedir 模式（不改动 JSON）
    python build.py --config-location appdata   # 本次打「安装版」：配置放 C 盘
    python build.py --clean         # 清空 PyInstaller 缓存，全量重建
    python build.py --print-spec    # 只打印将生成的 spec 内容，不打包
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT / "build_config.json"
GENERATED_SPEC = ROOT / "iconDesktop_auto.spec"
STATS_FILE = ROOT / ".build_stats.json"

DEFAULTS = {
    "mode": "onefile",
    "name": "iconDesktop",
    "entry": "main.py",
    "console": False,
    "icon": None,
    "version_file": None,
    "upx": False,
    "clean": False,
    "noconfirm": True,
    "log_level": "WARN",
    "excludes": ["tkinter", "matplotlib", "numpy"],
    "collect": ["win32com"],
    "hiddenimports": [],
    "strip_binaries": [],
    "datas": [],
    "config_location": "exe",
    "dist_path": "dist",
    "work_path": "build",
    "python": None,
}


def fail(msg: str):
    print(f"[build.py] 错误：{msg}", file=sys.stderr)
    sys.exit(1)


def load_config(path: Path, overrides: dict) -> dict:
    if not path.is_file():
        fail(f"找不到配置文件：{path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"{path.name} 不是合法 JSON：第 {exc.lineno} 行 {exc.msg}")
    if not isinstance(raw, dict):
        fail(f"{path.name} 顶层必须是一个 JSON 对象")

    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in raw.items() if not k.startswith("_")})
    cfg.update(overrides)

    # ---- 校验 ----
    if cfg["mode"] not in ("onefile", "onedir"):
        fail(f"mode 只能是 onefile 或 onedir，当前是 {cfg['mode']!r}")
    if cfg["config_location"] not in ("exe", "appdata"):
        fail(f"config_location 只能是 exe 或 appdata，当前是 {cfg['config_location']!r}")
    if not cfg["name"] or any(c in cfg["name"] for c in "/\\"):
        fail(f"name 不能为空且不能含路径分隔符，当前是 {cfg['name']!r}")
    if str(cfg["log_level"]).upper() not in ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL", "CRITICAL"):
        fail(f"log_level 取值应为 DEBUG/INFO/WARN/ERROR 等，当前是 {cfg['log_level']!r}")

    entry = (path.parent / cfg["entry"]).resolve()
    if not entry.is_file():
        fail(f"入口文件不存在：{entry}")
    cfg["_entry"] = str(entry)

    for key in ("icon", "version_file"):
        if cfg[key] is not None:
            p = (path.parent / cfg[key]).resolve()
            if not p.is_file():
                fail(f"{key} 指向的文件不存在：{p}")
            cfg[f"_{key}"] = str(p)
        else:
            cfg[f"_{key}"] = None

    if cfg["python"] is not None:
        p = (path.parent / cfg["python"]).resolve()
        if not p.is_file():
            fail(f"python 指定的解释器不存在：{p}")
        cfg["_python"] = str(p)
    else:
        cfg["_python"] = sys.executable

    datas = []
    for item in cfg["datas"]:
        if not (isinstance(item, list) and len(item) == 2 and all(isinstance(i, str) for i in item)):
            fail(f'datas 每项必须是 ["源文件", "目标目录"]，当前是 {item!r}')
        src = (path.parent / item[0]).resolve()
        if not src.is_file():
            fail(f"datas 源文件不存在：{src}")
        datas.append((str(src), item[1]))
    cfg["_datas"] = datas

    for key in ("excludes", "collect", "hiddenimports", "strip_binaries"):
        if not isinstance(cfg[key], list) or not all(isinstance(i, str) for i in cfg[key]):
            fail(f"{key} 必须是字符串列表")

    cfg["_dist"] = (path.parent / cfg["dist_path"]).resolve()
    cfg["_work"] = (path.parent / cfg["work_path"]).resolve()

    # 安装版（appdata）：产物加后缀与便携版区分，并通过运行时钩子注入
    # 数据目录环境变量（见 app/scanner.py 的 data_dir）
    if cfg["config_location"] == "appdata":
        cfg["_product_name"] = f"{cfg['name']}_appdata"
        cfg["_rthook"] = str(cfg["_work"] / "rthook_config_location.py")
        cfg["_runtime_hooks"] = [cfg["_rthook"]]
    else:
        cfg["_product_name"] = cfg["name"]
        cfg["_rthook"] = None
        cfg["_runtime_hooks"] = []
    return cfg


def write_config_hook(cfg: dict) -> None:
    """生成安装版的运行时钩子：在入口脚本执行前设置数据目录环境变量。"""
    if not cfg["_rthook"]:
        return
    hook = Path(cfg["_rthook"])
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(
        "# 本文件由 build.py 自动生成，请勿手改。\n"
        "# 安装版：把 config.json 与「快捷方式」文件夹定位到 C 盘 %APPDATA%。\n"
        "import os\n"
        "\n"
        'os.environ.setdefault("ICONDESKTOP_CONFIG_LOCATION", "appdata")\n',
        encoding="utf-8",
    )


def build_spec_text(cfg: dict) -> str:
    """根据配置生成 PyInstaller spec 文件内容。"""
    lines = [
        "# -*- mode: python ; coding: utf-8 -*-",
        "# 本文件由 build.py 根据 build_config.json 自动生成，请勿手改；",
        "# 要改打包参数请编辑 build_config.json。",
        "from PyInstaller.utils.hooks import collect_submodules",
        "",
        "hiddenimports = []",
    ]
    for pkg in cfg["collect"]:
        lines.append(f"hiddenimports += collect_submodules({pkg!r})")
    if cfg["hiddenimports"]:
        lines.append(f"hiddenimports += {cfg['hiddenimports']!r}")

    datas = ", ".join(f"({src!r}, {dst!r})" for src, dst in cfg["_datas"])
    lines += [
        "",
        "a = Analysis(",
        f"    [{cfg['_entry']!r}],",
        "    pathex=[],",
        "    binaries=[],",
        f"    datas=[{datas}],",
        "    hiddenimports=hiddenimports,",
        "    hookspath=[],",
        "    hooksconfig={},",
        f"    runtime_hooks={cfg['_runtime_hooks']!r},",
        f"    excludes={cfg['excludes']!r},",
        "    noarchive=False,",
        ")",
    ]

    if cfg["strip_binaries"]:
        patterns = [p.lower() for p in cfg["strip_binaries"]]
        lines += [
            "",
            "# 剔除用不到的二进制（片段匹配，来自 build_config.json 的 strip_binaries）",
            f"strip_binaries = {patterns!r}",
            "a.binaries = [b for b in a.binaries",
            "              if not any(p in b[0].lower() for p in strip_binaries)]",
        ]

    lines += [
        "",
        "pyz = PYZ(a.pure)",
        "",
    ]

    exe_common = [
        f"    name={cfg['_product_name']!r},",
        "    debug=False,",
        "    bootloader_ignore_signals=False,",
        "    strip=False,",
        f"    upx={bool(cfg['upx'])!r},",
        f"    console={bool(cfg['console'])!r},",
        "    disable_windowed_traceback=False,",
        "    argv_emulation=False,",
        "    target_arch=None,",
        "    codesign_identity=None,",
        "    entitlements_file=None,",
    ]
    if cfg["_icon"]:
        exe_common.append(f"    icon={cfg['_icon']!r},")
    if cfg["_version_file"]:
        exe_common.append(f"    version={cfg['_version_file']!r},")

    if cfg["mode"] == "onefile":
        lines += ["exe = EXE(", "    pyz,", "    a.scripts,", "    a.binaries,", "    a.datas,", "    [],"]
        lines += exe_common
        lines += ["    upx_exclude=[],", "    runtime_tmpdir=None,", ")"]
    else:
        lines += ["exe = EXE(", "    pyz,", "    a.scripts,", "    [],", "    exclude_binaries=True,"]
        lines += exe_common
        lines += [
            ")",
            "",
            "coll = COLLECT(",
            "    exe,",
            "    a.binaries,",
            "    a.datas,",
            "    strip=False,",
            f"    upx={bool(cfg['upx'])!r},",
            "    upx_exclude=[],",
            f"    name={cfg['_product_name']!r},",
            ")",
        ]
    return "\n".join(lines) + "\n"


def human_size(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num < 1024 or unit == "GB":
            return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
        num /= 1024
    return f"{num:.1f} GB"


def tree_size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    total = 0
    for f in p.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
            except OSError:
                pass
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="按 build_config.json 调用 PyInstaller 打包 iconDesktop")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="配置文件路径（默认 build_config.json）")
    parser.add_argument("--mode", choices=("onefile", "onedir"), help="临时覆盖配置里的 mode（不改动 JSON）")
    parser.add_argument(
        "--config-location",
        choices=("exe", "appdata"),
        help="临时覆盖配置里的 config_location：exe=配置跟随 exe；appdata=配置放 C 盘 %%APPDATA%（产物名加 _appdata 后缀）",
    )
    parser.add_argument("--clean", action="store_true", help="清空 PyInstaller 缓存后全量重建")
    parser.add_argument("--print-spec", action="store_true", help="只打印生成的 spec，不执行打包")
    args = parser.parse_args()

    overrides = {}
    if args.mode:
        overrides["mode"] = args.mode
    if args.config_location:
        overrides["config_location"] = args.config_location
    if args.clean:
        overrides["clean"] = True

    cfg = load_config(Path(args.config).resolve(), overrides)
    spec_text = build_spec_text(cfg)

    if args.print_spec:
        print(spec_text, end="")
        return

    GENERATED_SPEC.write_text(spec_text, encoding="utf-8")
    write_config_hook(cfg)

    cmd = [
        cfg["_python"], "-m", "PyInstaller",
        str(GENERATED_SPEC),
        "--distpath", str(cfg["_dist"]),
        "--workpath", str(cfg["_work"]),
        "--log-level", str(cfg["log_level"]).upper(),
    ]
    if cfg["noconfirm"]:
        cmd.append("--noconfirm")
    if cfg["clean"]:
        cmd.append("--clean")

    extra = "，clean=全量重建" if cfg["clean"] else ""
    print(f"[1/2] 开始打包（mode={cfg['mode']}，config={cfg['config_location']}{extra}）...")
    print(f"      {' '.join(cmd)}")
    if cfg["config_location"] == "appdata":
        print("      安装版：配置与「快捷方式」文件夹将位于 C 盘 %APPDATA%\\iconDesktop")

    start = time.perf_counter()
    try:
        result = subprocess.run(cmd, cwd=str(ROOT))
    except KeyboardInterrupt:
        fail("已取消")
    elapsed = time.perf_counter() - start

    if result.returncode != 0:
        fail(f"PyInstaller 退出码 {result.returncode}，打包失败（用时 {elapsed:.1f} 秒）")

    product = (cfg["_dist"] / cfg["_product_name"]) if cfg["mode"] == "onedir" else (cfg["_dist"] / f"{cfg['_product_name']}.exe")
    if not product.exists():
        fail(f"打包结束但找不到产物：{product}")

    size = tree_size(product)
    note = ""
    if STATS_FILE.is_file():
        try:
            prev = json.loads(STATS_FILE.read_text(encoding="utf-8"))
            if prev.get("mode") == cfg["mode"] and prev.get("elapsed"):
                delta = elapsed - prev["elapsed"]
                word = "慢" if delta > 0 else "快"
                note = f"（比上次{word} {abs(delta):.1f} 秒）"
        except (json.JSONDecodeError, OSError):
            pass
    STATS_FILE.write_text(
        json.dumps({"mode": cfg["mode"], "elapsed": elapsed, "size": size}, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"[2/2] 完成：{product}")
    print(f"      体积 {human_size(size)}，用时 {elapsed:.1f} 秒{note}")
    if cfg["mode"] == "onedir":
        print("      onedir 产物是整个文件夹，分发时把它压缩成 zip 即可。")


if __name__ == "__main__":
    main()
