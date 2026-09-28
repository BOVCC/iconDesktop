"""应用启动封装。"""
import os
import shlex
import subprocess


class LaunchError(Exception):
    """启动失败。"""


def launch(path, args="", workdir=""):
    """启动一个应用：.lnk 走 shell 打开，其余用 subprocess 并附带参数。"""
    path = os.path.abspath(str(path))
    if not os.path.exists(path):
        raise LaunchError(f"文件不存在: {path}")
    try:
        if path.lower().endswith(".lnk"):
            os.startfile(path)  # noqa: S606 - 受控环境下的预期行为
        else:
            cmd = [path]
            if args:
                cmd += shlex.split(args, posix=False)
            subprocess.Popen(cmd, cwd=workdir or os.path.dirname(path))
    except OSError as exc:
        raise LaunchError(f"启动失败: {path}\n{exc}") from exc
