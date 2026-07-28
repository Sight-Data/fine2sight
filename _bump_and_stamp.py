# -*- coding: utf-8 -*-
"""构建脚本调用:每次编译① 自增 version.py 的 PATCH ② 写构建戳 _build.py。

被 desktop/build-mac.sh 与 desktop/build-windows.bat 在 pyinstaller 之前调用。
单独运行也可(`python3 _bump_and_stamp.py`),打印新版本号。

一次发版要同时出多平台(如 mac + windows)时,不应让每个平台各自 +1 导致版本错位。
此时给第一个平台正常自增,其余平台设环境变量 FR_NO_BUMP=1:**只重写构建戳、
不再自增**,保证多平台共用同一版本号。
"""
import os
import re
import subprocess
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def _truthy(v):
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def main():
    no_bump = _truthy(os.environ.get("FR_NO_BUMP"))
    vpath = os.path.join(HERE, "version.py")
    src = open(vpath, encoding="utf-8").read()
    m = re.search(r'__version__\s*=\s*"(\d+)\.(\d+)\.(\d+)"', src)
    if not m:
        raise SystemExit("version.py 里找不到 __version__ = \"x.y.z\"")
    maj, minr, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if no_bump:                                  # 多平台同版本:沿用当前版本号
        newver = "%d.%d.%d" % (maj, minr, patch)
    else:
        patch += 1                               # 每次编译自增 PATCH
        newver = "%d.%d.%d" % (maj, minr, patch)
        src = re.sub(r'(__version__\s*=\s*")\d+\.\d+\.\d+(")',
                     lambda mm: mm.group(1) + newver + mm.group(2), src, count=1)
        open(vpath, "w", encoding="utf-8").write(src)

    try:
        rev = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                      cwd=HERE, stderr=subprocess.DEVNULL).decode().strip()
    except Exception:
        rev = "nogit"
    date = datetime.date.today().isoformat()
    open(os.path.join(HERE, "_build.py"), "w", encoding="utf-8").write(
        "# 自动生成:构建戳(勿手改;已 gitignore)\n"
        'BUILD_DATE = "%s"\nGIT_REV = "%s"\n' % (date, rev))

    print("%s (%s·%s)" % (newver, date, rev))
    return newver


if __name__ == "__main__":
    main()
