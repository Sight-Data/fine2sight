# -*- coding: utf-8 -*-
"""单元格字典 / 超链接 / 数据列过滤 / 内嵌图表 / Year 控件 的回归测试(最小 .cpt 合成)。
运行:python3 test_cell_features.py"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert  # noqa: E402

CPT = '''<?xml version="1.0" encoding="UTF-8"?>
<WorkBook><TableDataMap>
<TableData name="数据" class="com.fr.data.impl.DBTableData"><Parameters/>
<Attributes maxMemRowCount="-1"/><Connection class="com.fr.data.impl.NameDatabaseConnection"><DatabaseName><![CDATA[HIS]]></DatabaseName></Connection>
<Query><![CDATA[select a, b, c from t]]></Query></TableData>
<TableData name="科室字典" class="com.fr.data.impl.DBTableData"><Parameters/>
<Attributes maxMemRowCount="-1"/><Connection class="com.fr.data.impl.NameDatabaseConnection"><DatabaseName><![CDATA[HIS]]></DatabaseName></Connection>
<Query><![CDATA[select KSDM, KSMC from ks]]></Query></TableData>
</TableDataMap>
<Report class="com.fr.report.worksheet.WorkSheet" name="sheet1">
<ReportPageAttr><HR/><FR/><HC/><FC/></ReportPageAttr>
<RowHeight defaultValue="723900"><![CDATA[723900,723900]]></RowHeight>
<ColumnWidth defaultValue="2743200"><![CDATA[2743200,2743200,2743200]]></ColumnWidth>
<CellElementList>
<C c="0" r="0"><O>表头</O><PrivilegeControl/><Expand/></C>
<C c="0" r="1"><O t="DSColumn"><Attributes dsName="数据" columnName="a"/><Condition class="com.fr.data.condition.CommonCondition"><CNAME><![CDATA[b]]></CNAME><Compare op="0"><ColumnRow column="1" row="0"/></Compare></Condition><Complex/><RG class="com.fr.report.cell.cellattr.core.group.FunctionGrouper"/><Parameters/></O>
<Present class="com.fr.base.present.DictPresent"><Dictionary class="com.fr.data.impl.TableDataDictionary"><FormulaDictAttr kiName="KSDM" viName="KSMC"/><TableDataDictAttr><TableData class="com.fr.data.impl.NameTableData"><Name><![CDATA[科室字典]]></Name></TableData></TableDataDictAttr></Dictionary></Present>
<NameJavaScriptGroup><NameJavaScript name="钻取"><JavaScript class="com.fr.js.ReportletHyperlink"><JavaScript class="com.fr.js.ReportletHyperlink"><Parameters><Parameter><Attributes name="k"/><O t="Formula" class="Formula"><Attributes><![CDATA[=a2]]></Attributes></O></Parameter></Parameters><TargetFrame><![CDATA[_dialog]]></TargetFrame><Features width="800" height="600"/><ReportletName extendParameters="true"><![CDATA[/x/目标.cpt&op=view]]></ReportletName></JavaScript></JavaScript></NameJavaScript></NameJavaScriptGroup>
<PrivilegeControl/><Expand dir="0"/></C>
<C c="1" r="1"><O t="DSColumn"><Attributes dsName="数据" columnName="b"/><Complex/><RG class="com.fr.report.cell.cellattr.core.group.FunctionGrouper"/><Parameters/></O>
<Present class="com.fr.base.present.DictPresent"><Dictionary class="com.fr.data.impl.TableDataDictionary"><FormulaDictAttr kiName="X" viName="Y"/><TableDataDictAttr><TableData class="com.fr.data.impl.NameTableData"><Name><![CDATA[服务器字典]]></Name></TableData></TableDataDictAttr></Dictionary></Present>
<PrivilegeControl/><Expand dir="0"/></C>
</CellElementList></Report></WorkBook>'''


def run():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.cpt")
        open(p, "w", encoding="utf-8").write(CPT)
        out = os.path.join(d, "out")
        cfg = convert.load_config(None)
        rows = convert.convert_one(p, out, cfg)
        assert rows[0]["ok"], rows
        mrg = open(os.path.join(out, "t.mrg"), encoding="utf-8").read()
        msgs = " ".join(i["msg"] for i in rows[0]["issues"])
    # 1) 数据集内字典 → 值映射 facade,且字典数据集被输出
    assert re.search(r'<facade type="mapping" mappingType="dataset" dataset="科室字典" '
                     r'labelField="KSMC" valueField="KSDM"', mrg), "值映射缺失"
    assert 'name="科室字典"' in mrg, "字典数据集未输出"
    # 2) 服务器数据集(定义不在模板内)→ 默认假定为同名公共数据集,按名引用且不输出内联数据集
    assert re.search(r'<facade type="mapping" mappingType="dataset" dataset="服务器字典" '
                     r'labelField="Y" valueField="X"', mrg), "公共数据集引用缺失"
    assert '<dataset xmlns="" id=' in mrg and 'name="服务器字典"' not in mrg.split("<row")[0]
    assert "服务器字典" in convert._PUBLIC["refs"]
    # 3) 超链接 → links,参数为表达式,小写 a2 转大写
    assert re.search(r'<links [^>]*type="report"[^>]*fileName="目标"', mrg)
    assert '<parameter name="k" value="A2" isExpression="true" />' in mrg
    assert "钻取链接目标" in msgs
    # 4) 数据列过滤(单元格引用)
    assert re.search(r'<condition itemType="common" leftValue="b" operator="equals" '
                     r'rightValueType="Cell" rightValue="B1"', mrg), re.findall(r"<condition[^>]*>", mrg)
    # 关闭公共数据集假设 → 回到待人工
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.cpt")
        open(p, "w", encoding="utf-8").write(CPT)
        cfg = convert.load_config(None)
        cfg["assume_public_datasets"] = False
        rows = convert.convert_one(p, os.path.join(d, "o"), cfg)
        assert any("服务器数据集" in i["msg"] for i in rows[0]["issues"])
    convert._PUBLIC["on"] = True
    print("全部通过 ✅ (单元格字典/公共数据集/链接/过滤)")


CHILD = CPT.replace("select a, b, c from t", "select x from child where k='${k}'") \
    .replace("<NameJavaScriptGroup>", "<X>").replace("</NameJavaScriptGroup>", "</X>")


def run_embed():
    with tempfile.TemporaryDirectory() as d:
        open(os.path.join(d, "t.cpt"), "w", encoding="utf-8").write(CPT)
        open(os.path.join(d, "目标.cpt"), "w", encoding="utf-8").write(CHILD)
        cfg = convert.load_config(None)
        cfg["_input_root"] = d
        out = os.path.join(d, "out")
        rows = convert.convert_one(os.path.join(d, "t.cpt"), out, cfg)
        assert rows[0]["ok"], rows
        mrg = open(os.path.join(out, "t.mrg"), encoding="utf-8").read()
    assert 'embeddedReportId="emb_1"' in mrg and '<embeddedReport id="emb_1" name="目标">' in mrg
    assert 'name="k"' in mrg and '<parameter xmlns="" id=' in mrg, "链接参数未声明"
    assert "where k=" in mrg, "目标数据集未并入"
    assert 'id="emb_1_row_1"' in mrg
    assert "fileName=" not in mrg.split("<links")[1].split(">")[0]
    print("全部通过 ✅ (钻取内置)")


if __name__ == "__main__":
    run()
    run_embed()
