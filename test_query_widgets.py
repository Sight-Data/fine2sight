# -*- coding: utf-8 -*-
"""查询面板「勾选类」控件的无头自测。

用法: python3 test_query_widgets.py

帆软有三种长得像的控件，转换器必须分开处理：

  · CheckBox      单个布尔勾选。**没有** <Dictionary>，勾选文案在 <Text> 里，
                  值是 <O t="B">true/false。→ magic switch + Boolean 参数。
  · CheckBoxGroup 复选框「组」。有 <Dictionary> 选项，值是数组。→ magic checkbox。
  · RadioGroup    单选框组。有 <Dictionary>，值是标量。→ magic radio。

2026-08-13 真机（住院病人信息查询「包含冲销」）暴露的问题：CheckBox 被和 CheckBoxGroup
一起映射成 checkbox，而 _fill_options 遇到没有 Dictionary 的控件直接 return，于是
props 为空 → 前端 el-checkbox-group 循环空数组 → 界面上渲染出一个什么都看不见的空容器，
且转换报告一条提示都没有。
"""
import json
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert as C


def _panel(widgets_xml, sql):
    return """<?xml version="1.0" encoding="UTF-8"?>
<WorkBook xmlVersion="20170720" releaseVersion="10.0.0">
<TableDataMap>
<TableData name="ds1" class="com.fr.data.impl.DBTableData">
<Parameters/>
<Query><![CDATA[%s]]></Query>
<Connection class="com.fr.data.impl.NameDatabaseConnection">
<DatabaseName><![CDATA[demo]]></DatabaseName>
</Connection>
</TableData>
</TableDataMap>
<Report class="com.fr.report.worksheet.WorkSheet" name="sheet1">
<CellElementList>
<C c="0" r="0" s="0"><O><![CDATA[科室]]></O></C>
<C c="0" r="1" s="0">
<O t="DSColumn"><Attributes dsName="ds1" columnName="dept"/></O>
<Expand dir="0"/></C>
</CellElementList>
</Report>
<ReportParameterAttr>
<Attributes delayPlaying="true"/>
<Parameters/>
<ParameterUI class="com.fr.form.main.parameter.FormParameterUI">
<Widget class="com.fr.form.ui.container.WParameterLayout">
%s
</Widget>
</ParameterUI>
</ReportParameterAttr>
</WorkBook>
""" % (sql, widgets_xml)


# 单个布尔勾选。刻意保留真机上的两个坑：LabelName 是历史残留「不为0:」而真正的文案
# 在 <Text> 里；默认值是 <O t="B">false。
CHECKBOX_SINGLE = """
<Widget class="com.fr.form.ui.container.WAbsoluteLayout$BoundsWidget">
<InnerWidget class="com.fr.form.ui.CheckBox">
<WidgetName name="包含冲销"/>
<LabelName name="不为0:"/>
<Text><![CDATA[包含冲销]]></Text>
<widgetValue><O t="B"><![CDATA[false]]></O></widgetValue>
</InnerWidget>
<BoundsAttr x="600" y="10" width="87" height="28"/>
</Widget>
"""

CHECKBOX_GROUP = """
<Widget class="com.fr.form.ui.container.WAbsoluteLayout$BoundsWidget">
<InnerWidget class="com.fr.form.ui.CheckBoxGroup">
<WidgetName name="病区List"/>
<LabelName name="病区："/>
<Dictionary class="com.fr.data.impl.CustomDictionary">
<CustomDictAttr>
<Dict key="1" value="东区"/>
<Dict key="2" value="西区"/>
</CustomDictAttr>
</Dictionary>
</InnerWidget>
<BoundsAttr x="10" y="10" width="200" height="28"/>
</Widget>
"""

# 复选框组：选项来自数据集字典（TableDataDictionary），且带默认值。
# 默认值是这条用例的重点——它走的是「后端 parse → 前端回显 → SQL 守卫」整条链。
CHECKBOX_GROUP_DS_DEFAULT = """
<Widget class="com.fr.form.ui.container.WAbsoluteLayout$BoundsWidget">
<InnerWidget class="com.fr.form.ui.CheckBoxGroup">
<WidgetName name="病区List"/>
<LabelName name="病区："/>
<Dictionary class="com.fr.data.impl.TableDataDictionary">
<TableDataDictAttr><Name><![CDATA[病区字典]]></Name></TableDataDictAttr>
<FormulaDictAttr kiName="bqid" viName="bqmc"/>
</Dictionary>
<widgetValue><O><![CDATA[1]]></O></widgetValue>
</InnerWidget>
<BoundsAttr x="10" y="10" width="300" height="26"/>
</Widget>
"""

# 多选下拉：和复选框组同为「多值参数」，走同一条 .join 链路
COMBO_CHECKBOX = """
<Widget class="com.fr.form.ui.container.WAbsoluteLayout$BoundsWidget">
<InnerWidget class="com.fr.form.ui.ComboCheckBox">
<WidgetName name="费用类别List"/>
<LabelName name="费用类别："/>
<Dictionary class="com.fr.data.impl.CustomDictionary">
<CustomDictAttr>
<Dict key="1" value="西药"/>
<Dict key="2" value="中药"/>
</CustomDictAttr>
</Dictionary>
<widgetValue><O><![CDATA[1]]></O></widgetValue>
</InnerWidget>
<BoundsAttr x="340" y="10" width="240" height="26"/>
</Widget>
"""

RADIO_GROUP = """
<Widget class="com.fr.form.ui.container.WAbsoluteLayout$BoundsWidget">
<InnerWidget class="com.fr.form.ui.RadioGroup">
<WidgetName name="日期模式"/>
<LabelName name="日期模式："/>
<Dictionary class="com.fr.data.impl.CustomDictionary">
<CustomDictAttr>
<Dict key="b.ruyuanrq" value="入院"/>
<Dict key="b.chuyuanrq" value="出院"/>
</CustomDictAttr>
</Dictionary>
<widgetValue><O><![CDATA[b.ruyuanrq]]></O></widgetValue>
</InnerWidget>
<BoundsAttr x="250" y="10" width="210" height="22"/>
</Widget>
"""

SQL_BOOL = ("select dept from t where 1=1 "
            "${if(包含冲销 == true, \"\", \" and chongxiaobz = 0 \")}")


def _convert(widgets_xml, sql=SQL_BOOL):
    """转一遍，返回 (components 列表, parameters 字典, mrg 全文, 报告全文)。"""
    cfg = C.load_config(None)
    with tempfile.TemporaryDirectory() as d:
        cpt = os.path.join(d, "mini.cpt")
        with open(cpt, "w", encoding="utf-8") as f:
            f.write(_panel(widgets_xml, sql))
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

    m = re.search(r"<queryFormSetting[^>]*><!\[CDATA\[(.*?)\]\]></queryFormSetting>",
                  mrg, re.S)
    comps = json.loads(m.group(1))["components"] if m else []
    params = {pm.group(1): pm.group(0) for pm in
              re.finditer(r'<parameter[^>]*name="([^"]+)"[^>]*/>', mrg)}
    return comps, params, mrg, rep


def _one(comps, ctype):
    got = [c for c in comps if c["type"] == ctype]
    assert len(got) == 1, "期望恰好 1 个 %s 组件，实得 %d 个（全部：%s）" % (
        ctype, len(got), [c["type"] for c in comps])
    return got[0]


def main():
    n = 0

    # ── 1. 单个 CheckBox → switch ──────────────────────────────────────────
    comps, params, mrg, rep = _convert(CHECKBOX_SINGLE)
    sw = _one(comps, "switch")
    assert not [c for c in comps if c["type"] == "checkbox"], \
        "单个 CheckBox 不能落成 checkbox（复选框组）——它没有选项，会渲染成空容器"
    n += 1

    # 文案取 <Text> 而不是 LabelName（LabelName 常是设计器残留，真机上是「不为0:」）
    assert sw["label"] == "包含冲销", "开关文案应取 <Text>，实得 %r" % sw["label"]
    n += 1

    # 参数必须是 Boolean：声明成 String 时后端原样放行 "false"，
    # SQL 里的 $p == true 恒不成立且不报错 → 该筛选条件永远关不掉
    p = params["包含冲销"]
    assert 'datatype="Boolean"' in p, "布尔勾选的参数必须是 Boolean，实得：%s" % p
    assert 'defaultValue="false"' in p, "默认值应保留帆软的 false，实得：%s" % p
    n += 1

    # SQL 侧：布尔比较原样保留，且不能被当成多选参数去 .join
    assert "$包含冲销 == true" in mrg, "布尔比较应原样翻译成 $p == true"
    assert "包含冲销.join" not in mrg, \
        "布尔参数不是 ArrayList，不能生成 .join（String/Boolean 上没有 join 扩展）"
    n += 1

    # 不能静默：转换报告里要留痕（外观由勾选框变成开关）
    assert "开关" in rep, "转换报告应说明单个复选框被转成了开关组件"
    n += 1

    # ── 2. CheckBoxGroup 仍然是 checkbox 且带上选项 ────────────────────────
    comps, params, mrg, rep = _convert(CHECKBOX_GROUP, "select dept from t")
    cb = _one(comps, "checkbox")
    assert cb["props"].get("optionsBindingType") == "custom"
    assert cb["props"].get("customBinding") == [
        {"value": "1", "label": "东区"}, {"value": "2", "label": "西区"}], \
        "复选框组的选项应从 CustomDictionary 取，实得 %r" % cb["props"].get("customBinding")
    # ⚠️多值控件必须是 List：声明成 String 时后端原样放行字符串，SQL 侧的 $p.join("','")
    # 在 String 上恒返 ""（误命中 JDK 静态 String.join）→ 空值守卫恒真 →
    # **整段 IN 条件从 SQL 里消失**，不报错、直接返回全量数据（真机：病区默认值静默失效）。
    assert 'datatype="List"' in params["病区List"], \
        "复选框组必须声明 List，实得：%s" % params["病区List"]
    n += 1

    # ── 3. RadioGroup → radio，选项与默认值都在 ───────────────────────────
    comps, params, mrg, rep = _convert(RADIO_GROUP, "select dept from t")
    rd = _one(comps, "radio")
    assert rd["props"].get("customBinding") == [
        {"value": "b.ruyuanrq", "label": "入院"},
        {"value": "b.chuyuanrq", "label": "出院"}], \
        "单选组选项不对：%r" % rd["props"].get("customBinding")
    assert 'defaultValue="b.ruyuanrq"' in params["日期模式"], \
        "单选组默认值应取 widgetValue，实得：%s" % params["日期模式"]
    n += 1

    # ── 4. 三者共存时不串味 ───────────────────────────────────────────────
    comps, params, mrg, rep = _convert(
        CHECKBOX_SINGLE + CHECKBOX_GROUP + RADIO_GROUP)
    kinds = sorted(c["type"] for c in comps if c["type"] != "text")
    assert kinds == ["checkbox", "radio", "switch"], \
        "三种控件应各成一种组件，实得 %r" % kinds
    n += 1

    # ── 5. 多值参数的默认值：必须声明 List，SQL 侧必须是 .join 守卫 ─────────
    # 真机（住院病人信息查询 / group_demo）实证：声明成 String 时首屏 SQL 里
    # **整段 IN 条件消失**（守卫恒真），报表直接返回全量数据且不报错；
    # 用户手动勾一次后前端提交数组反而正常了，所以线上极难被发现。
    SQL_IN = ('select bqid from t where 1=1 '
              '${if(len(病区List) == 0, "", " and t.bqid in(\'" + 病区List + "\')")}'
              '${if(len(费用类别List) == 0, "", " and t.fylb in(\'" + 费用类别List + "\')")}')
    comps, params, mrg, rep = _convert(
        CHECKBOX_GROUP_DS_DEFAULT + COMBO_CHECKBOX, SQL_IN)

    for pname, ctype in (("病区List", "checkbox"), ("费用类别List", "multiselect")):
        _one(comps, ctype)
        assert 'datatype="List"' in params[pname], \
            "%s（%s）必须声明 List，实得：%s" % (pname, ctype, params[pname])
        assert 'defaultValue="1"' in params[pname], \
            "%s 的默认值应保留，实得：%s" % (pname, params[pname])
        # SQL 侧配套：多值参数在动态 IN 片段里走 .join，才需要 List 撑着
        assert '$%s.join' % pname in mrg, "%s 的 IN 片段应生成 .join" % pname
    n += 1

    # 数据集字典（TableDataDictionary）→ datasetBinding，不是空 props
    cb = _one(comps, "checkbox")
    assert cb["props"].get("optionsBindingType") == "dataset"
    assert cb["props"].get("datasetBinding") == {
        "datasetName": "病区字典", "labelField": "bqmc", "valueField": "bqid"}, \
        "数据集字典应转成 datasetBinding，实得 %r" % cb["props"].get("datasetBinding")
    n += 1

    print("全部通过 ✅ (%d 组)" % n)


if __name__ == "__main__":
    main()
