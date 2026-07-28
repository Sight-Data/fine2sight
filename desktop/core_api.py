# -*- coding: utf-8 -*-
"""桌面应用核心层(与 GUI 框架无关,可无头单测)。

封装现有 convert.py 内核,对外提供三件事:
  - list_cpt(inputs)          枚举输入(文件/目录,目录递归)中的 .cpt,带镜像子目录
  - scan_connections(inputs)  扫描所有 .cpt 的帆软连接名(<DatabaseName>)去重
  - run_conversion(...)        按选项批量转换,返回每文件结果

GUI 层(app.py)只负责文件对话框 + 调用这里;所有真实逻辑在此,便于自动化测试。
"""
import os
import re
import sys
import json

# 让本模块在「源码运行」和「PyInstaller 打包」两种形态下都能 import 到 convert
_HERE = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_HERE)               # 仓库根(desktop/ 的上一级)
for _p in (_PARENT, getattr(sys, "_MEIPASS", "")):
    if _p and _p not in sys.path:
        sys.path.insert(0, _p)

import convert  # noqa: E402


# ----------------------------------------------------------------------------
def list_cpt(inputs):
    """inputs: 文件或目录路径列表 → [(cpt绝对路径, 镜像子目录)] 去重排序。

    目录输入会以「目录名」作为镜像顶层,内部结构原样保留;单文件输入子目录为空。
    """
    pairs = []
    for inp in inputs:
        if not inp:
            continue
        inp = os.path.abspath(inp)
        if os.path.isdir(inp):
            base = os.path.basename(inp.rstrip(os.sep)) or "report"
            for dp, _, fns in os.walk(inp):
                for fn in fns:
                    if fn.lower().endswith(".cpt"):
                        rel = os.path.relpath(dp, inp)
                        sub = base if rel == "." else os.path.join(base, rel)
                        pairs.append((os.path.join(dp, fn), sub))
        elif inp.lower().endswith(".cpt") and os.path.isfile(inp):
            pairs.append((inp, ""))
    return sorted(set(pairs))


_DBNAME_RE = re.compile(
    r"<DatabaseName>\s*(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?\s*</DatabaseName>", re.S)


def scan_connections(inputs):
    """扫描所有 .cpt 的帆软数据库连接名(轻量正则,不全量解析),去重排序。"""
    names = set()
    for path, _ in list_cpt(inputs):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except Exception:
            continue
        for m in _DBNAME_RE.findall(text):
            n = (m or "").strip()
            if n:
                names.add(n)
    return sorted(names)


def _normalize_conn_map(conn_map):
    """把 GUI 传来的映射规整成 convert 需要的 {帆软连接名: 数据连接名称}(字符串)。
    运行时按数据连接名称解析数据源(无需 id);兼容旧 {id,name} 格式(取 name);空名称丢弃。"""
    out = {}
    for k, v in (conn_map or {}).items():
        if isinstance(v, dict):                       # 兼容旧格式 {id,name}
            name = (v.get("name") or "").strip()
        else:
            name = (v or "").strip()
        if name:
            out[k] = name
    return out


def run_conversion(inputs, outdir, conn_map=None, overwrite="overwrite",
                   make_zip=False, progress=None, merge_sheets=True):
    """批量转换。

    inputs: 文件/目录列表;outdir: 输出目录;conn_map: {帆软连接名: 数据连接名称};
    overwrite: overwrite|skip|rename;make_zip: 额外打一个可批量导入的 .zip;
    merge_sheets: 多 sheet 的 .cpt 是否合并为单个多页签报表(默认 True;False=每 sheet 拆一张);
    progress: 可选回调 progress(done, total, current_path)。
    返回 dict:{files, reports, ok, failed, skipped, unmapped, zip, results[]}。
    """
    if not outdir:
        raise ValueError("未指定输出目录")
    cfg = json.loads(json.dumps(convert.DEFAULT_CONFIG))
    cfg["connection_map"] = _normalize_conn_map(conn_map)
    cfg["merge_sheets"] = bool(merge_sheets)
    os.makedirs(outdir, exist_ok=True)

    pairs = list_cpt(inputs)
    if not pairs:
        return {"files": 0, "reports": 0, "ok": 0, "failed": 0, "skipped": 0,
                "unmapped": [], "zip": None, "results": []}

    # 未映射连接名(供 UI 提示)
    mapped = set(cfg["connection_map"])
    unmapped = sorted({n for n in scan_connections(inputs) if n not in mapped})

    results = []
    total = len(pairs)
    for i, (fp, sub) in enumerate(pairs, 1):
        try:
            rows = convert.convert_one(fp, outdir, cfg, sub, overwrite=overwrite)
        except Exception as e:                       # 单文件异常不打断整批
            rows = [{"name": os.path.basename(fp), "ok": False,
                     "error": "转换异常:%s" % e}]
        for r in rows:
            r["source"] = fp
        results.extend(rows)
        if progress:
            try:
                progress(i, total, fp)
            except Exception:
                pass

    zip_path = None
    if make_zip:
        import zipfile
        zip_path = os.path.join(outdir, "sight-reports.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for dp, _, fns in os.walk(outdir):
                for fn in fns:
                    if fn.endswith(".mrg"):
                        full = os.path.join(dp, fn)
                        z.write(full, os.path.relpath(full, outdir))

    ok = [r for r in results if r.get("ok") and not r.get("skipped")]
    skipped = [r for r in results if r.get("skipped")]
    failed = [r for r in results if not r.get("ok")]
    # 批量汇总落盘
    if len(results) > 1:
        _write_summary(outdir, results, ok, skipped, failed)
    # 聚合「待人工/降级」问题清单(_issues.csv + _issues.txt),并把汇总回传给 UI
    issues_report = convert.write_issues_report(outdir, results)

    return {"files": total, "reports": len(results), "ok": len(ok),
            "failed": len(failed), "skipped": len(skipped),
            "unmapped": unmapped, "zip": zip_path, "results": results,
            "issues": issues_report}


def _write_summary(outdir, results, ok, skipped, failed):
    lines = ["# 批量转换汇总\n",
             "成功 %d / 跳过 %d / 失败 %d\n" % (len(ok), len(skipped), len(failed)),
             "| 报表 | 单元格 | 待人工 | 降级 | 状态 |", "|---|---|---|---|---|"]
    for r in results:
        if not r.get("ok"):
            lines.append("| %s | - | - | - | ✗ %s |" % (r["name"], r.get("error", "")))
        elif r.get("skipped"):
            lines.append("| %s | - | - | - | ⏭ 跳过(已存在) |" % r["name"])
        else:
            lines.append("| %s | %d | %d | %d | ✓ |"
                         % (r["name"], r["cells"], r["manual"], r["degraded"]))
    with open(os.path.join(outdir, "_summary.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---------------------------------------------------------------------------
# 版本信息 + 在线更新检查
# ---------------------------------------------------------------------------
import version  # noqa: E402  (version.py 在仓库根,已在 sys.path)


def get_version():
    """返回 {version, full}:语义版本号 + 含构建戳的完整串。"""
    return {"version": version.__version__, "full": version.full_version()}


def _semver_tuple(v):
    """'1.2.10-beta+x' → (1,2,10);取前导数字段,遇非数字停止。用于版本比较。"""
    nums = []
    for part in re.split(r"[.\-+]", str(v or "").strip()):
        if part.isdigit():
            nums.append(int(part))
        else:
            break
    return tuple(nums) or (0,)


def _semver_gt(a, b):
    """a 是否比 b 新(语义版本)。"""
    return _semver_tuple(a) > _semver_tuple(b)


def _candidate_update_urls(url=None):
    """更新检查的候选地址(按优先级)。

    - 显式传 url(如 config.json 的 update_check_url):只用它。
    - 否则用 version.UPDATE_CHECK_URLS(主域名优先,备用兜底);兼容老的单值 UPDATE_CHECK_URL。
    """
    if url:
        return [url]
    urls = list(getattr(version, "UPDATE_CHECK_URLS", None) or [])
    if not urls:
        single = getattr(version, "UPDATE_CHECK_URL", "")
        urls = [single] if single else []
    return urls


def check_update(url=None, timeout=4):
    """按顺序请求官网版本清单 JSON,与本地版本比对(主域名优先,失败退备用域名)。

    JSON 约定:{"version": "1.2.0", "url": "下载地址", "notes": "更新说明"}。
    返回:{ok, current, latest, hasUpdate, url, notes, source}(全部地址都失败时
    ok=False+error,UI 静默忽略即可,不打扰用户)。
    """
    import urllib.request
    cur = version.__version__
    last_err = ""
    for src in _candidate_update_urls(url):
        try:
            req = urllib.request.Request(
                src, headers={"User-Agent": "finereport-converter/%s" % cur})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            latest = str(data.get("version") or data.get("latest") or "").strip()
            return {
                "ok": True,
                "current": cur,
                "latest": latest,
                "hasUpdate": bool(latest) and _semver_gt(latest, cur),
                "url": (data.get("url") or data.get("download") or "").strip(),
                "notes": (data.get("notes") or data.get("changelog") or "").strip(),
                "source": src,
            }
        except Exception as e:
            last_err = str(e)
            continue
    return {"ok": False, "current": cur, "hasUpdate": False, "error": last_err}
