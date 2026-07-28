# -*- coding: utf-8 -*-
"""帆软报表转换器 — 桌面应用(pywebview)。

界面是一张本地 HTML(web/index.html),套进原生窗口;真实逻辑全在 core_api。
源码运行:  python app.py
打包:      见 build-mac.sh / build-windows.bat
"""
import os
import sys
import json
import subprocess

import webview

import core_api


def _resource(*parts):
    """兼容源码运行与 PyInstaller 打包(_MEIPASS)的资源路径。"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def _open_in_os(path):
    """用系统默认方式打开文件或目录。"""
    if not path or not os.path.exists(path):
        return False
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
        elif os.name == "nt":
            os.startfile(path)  # noqa: D
        else:
            subprocess.Popen(["xdg-open", path])
        return True
    except Exception:
        return False


class Api:
    """暴露给页面 JS 的接口(pywebview.api.xxx)。"""

    def pick_files(self):
        w = webview.windows[0]
        res = w.create_file_dialog(
            webview.OPEN_DIALOG, allow_multiple=True,
            file_types=("帆软报表 (*.cpt)", "所有文件 (*.*)"))
        return list(res) if res else []

    def pick_folder(self):
        w = webview.windows[0]
        res = w.create_file_dialog(webview.FOLDER_DIALOG)
        return (list(res)[0] if res else None)

    def pick_output(self):
        w = webview.windows[0]
        res = w.create_file_dialog(webview.FOLDER_DIALOG)
        return (list(res)[0] if res else None)

    def scan_connections(self, inputs):
        return core_api.scan_connections(inputs or [])

    def run(self, payload):
        payload = payload or {}

        def _progress(done, total, path):
            try:
                webview.windows[0].evaluate_js(
                    "window.onProgress && window.onProgress(%d,%d,%s)"
                    % (done, total, json.dumps(os.path.basename(path))))
            except Exception:
                pass

        return core_api.run_conversion(
            inputs=payload.get("inputs") or [],
            outdir=payload.get("outdir") or "",
            conn_map=payload.get("conn_map") or {},
            overwrite=payload.get("overwrite") or "overwrite",
            make_zip=bool(payload.get("zip")),
            merge_sheets=payload.get("merge_sheets", True),
            progress=_progress)

    def open_path(self, path):
        return _open_in_os(path)

    def open_parent(self, path):
        return _open_in_os(os.path.dirname(path) if path else "")

    def open_url(self, url):
        """在系统默认浏览器打开 URL(升级下载链接用)。"""
        if not url:
            return False
        try:
            import webbrowser
            return bool(webbrowser.open(url))
        except Exception:
            return False

    # ---- 版本 / 更新检查 ----
    def version(self):
        return core_api.get_version()

    def check_update(self):
        return core_api.check_update()


def main():
    api = Api()
    with open(_resource("web", "index.html"), encoding="utf-8") as f:
        html = f.read()
    webview.create_window(
        "帆软报表 → sight-report 转换器  v%s" % core_api.get_version()["version"],
        html=html, js_api=api,
        width=1000, height=760, min_size=(860, 640))
    webview.start()


if __name__ == "__main__":
    main()
