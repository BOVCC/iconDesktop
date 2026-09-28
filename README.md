# iconDesktop

Python 版「开始屏幕」应用启动器：扫描程序同级「快捷方式」文件夹中的启动项，
以图标网格展示，点击图标即可打开应用；支持手动添加、搜索过滤、拖拽排序。

基于 PySide6 (Qt6)，`.lnk` 图标从其目标文件提取（不带快捷方式小箭头）。

## 功能

- **快捷方式文件夹**：启动时扫描程序同级「快捷方式」文件夹（不存在会自动创建），
  把 `.lnk` / `.exe` 放进去即可出现在网格里，支持子文件夹，点「刷新」重新扫描
- **添加EXE 按钮**：多选 exe/lnk 后自动在「快捷方式」文件夹里生成快捷方式
  （保留参数、工作目录、自定义图标），与手动放入的条目同等管理
- **手动添加**：「添加应用」可指定名称、启动参数、工作目录，同样生成到文件夹
- **点击启动**：单击图标启动应用（可在设置里切换为双击）；启动后窗口自动最小化（可关）
- **自定义标题栏**：无系统边框窗口，标题栏随主题配色；支持拖动、边缘缩放、
  双击最大化、Aero Snap 贴靠（Windows 上经 WM_NCHITTEST 交还系统处理）
- **启动自清理**：启动时检查配置，文件夹里已不存在的条目（隐藏、排序等）
  会从配置中一并删除；旧版 %APPDATA% 配置自动迁移到程序同级目录
- **右键菜单**：打开 / 隐藏
- **搜索过滤**：顶部搜索框实时过滤
- **拖拽排序**：拖动图标调整顺序，退出时自动保存
- **浅色/深色主题**：设置菜单可勾选「深色模式」，选择会记住；配色固定不随
  Windows 深色模式变化，深色模式下窗口标题栏同步变暗
- **状态持久化**：配置存于程序同级目录 `config.json`（旧版本在 %APPDATA%）

## 运行

```bash
pip install -r requirements.txt
python main.py
```

## 打包 exe

```bash
python build.py
```

打包参数在 `build_config.json` 里改（文件内有中文说明），脚本读取它生成
`iconDesktop_auto.spec` 再调用 PyInstaller。常用临时参数：

```bash
python build.py --mode onedir   # 本次临时改用 onedir 模式（不改动 JSON）
python build.py --clean         # 清空 PyInstaller 缓存，全量重建
python build.py --print-spec    # 只预览生成的 spec，不打包
```

- 默认 `onefile`：产物 `dist\iconDesktop.exe`（单文件、无控制台窗口）
- `onedir` 模式打包和启动都更快：产物是 `dist\iconDesktop\` 整个文件夹，分发时压缩成 zip 即可
- 提速要点：PyInstaller 没有多线程选项，脚本默认通过 `strip_binaries` 剔除用不到的
  大体积二进制（exe 从约 58MB 降到 34MB），配合增量缓存（`clean: false`）、
  关闭 UPX、降低日志级别来加快构建

打包后的 exe 会在其同级目录读写 `config.json` 与「快捷方式」文件夹。旧的
`pyinstaller iconDesktop.spec` 方式仍然可用。

## 项目结构

```
main.py                入口
app/
  main_window.py       主窗口（搜索栏 + 网格 + 设置）
  icon_grid.py         图标网格组件（点击启动/拖拽排序/右键菜单/过滤）
  title_bar.py         自定义标题栏（无系统边框、窗口控制按钮、命中测试）
  add_dialog.py        添加/编辑应用对话框
  scanner.py           「快捷方式」文件夹扫描
  lnk_utils.py         .lnk 目标解析与图标来源（pywin32）
  launcher.py          应用启动封装
  config.py            JSON 配置读写
  theme.py             配色主题（浅色/深色 QPalette 与深色标题栏）
smoke_test.py          离屏冒烟测试（python smoke_test.py）
ui_demo_test.py        UI 截图演示测试（python ui_demo_test.py）
build.py               打包脚本（读取 build_config.json）
build_config.json      打包参数配置（模式/图标/剔除文件等，可手改）
iconDesktop.spec       旧的手写 PyInstaller 配置（仍可用）
```
