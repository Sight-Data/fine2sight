# -*- coding: utf-8 -*-
"""转换器版本信息(单一真值源)。

- __version__：语义版本号 MAJOR.MINOR.PATCH。构建脚本每次编译自增 PATCH
  (见同目录 _bump_and_stamp.py),实现「每次编译更新版本号」。
- 构建戳(构建日期 + git 短哈希)由构建脚本写入同目录 _build.py(已 gitignore),
  随每次编译刷新;直接跑源码(未构建)时无 _build.py,标记为 dev。
- UPDATE_CHECK_URLS：程序启动时按顺序请求这些 JSON 比对版本号,有新版则提示升级。
  优先官网主域名 sightdata.top,连不上再退到备用域名 sight-report.top;任一成功即止。
  JSON 约定字段:{"version": "1.2.0", "url": "下载地址", "notes": "更新说明"}。
  可被 config.json 的 update_check_url 覆盖(见 core_api.check_update)。
"""

__version__ = "1.3.0"

# 官网最新版清单(按顺序尝试:主域名优先,备用域名兜底)。
# 清单文件在仓库里:website/public/finereport-converter/latest.json(随官网部署到 /opt/website/public/)。
# 也可在 config.json 里用 update_check_url 覆盖。
# ⚠️ 兜底域名必须是「真能解析 + 证书有效 + 反代到同一个官网 node 应用」的域名,否则等于没有:
#    原先写的 sight-report.top **根本没有 DNS 解析**(2026-07-16 实测),兜底一直是死的。
#    magic-report.top 与 sightdata.top 反代到同一个 node 应用(同机 nginx),会供上同一份 latest.json。
UPDATE_CHECK_URLS = [
    "https://sightdata.top/finereport-converter/latest.json",       # 优先(证书 certbot 自动续期)
    "https://magic-report.top/finereport-converter/latest.json",    # 兜底(同机同应用,另一域名)
]

# 兼容旧引用:单一地址 = 首选地址
UPDATE_CHECK_URL = UPDATE_CHECK_URLS[0]


def build_stamp():
    """构建戳:'YYYY-MM-DD·<gitrev>';未构建(源码运行)返回 'dev'。"""
    try:
        from _build import BUILD_DATE, GIT_REV  # 构建脚本生成,gitignore
        return "%s·%s" % (BUILD_DATE, GIT_REV)
    except Exception:
        return "dev"


def full_version():
    """完整展示用版本串,如 '1.0.3 (2026-06-15·a1b2c3d)' 或 '1.0.0 (dev)'。"""
    return "%s (%s)" % (__version__, build_stamp())
