# -*- coding: utf-8 -*-
"""Windows 打包用的 PyInstaller 调用封装(替代 build-windows.bat 里直接内联的
`pyinstaller --name "帆软报表转换器" ...` 命令行)。

背景(真机+CI 均已复现的 bug):.bat 文本里的中文命令行参数要靠 cmd.exe 按**当前活动
代码页**解析后才能构造出子进程的命令行。GitHub Actions windows-latest 默认代码页不是
UTF-8(chcp 65001 只切了控制台 I/O 代码页,不保证 cmd.exe 解析批处理文本里的中文实参这条
链路可靠),实测导致 `--name` 参数丢失/损坏,PyInstaller 落回内置默认名,产物变成
`dist\\default.exe` 而不是 `dist\\帆软报表转换器.exe`(2026-07-29 v1.1.1 发布时首次发现,
因为这是 build-desktop.yml 这条 GitHub Actions 打包链路第一次真正跑通产出正式 Release)。

根治办法:把这个中文参数从"cmd.exe 批处理文本里的命令行实参"挪成"Python 源码里的字符串
字面量"——本文件本身按 UTF-8 读取(Python 3 默认源码编码),`APP_NAME` 常量在这里就是正确
的 Unicode 字符串,完全不经过 cmd.exe 的参数解析;随后 `subprocess.run(list, ...)` 在
Windows 上走 `CreateProcessW`(宽字符 API)拼子进程命令行,同样不受活动代码页影响。
build-windows.bat 只需要执行 `python _pyinstaller_win.py` 这一句纯 ASCII 命令,不会再触发
这个坑。
"""
import subprocess
import sys

APP_NAME = "帆软报表转换器"


def main():
    subprocess.run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed", "--onefile",
        "--name", APP_NAME,
        "--icon", "assets/icon.ico",
        "--collect-all", "webview",
        "--add-data", "web;web",
        "--paths", "..",
        "--hidden-import", "convert",
        "--hidden-import", "version",
        "--hidden-import", "_build",
        "app.py",
    ], check=True)


if __name__ == "__main__":
    main()
