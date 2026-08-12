# -*- coding: utf-8 -*-
"""内容自适应(换行/列宽)相关的无头自测。

用法: python3 test_adjust.py

覆盖三件事:
1. wordWrap 默认必须是 true —— 帆软「页面设置>根据单元格内容自动调整」默认档就是「行高」
   (https://help.fanruan.com/finereport/doc-view-205.html)。转换器长期写死 false(＝「不自动
   调整」那一档),内容超长在帆软里撑高行、转过来却被截断。
2. --wrap-mode none 能回到旧行为。
3. --auto-width 写出 widthMode/maxWidth;不开时一个字都不写(存量模板逐字节不变)。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert as C


MINI_CPT = """<?xml version="1.0" encoding="UTF-8"?>
<WorkBook xmlVersion="20170720" releaseVersion="10.0.0">
<TableDataMap>
<TableData name="ds1" class="com.fr.data.impl.DBTableData">
<Parameters/>
<Query><![CDATA[select dept, diag from t]]></Query>
<Connection class="com.fr.data.impl.NameDatabaseConnection">
<DatabaseName><![CDATA[demo]]></DatabaseName>
</Connection>
</TableData>
</TableDataMap>
<Report class="com.fr.report.worksheet.WorkSheet" name="sheet1">
<ReportPageAttr adjustMode="1"/>
<CellElementList>
<C c="0" r="0" s="0"><O><![CDATA[科室名称]]></O>
<CellGUIAttr adjustmode="2"/></C>
<C c="1" r="0" s="0"><O><![CDATA[主要诊断]]></O></C>
<C c="0" r="1" s="0">
<O class="com.fr.report.cell.cellattr.core.group.DSColumn">
<Attributes dsName="ds1" columnName="dept"/></O>
<Expand dir="0"/></C>
<C c="1" r="1" s="0">
<O class="com.fr.report.cell.cellattr.core.group.DSColumn">
<Attributes dsName="ds1" columnName="diag"/></O>
<Expand dir="0" leftParentDefault="false" left="A2"/></C>
</CellElementList>
<RowHeight defaultValue="723900"><![CDATA[1181100,723900]]></RowHeight>
<ColumnWidth defaultValue="2743200"><![CDATA[2743200,4114800]]></ColumnWidth>
</Report>
</WorkBook>
"""


def _convert(cfg_over=None):
    """把内置样例转一遍,返回 (mrg 文本, 转换报告文本)。"""
    cfg = C.load_config(None)
    cfg.update(cfg_over or {})
    with tempfile.TemporaryDirectory() as d:
        cpt = os.path.join(d, "mini.cpt")
        with open(cpt, "w", encoding="utf-8") as f:
            f.write(MINI_CPT)
        out = os.path.join(d, "out")
        os.makedirs(out, exist_ok=True)
        C.convert_one(cpt, out, cfg, "")
        mrg = rep = ""
        for fn in os.listdir(out):
            p = os.path.join(out, fn)
            if fn.endswith(".mrg"):
                mrg = open(p, encoding="utf-8").read()
            elif fn.endswith(".report.md"):
                rep = open(p, encoding="utf-8").read()
        return mrg, rep


def main():
    n = 0

    # 1. 默认:全部换行(对齐帆软默认档「自动调整行高」),且不写任何自适应列宽属性
    mrg, _ = _convert()
    assert 'wordWrap="true"' in mrg, "默认应换行(帆软默认档=自动调整行高)"
    assert 'wordWrap="false"' not in mrg.replace(
        '<textContent wordWrap="false"><![CDATA[]]>', ""), \
        "默认下除空占位格外不应再有 wordWrap=false"
    n += 1

    assert 'widthMode=' not in mrg, "未开 auto_width 时不得写出 widthMode(存量模板逐字节不变)"
    assert 'maxWidth=' not in mrg, "未开 auto_width 时不得写出 maxWidth"
    n += 1

    # 2. wrap_mode=none 回到旧行为
    mrg_none, _ = _convert({"wrap_mode": "none"})
    assert 'wordWrap="true"' not in mrg_none, "wrap_mode=none 应全部不换行"
    n += 1

    # 3. auto_width 写出属性;带上限时一并写出
    mrg_auto, _ = _convert({"auto_width": True})
    assert mrg_auto.count('widthMode="auto"') == 2, \
        "两列都应标 auto,实得 %d" % mrg_auto.count('widthMode="auto"')
    assert 'maxWidth=' not in mrg_auto, "未给 auto_width_max 时不应写 maxWidth(交引擎推导)"
    n += 1

    mrg_max, _ = _convert({"auto_width": True, "auto_width_max": 120})
    assert 'maxWidth="120"' in mrg_max, "应写出 maxWidth=120,实得:%s" % (
        [l for l in mrg_max.splitlines() if "<col " in l][:1])
    n += 1

    # 4. 取证探针:页面级与单元格级两处 adjust 属性都要出现在转换报告里。
    #    这一条曾经假绿 —— info 级问题既不进 _issues.txt 也不进报告的待人工/降级两节,
    #    探针等于白写,所以报告里专门开了「自适应取证」一节。
    _, rep = _convert()
    assert "自适应取证" in rep, "报告应有自适应取证一节"
    assert "ReportPageAttr" in rep and 'adjustMode="1"' in rep, "应报出页面级 adjust 属性"
    assert "CellGUIAttr" in rep and 'adjustmode="2"' in rep, "应报出单元格级 adjust 属性"
    n += 1

    print("全部通过 ✅ (%d 组)" % n)


if __name__ == "__main__":
    main()
