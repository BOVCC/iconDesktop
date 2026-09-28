"""iconDesktop — Python 版开始屏幕应用启动器。"""
import signal
import sys

from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow

SINGLE_INSTANCE_KEY = "iconDesktop.single-instance"


def already_running() -> bool:
    """是否已有实例在运行；是则请求它显示主窗口，供本次启动直接退出。"""
    socket = QLocalSocket()
    socket.connectToServer(SINGLE_INSTANCE_KEY)
    if not socket.waitForConnected(300):
        return False
    socket.write(b"show")
    socket.flush()
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


def start_single_instance_server(window: MainWindow) -> QLocalServer:
    """监听单实例通道：后来实例连上来时，把主窗口唤到前台。"""
    QLocalServer.removeServer(SINGLE_INSTANCE_KEY)  # 清理上次异常退出残留
    server = QLocalServer()

    def on_connection():
        socket = server.nextPendingConnection()
        if socket is None:
            return
        socket.disconnected.connect(socket.deleteLater)
        socket.readyRead.connect(lambda: (socket.readAll(), window.present()))

    server.newConnection.connect(on_connection)
    server.listen(SINGLE_INSTANCE_KEY)
    return server


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("iconDesktop")
    app.setApplicationDisplayName("iconDesktop")
    app.setStyle("Fusion")
    # 单实例：已有实例在运行时不再重复打开，请求其显示主窗口后退出
    if already_running():
        return
    # 配色固定为应用内主题（浅色/深色），不随 Windows 深色模式变化；
    # 主题在 MainWindow 初始化时按配置应用
    window = MainWindow()
    window.startup_cleanup()  # 迁移旧配置、清理已失效的快捷方式信息
    window.show()
    server = start_single_instance_server(window)  # noqa: F841 保活到进程结束

    # Qt 事件循环阻塞在 C++ 里，Python 层的 SIGINT/SIGBREAK 处理函数没机会
    # 执行，Ctrl+C 默认无效。定时器周期性把主线程带回 Python 层让信号得以
    # 处理；收到 Ctrl+C 时保存状态后正常退出（与托盘「退出」同一路径）
    for sig_name in ("SIGINT", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            signal.signal(sig, lambda *_: window._save_and_quit())
    interrupt_timer = QTimer()
    interrupt_timer.timeout.connect(lambda: None)
    interrupt_timer.start(200)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
