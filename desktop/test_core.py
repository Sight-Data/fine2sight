# -*- coding: utf-8 -*-
"""core_api 无头自测(不依赖 pywebview / GUI)。

用法:  python3 test_core.py <含.cpt的文件或目录> [更多...]
没给参数则尝试 ../sample-out 附近的样例;主要在 CI / 沙箱里跑。
"""
import os
import sys
import json
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import core_api


def main(inputs):
    assert inputs, "请传入至少一个 .cpt 文件或目录"
    pairs = core_api.list_cpt(inputs)
    print("list_cpt: 发现 %d 个 .cpt" % len(pairs))
    assert pairs, "未发现 .cpt"

    conns = core_api.scan_connections(inputs)
    print("scan_connections:", conns)

    tmp = tempfile.mkdtemp(prefix="fr_gui_test_")
    try:
        # 1) 首次转换:不映射数据源 → unmapped 应包含发现的连接
        r1 = core_api.run_conversion(inputs, tmp, conn_map={}, overwrite="overwrite")
        print("run#1 overwrite:", {k: r1[k] for k in
              ("files", "reports", "ok", "failed", "skipped")}, "unmapped=", r1["unmapped"])
        assert r1["ok"] >= 1 and r1["failed"] == 0
        assert set(r1["unmapped"]) == set(conns), "未映射连接应等于扫描到的连接"
        n_mrg = sum(1 for dp, _, fns in os.walk(tmp) for f in fns if f.endswith(".mrg"))
        assert n_mrg == r1["ok"], "落盘 .mrg 数应等于成功数"

        # 2) skip:同目录再跑,全部应跳过,不新增文件
        before = _snapshot(tmp)
        r2 = core_api.run_conversion(inputs, tmp, conn_map={}, overwrite="skip")
        print("run#2 skip:", {k: r2[k] for k in ("ok", "skipped", "failed")})
        assert r2["skipped"] == r1["ok"] and r2["ok"] == 0, "skip 应全部跳过"
        assert _snapshot(tmp) == before, "skip 不应改动文件"

        # 3) rename:再跑应生成 _1 副本,文件数增加
        r3 = core_api.run_conversion(inputs, tmp, conn_map={}, overwrite="rename")
        print("run#3 rename:", {k: r3[k] for k in ("ok", "skipped", "failed")})
        assert r3["ok"] == r1["ok"], "rename 应重新生成同样多的报表"
        n_mrg_after = sum(1 for dp, _, fns in os.walk(tmp) for f in fns if f.endswith(".mrg"))
        assert n_mrg_after == n_mrg * 2, "rename 后 .mrg 应翻倍"
        assert any(f.endswith("_1.mrg") for dp, _, fns in os.walk(tmp) for f in fns)

        # 4) 映射数据源:映射值=数据连接名称(字符串),映射后 unmapped 应为空,.mrg 含 dataSourceName(无 dataSourceId)
        if conns:
            cmap = {c: "数据连接_%s" % c for c in conns}
            tmp2 = tempfile.mkdtemp(prefix="fr_gui_test2_")
            try:
                r4 = core_api.run_conversion(inputs, tmp2, conn_map=cmap,
                                             overwrite="overwrite", make_zip=True)
                print("run#4 mapped+zip:", {k: r4[k] for k in ("ok", "failed")},
                      "unmapped=", r4["unmapped"], "zip=", bool(r4["zip"]))
                assert r4["unmapped"] == [], "映射后不应再有未映射连接"
                assert r4["zip"] and os.path.exists(r4["zip"]), "应产出 zip"
                hit = False
                for dp, _, fns in os.walk(tmp2):
                    for f in fns:
                        if f.endswith(".mrg"):
                            txt = open(os.path.join(dp, f), encoding="utf-8").read()
                            if 'dataSourceName="数据连接_' in txt:
                                hit = True
                            assert "dataSourceId=" not in txt, "已去掉 dataSourceId,不应再出现"
                assert hit, ".mrg 应写入映射的 dataSourceName"
            finally:
                shutil.rmtree(tmp2, ignore_errors=True)

        print("\n✅ 全部断言通过")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _snapshot(root):
    # 只比对报表产物(.mrg/.report.md);_summary.md 每次重写属正常,不计入
    return {os.path.relpath(os.path.join(dp, f), root): os.path.getsize(os.path.join(dp, f))
            for dp, _, fns in os.walk(root) for f in fns
            if f.endswith(".mrg") or f.endswith(".report.md")}


if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        cand = os.path.join(os.path.dirname(__file__), "..", "sample-out")
        args = [cand] if os.path.isdir(cand) else []
    main(args)
