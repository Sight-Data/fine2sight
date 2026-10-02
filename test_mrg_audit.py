# -*- coding: utf-8 -*-
"""网格报表 .mrg 输出体检(对已转换目录跑):单元格/值映射引用的数据集与字段、SQL 参数声明。
用法: python3 test_mrg_audit.py <输出目录>
公共数据集(假定 SightReport 已有同名数据集)的映射不报;字段名大小写不一致会报。"""
import collections
import glob
import re
import sys
from xml.etree import ElementTree as ET


def audit(d):
    probs = collections.defaultdict(list)
    for f in glob.glob(d + "/**/*.mrg", recursive=True):
        root = ET.parse(f).getroot()
        dss = {x.get("name"): {y.get("name") for y in x.findall("field")} for x in root.iter("dataset")}
        pars = {p.get("name") for p in root.iter("parameter")}
        for e in root.iter():
            tg = e.tag.split("}")[-1]
            if tg == "datasetContent":
                dn, fn = e.get("dataset"), e.get("field")
                if dn not in dss:
                    probs["单元格数据集不存在"].append((f, dn))
                elif dss[dn] and fn not in dss[dn]:
                    probs["单元格字段不在声明里"].append((f, dn, fn))
            elif tg == "facade" and e.get("mappingType") == "dataset" and e.get("dataset") in dss:
                for k in ("labelField", "valueField"):
                    if dss[e.get("dataset")] and e.get(k) not in dss[e.get("dataset")]:
                        probs["映射字段不在声明里"].append((f, e.get("dataset"), e.get(k)))
        for x in root.iter("dataset"):
            sql = x.findtext("{*}sql") or x.findtext("sql") or ""
            for m in re.findall(r"\$\{\$?(\w+)\}|#\{[^}]*?\$(\w+)", sql):
                if (m[0] or m[1]) not in pars:
                    probs["SQL参数未声明"].append((f, x.get("name"), m[0] or m[1]))
    return probs


if __name__ == "__main__":
    p = audit(sys.argv[1] if len(sys.argv) > 1 else "/tmp/o2")
    for k, v in p.items():
        print("✗", k, len(v), v[:3])
    print("体检完成,问题类别 %d 个" % len(p))
    sys.exit(1 if p else 0)
