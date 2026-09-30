# iconDesktop

Python 版「开始屏幕」应用启动器：扫描程序同级「快捷方式」文件夹中的启动项，
以分页图标网格展示，双击图标即可打开应用；支持手动添加、搜索过滤、拖拽整理。

基于 PySide6 (Qt6)，`.lnk` 图标从其目标文件提取（不带快捷方式小箭头）。

## 功能

- **快捷方式文件夹**：启动时扫描程序同级「快捷方式」文件夹（不存在会自动创建），
  把 `.lnk` / `.exe` 放进去即可出现在网格里，支持子文件夹，点「刷新」重新扫描
- **添加EXE 按钮**：多选 exe/lnk 后自动在「快捷方式」文件夹里生成快捷方式
  （保留参数、工作目录、自定义图标），与手动放入的条目同等管理
- **分页网格**：图标按顺序紧凑铺满每一页（与手机桌面一致），没有滚动条；
  新加入的应用自动排到最后一页的空位，不会与旧图标重叠
- **翻页**：键盘 A/D、←/→、PgUp/PgDn、Home/End，鼠标滚轮，以及右侧翻页栏
  （极简样式：上下箭头 + 页位点，点击箭头翻页、点击页位点跳转，当前页显示为
  长条；只有一页时自动隐藏）
- **缩放**：Ctrl+滚轮缩放图标；窗口放大缩小时图标也随之缩放，格子宽高比固定
  2:3，最小缩到 40×60，更小的窗口靠增加页数容纳
- **双击启动**：默认双击图标启动应用（可在设置里切换为单击）；启动后窗口自动
  最小化（可关）
- **系统托盘**：托盘常驻图标，左键单击显示/隐藏主窗口；点窗口关闭会最小化到
  托盘，真正退出走托盘菜单的「退出」
- **自定义标题栏**：无系统边框窗口，标题栏随主题配色；支持拖动、边缘缩放、
  双击最大化、Aero Snap 贴靠（Windows 上经 WM_NCHITTEST 交还系统处理）
- **单实例**：重复启动时不会开出第二个程序，而是把已在运行的那个实例的
  主窗口唤到前台
- **启动自清理**：启动时检查配置，文件夹里已不存在的条目（隐藏、排序等）
  会从配置中一并删除；旧版 %APPDATA% 配置自动迁移到程序同级目录，
  旧版格子坐标自动迁移为显示顺序
- **右键菜单**：打开 / 删除（删除会连同「快捷方式」文件夹里的对应文件
  一起清掉，并同步清理配置）
- **搜索过滤**：顶部搜索框实时过滤，过滤结果重新分页
- **拖拽整理**（与手机桌面一致；插入点钳制在本页内，不会把图标挤出本页）：
  落点分区按光标在目标图标格子内的横向位置计算，任意图标都能触发移位：
  - 落在目标格子中间 50% 宽度 → 与目标图标互换
  - 落在目标格子左 1/4 边缘 → 插到目标图标之前，落点到原位之间的图标向
    原位方向顺移一格补位
  - 落在目标格子右 1/4 边缘 → 对称地插到目标图标之后
  - 拖动时「图标 + 名称」以不透明像素图由系统带着丝滑跟随光标；受影响
    的图标实时动画偏移预览（中间区不偏移），半透明落点阴影吸附插入点
    作落位指引，松手落位与预览一致，Esc 取消
- **深色/浅色主题**：默认深色，设置菜单可切换「深色模式」，选择会记住；
  配色固定不随 Windows 深色模式变化，深色模式下窗口标题栏同步变暗
- **状态持久化**：便携版配置存于 C 盘用户目录 `%APPDATA%\iconDesktop`；
  数据跟随 exe 的版本存于程序同级目录 `config.json`

## 运行

```bash
pip install -r requirements.txt
python main.py
```

## 打包 exe

```bash
python build.py --config-location appdata   # 便携版（日常使用/分发用这个）
python build.py                             # 数据跟随 exe 的单文件版
python build.py --clean                     # 清空 PyInstaller 缓存，全量重建
```

| 版本 | 命令 | 产物 | config.json 与「快捷方式」位置 |
|------|------|------|--------------------------------|
| 便携版 | `python build.py --config-location appdata` | `dist\iconDesktop_appdata.exe` | C 盘用户目录 `%APPDATA%\iconDesktop` |
| 数据跟随 exe（默认） | `python build.py` | `dist\iconDesktop.exe` | exe 同级目录 |

- **便携版**是日常使用的版本：数据统一放 C 盘用户目录，exe 放哪都能跑
  （包括只读目录如 Program Files），换 exe 不丢布局；产物名自动加
  `_appdata` 后缀与数据跟随 exe 的版本区分
- 两种版本都可以用 `--mode onedir` 打成文件夹形态（打包和启动都更快，
  分发时把整个文件夹压缩成 zip 即可），默认 onefile 单文件
- 旧版的格子坐标配置会在新版首次启动时自动迁移为显示顺序

全部构建参数（临时生效不改动 JSON；想固化就改 `build_config.json`，文件内有
中文说明，脚本读取它生成 `iconDesktop_auto.spec` 再调用 PyInstaller）：

| 参数 | 作用 |
|------|------|
| `--config-location appdata\|exe` | 临时覆盖数据位置：appdata=便携版（数据放 C 盘用户目录，产物加 `_appdata` 后缀）；exe=跟随 exe 所在目录 |
| `--mode onefile\|onedir` | 临时覆盖产物形态：onefile=单个 exe（每次启动要自解压）；onedir=`dist\<名字>\` 整个文件夹（打包和启动都快） |
| `--clean` | 清空 PyInstaller 缓存，全量重建 |
| `--print-spec` | 只预览生成的 spec 内容，不打包 |
| `--config <路径>` | 使用其他配置文件（默认程序同级的 build_config.json） |

提速要点：PyInstaller 没有多线程选项，脚本默认通过 `strip_binaries` 剔除用不到的
大体积二进制（exe 从约 58MB 降到 34MB；注意 qt6network/qtnetwork.pyd 不能剔，
单实例检测用到 QtNetwork），配合增量缓存（`clean: false`）、关闭 UPX、降低日志
级别来加快构建。

## 项目结构

```
main.py                入口
app/
  main_window.py       主窗口（搜索栏 + 网格 + 翻页栏 + 托盘 + 设置）
  icon_grid.py         图标网格组件（分页布局/缩放/翻页/拖拽整理/右键菜单/过滤）
                       与右侧翻页栏 PageBar
  title_bar.py         自定义标题栏（无系统边框、窗口控制按钮、命中测试）
  scanner.py           「快捷方式」文件夹扫描
  lnk_utils.py         .lnk 目标解析与图标来源（pywin32）
  launcher.py          应用启动封装
  config.py            JSON 配置读写（含旧坐标配置迁移）
  theme.py             配色主题（浅色/深色 QPalette 与深色标题栏）
smoke_test.py          离屏冒烟测试（python smoke_test.py）
drag_test.py           分页与拖拽整理离屏回归测试（python drag_test.py）
ui_demo_test.py        UI 截图演示测试（python ui_demo_test.py）
build.py               打包脚本（读取 build_config.json）
build_config.json      打包参数配置（模式/图标/剔除文件等，可手改）
iconDesktop.spec       旧的手写 PyInstaller 配置（仍可用）
```
