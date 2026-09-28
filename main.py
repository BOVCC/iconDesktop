"""iconDesktop — Python 版开始屏幕应用启动器。"""
import sys

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("iconDesktop")
    app.setApplicationDisplayName("iconDesktop")
    app.setStyle("Fusion")
    # 配色固定为应用内主题（浅色/深色），不随 Windows 深色模式变化；
    # 主题在 MainWindow 初始化时按配置应用
    window = MainWindow()
    window.startup_cleanup()  # 迁移旧配置、清理已失效的快捷方式信息
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
