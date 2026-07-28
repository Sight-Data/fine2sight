# 帆软报表转换器 · 桌面应用

把帆软 `.cpt` 网格报表批量转换为 sight-report 可导入的 `.mrg` 的图形界面。
底层复用同目录上一级的 `convert.py` 内核,界面用 [pywebview](https://pywebview.flowrl.com/)
(本地 HTML + 原生窗口),打包后是普通双击运行的桌面程序,最终用户无需装 Python。

## 目录结构

```
desktop/
  app.py             # 启动入口(pywebview 窗口 + 文件对话框)
  core_api.py        # 核心层:扫描连接名 / 批量转换 / 结果聚合(无 GUI 依赖,可单测)
  web/index.html     # 界面(单文件)
  requirements.txt   # 运行依赖(只有 pywebview)
  build-mac.sh       # 打包成 .app(在 mac 上跑)
  build-windows.bat  # 打包成 .exe(在 Windows 上跑)
  test_core.py       # core_api 无头自测
  assets/            # 图标:logo.svg(母版) / icon.icns(mac) / icon.ico(win) / logo-1024.png
```

打包脚本已用 `assets/icon.icns`(mac)和 `assets/icon.ico`(win)作应用图标。

## 日常测试(Mac,源码直接跑)

```bash
cd desktop
python3 -m pip install -r requirements.txt
python3 app.py
```

会弹出窗口。用法:
1. **输入**:加文件或文件夹(文件夹递归找 `.cpt`)。
2. **输出目录**:选转换结果放哪。
3. **数据源映射**:点「扫描连接名」,把每个帆软连接(如 `DFHIS`)填上其在 Sight Report 里对应的数据连接名称(常与左侧同名;按名称解析,无需 id)
   (在 Sight Report 后台数据连接管理里能查到;留空的连接转换后会标「待人工」)。
4. **选项**:同名已存在时 覆盖/跳过/重命名;是否额外打包 `.zip`(可在 Sight Report 里按目录批量导入);
   「多 sheet 合并为多页签报表」默认勾选(取消则每 sheet 拆一张)。
   > 开始转换前,若存在用到但未填写数据连接名称的连接,会弹窗提醒并列出这些连接,可选择「去映射填写」或「仍然继续」。
5. 点「**开始转换**」。完成后每张报表显示 单元格数 / 待人工 / 降级 / 状态,可打开输出目录与各自报告。

## 打包

### macOS → `.app`
```bash
cd desktop
./build-mac.sh         # 首次:chmod +x build-mac.sh
# 脚本会自动创建本地 .venv，并在其中安装 pywebview / PyInstaller
# 产物:dist/帆软报表转换器.app(访达里是单个可双击图标)
```
未签名的 app 首次打开会提示「无法验证开发者」→ 右键 → 打开 → 打开(只需一次)。
要彻底去掉提示需 Apple 开发者证书做代码签名 + 公证(可选)。

### Windows → `.exe`
在 Windows 机器上:
```bat
cd desktop
build-windows.bat
REM 产物:dist\帆软报表转换器.exe  (单个文件,直接拷给用户双击运行)
```
- 需系统已装 **WebView2 Runtime**(Win11 和多数 Win10 自带;没有可从微软官网免费装)。
- 已默认 `--onefile` 打成单个 `.exe`(无散落 DLL / 目录)。单文件首次/冷启动会先解包到临时目录、稍慢,个别杀软可能误报(如遇加白即可)。
- 无法跨平台编译:Windows 包必须在 Windows 上打,mac 包必须在 mac 上打。

> **Linux 不出桌面 GUI**:pywebview 依赖系统 WebKitGTK,旧发行版(如 openEuler 22.03 的 2.36)版本太旧,难以满足。Linux 上请直接用 CLI:`python3 convert.py ...`(纯标准库,跨平台无依赖)。

## 说明
- 单位、字体等换算已是校准好的默认值(长度 50800、字号 8),正常无需改;
  要调可改 `../convert.py` 顶部 `DEFAULT_CONFIG`。
- 一张多 sheet 的 `.cpt` **默认合并成一个多页签(tab)`.mrg`**(各 sheet 一个页签,`<sheets>` 包裹,
  写 `<meta minEngine="2">`);取消「合并为多页签」勾选则拆成多个 `<名>__<sheet>.mrg`,各配一份 `.report.md`。
  单 sheet 报表照旧输出扁平老格式。
