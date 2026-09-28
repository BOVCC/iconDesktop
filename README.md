# iconDesktop

Python 版「开始屏幕」应用启动器：扫描程序同级「快捷方式」文件夹中的启动项，
以图标网格展示，双击图标即可打开应用；支持手动添加、搜索过滤、拖拽排序。

基于 PySide6 (Qt6)，`.lnk` 图标从其目标文件提取（不带快捷方式小箭头）。

## 功能

- **快捷方式文件夹**：启动时扫描程序同级「快捷方式」文件夹（不存在会自动创建），
  把 `.lnk` / `.exe` 放进去即可出现在网格里，支持子文件夹，点「刷新」重新扫描
- **添加EXE 按钮**：多选 exe/lnk 后自动在「快捷方式」文件夹里生成快捷方式
  （保留参数、工作目录、自定义图标），与手动放入的条目同等管理
- **双击启动**：默认双击图标启动应用（可在设置里切换为单击）；启动后窗口自动
  最小化（可关）
- **系统托盘**：托盘常驻图标，左键单击显示/隐藏主窗口；点窗口关闭会最小化到
  托盘，真正退出走托盘菜单的「退出」
- **自定义标题栏**：无系统边框窗口，标题栏随主题配色；支持拖动、边缘缩放、
  双击最大化、Aero Snap 贴靠（Windows 上经 WM_NCHITTEST 交还系统处理）
- **单实例**：重复启动时不会开出第二个程序，而是把已在运行的那个实例的
  主窗口唤到前台
- **启动自清理**：启动时检查配置，文件夹里已不存在的条目（隐藏、排序等）
  会从配置中一并删除；旧版 %APPDATA% 配置自动迁移到程序同级目录
- **右键菜单**：打开 / 删除（删除会连同「快捷方式」文件夹里的对应文件
  一起清掉，并同步清理配置）
- **搜索过滤**：顶部搜索框实时过滤
- **拖拽排序**：图标可自由摆放到任意格子，允许中间留空（与桌面图标一致）；
  拖动时半透明图标阴影实时吸附光标所在格子，松手即落在阴影处，落到已占用
  格子时两个图标互换；坐标落位即保存，Esc 取消；新加入的应用放进第一个空格
- **深色/浅色主题**：默认深色，设置菜单可切换「深色模式」，选择会记住；
  配色固定不随 Windows 深色模式变化，深色模式下窗口标题栏同步变暗
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
python build.py --config-location appdata   # 本次打安装版：配置放 C 盘（不改动 JSON）
python build.py --clean         # 清空 PyInstaller 缓存，全量重建
python build.py --print-spec    # 只预览生成的 spec，不打包
```

- 默认 `onefile`：产物 `dist\iconDesktop.exe`（单文件、无控制台窗口）
- `onedir` 模式打包和启动都更快：产物是 `dist\iconDesktop\` 整个文件夹，分发时压缩成 zip 即可
- 配置位置两种版本（`build_config.json` 的 `config_location` 键，或打包时
  `--config-location` 临时指定）：
  - `exe`（便携版，默认）：`config.json` 与「快捷方式」文件夹跟随 exe 所在目录
  - `appdata`（安装版）：数据放 C 盘 `%APPDATA%\iconDesktop`，适合把 exe 放进
    只读目录或做安装包分发；产物名自动加 `_appdata` 后缀与便携版区分
- 提速要点：PyInstaller 没有多线程选项，脚本默认通过 `strip_binaries` 剔除用不到的
  大体积二进制（exe 从约 58MB 降到 34MB），配合增量缓存（`clean: false`）、
  关闭 UPX、降低日志级别来加快构建

打包后的 exe 会在其同级目录读写 `config.json` 与「快捷方式」文件夹。旧的
`pyinstaller iconDesktop.spec` 方式仍然可用。

## 项目结构

```
main.py                入口
app/
  main_window.py       主窗口（搜索栏 + 网格 + 托盘 + 设置）
  icon_grid.py         图标网格组件（双击启动/拖拽排序/右键菜单/过滤）
  title_bar.py         自定义标题栏（无系统边框、窗口控制按钮、命中测试）
  scanner.py           「快捷方式」文件夹扫描
  lnk_utils.py         .lnk 目标解析与图标来源（pywin32）
  launcher.py          应用启动封装
  config.py            JSON 配置读写
  theme.py             配色主题（浅色/深色 QPalette 与深色标题栏）
smoke_test.py          离屏冒烟测试（python smoke_test.py）
drag_test.py           拖拽排序离屏回归测试（python drag_test.py）
ui_demo_test.py        UI 截图演示测试（python ui_demo_test.py）
build.py               打包脚本（读取 build_config.json）
build_config.json      打包参数配置（模式/图标/剔除文件等，可手改）
iconDesktop.spec       旧的手写 PyInstaller 配置（仍可用）
```
