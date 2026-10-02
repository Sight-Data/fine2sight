# -*- coding: utf-8 -*-
"""frm → 仪表盘 的结构自检(不依赖 SightReport 运行时):
  每个 block 恰被引用一次、悬空引用、datasetName 存在(公共数据集除外)、SQL 参数都有声明、嵌套深度≤4、过滤项指向存在的控件。
用法: python3 test_frm_dashboard.py [frm目录]   (默认 ~/mnt/reportlets)"""
import glob
import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert as C
import convert_frm as F


def check_mrs(path):
    errs = []
    root = ET.parse(path).getroot()
    blocks = {b.get("id"): b for b in root.find("blocks")}
    refs = [e.get("ref") for e in root.iter("block") if e.get("ref")]
    for r in set(refs):
        if r not in blocks:
            errs.append("悬空 ref %s" % r)
    for bid in blocks:
        if refs.count(bid) != 1:
            errs.append("区块 %s 被引用 %d 次" % (bid, refs.count(bid)))
    dsn = {d.get("name") for d in root.findall("dataset")}
    declared = {p.get("name") for p in root.findall("parameter")}
    for d in root.findall("dataset"):
        for p in re.findall(r"\$\{\$?(\w+)\}|#\{\$(\w+)", d.findtext("sql") or ""):
            n = p[0] or p[1]
            if n not in declared:
                errs.append("数据集 %s 引用未声明参数 %s" % (d.get("name"), n))
    for bid, b in blocks.items():
        pj = b.findtext("propsJson")
        if pj:
            props = json.loads(pj)
            for k in ("datasetName",):
                if props.get(k) and props[k] not in dsn:
                    errs.append("区块 %s 引用的数据集 %s 不在模板内(应为公共数据集,需手工引用)" % (bid, props[k]))
            sm = (props.get("columnSetting") or {}).get("summary") or {}
            if sm.get("datasetName") and sm["datasetName"] not in dsn:
                errs.append("区块 %s 合计数据集 %s 不存在" % (bid, sm["datasetName"]))
    flds = {d.get("name"): [f.get("name") for f in d.findall("field")] for d in root.findall("dataset")}
    for n, fl in flds.items():
        if len(fl) != len(set(fl)):
            errs.append("数据集 %s 有重复字段 %s" % (n, sorted({x for x in fl if fl.count(x) > 1})))
    for d in root.findall("dataset"):
        q = d.findtext("sql") or ""
        if any(sev == "manual" for sev, _m in C.sql_lint(q)) and "）" not in q:
            errs.append("数据集 %s 的 SQL 括号不配平" % d.get("name"))
    for bid, b in blocks.items():
        pj = b.findtext("propsJson")
        if not pj:
            continue
        props = json.loads(pj)
        dsx = props.get("datasetName")
        if not dsx or not flds.get(dsx):
            continue                                    # 公共数据集/字段运行时由结果集给
        used = [props.get(k) for k in ("dimensionField", "valueField", "compareField", "colorField")]
        used += [m.get("field") for m in props.get("extraMeasures") or []]
        used += list(((props.get("columnSetting") or {}).get("columns") or {}).keys())
        for u in used:
            if u and u not in flds[dsx]:
                errs.append("区块 %s 引用的字段 %s 不在数据集 %s 里" % (bid, u, dsx))
    comps = {c["id"] for c in json.loads(root.findtext("queryFormSetting") or '{"components":[]}')["components"]}
    for it in root.find("filterBar"):
        if it.get("componentId") not in comps:
            errs.append("过滤项指向不存在的控件 %s" % it.get("componentId"))

    def depth(e, d=0):
        m = d
        for c in e:
            if c.tag in ("row", "column", "block", "tabs", "pane"):
                m = max(m, depth(c, d + 1))
        return m
    for tab in root.find("layout").iter("tab"):
        if depth(tab) > 4:
            errs.append("嵌套深度 %d > 4" % depth(tab))
    return errs


def run(frm_dir):
    out = tempfile.mkdtemp()
    cfg = C.load_config(None)
    cfg["_input_root"] = frm_dir
    n = bad = 0
    for f in sorted(glob.glob(os.path.join(frm_dir, "**", "*.frm"), recursive=True)):
        sub = os.path.relpath(os.path.dirname(f), frm_dir)
        sub = "" if sub == "." else sub
        r = F.convert_frm(f, out, cfg, sub)[0]
        assert r["ok"], r
        mrs = os.path.join(out, sub, os.path.splitext(os.path.basename(f))[0] + ".mrs")
        errs = [e for e in check_mrs(mrs) if "公共数据集" not in e]
        n += 1
        if errs:
            bad += 1
            print("✗", os.path.relpath(f, frm_dir), errs[:3])
    print("frm→dashboard 结构自检:%d 个,问题 %d 个" % (n, bad))
    return bad


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/mnt/reportlets")
    sys.exit(1 if run(d) else 0)
