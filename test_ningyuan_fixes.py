# -*- coding: utf-8 -*-
"""宁远 237 张报表批量体检(2026-10-29)暴露问题的回归自测。

用法: python3 test_ningyuan_fixes.py

覆盖:
  1. 查询面板隐藏控件(WidgetAttr invisible)不渲染,只留参数
  2. 富文本 RichText:不带 XML 缩进换行;${=公式} → 拼接表达式
  3. datasetContent:NoneFunction 不出 aggregateType="none";过滤条件首条带 joinType
  4. 表达式:空实参、TODAY()-DAY(TODAY())、多条件 IF、=("…") 默认值、非法日期默认值
  5. 父格:自引用 / 成环 / 指向空格
  6. 合并区压叠收缩
"""
import os
import re
import sys
import tempfile
from xml.etree import ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert as C

HEAD = """<?xml version="1.0" encoding="UTF-8"?>
<WorkBook xmlVersion="20170720" releaseVersion="10.0.0">
<TableDataMap>
<TableData name="ds1" class="com.fr.data.impl.DBTableData">
<Parameters/>
<Query><![CDATA[select a,b,c from t where d >= '${startTime}' and d <= '${endTime}']]></Query>
<Connection class="com.fr.data.impl.NameDatabaseConnection">
<DatabaseName><![CDATA[demo]]></DatabaseName>
</Connection>
</TableData>
</TableDataMap>
<Report class="com.fr.report.worksheet.WorkSheet" name="sheet1">
<CellElementList>
%s
</CellElementList>
</Report>
<ReportParameterAttr>
<Attributes delayPlaying="false"/>
<Parameters/>
<ParameterUI class="com.fr.form.main.parameter.FormParameterUI">
<Widget class="com.fr.form.ui.container.WParameterLayout">
%s
</Widget>
</ParameterUI>
</ReportParameterAttr>
</WorkBook>
"""

RICH = """<C c="0" r="0" cs="3" s="0">
<O t="RichText">
<RichText>
<RichChar styleIndex="0">
<text>
<![CDATA[统计时间:]]></text>
</RichChar>
<RichChar styleIndex="0">
<text>
<![CDATA[${=$startTime}]]></text>
</RichChar>
<RichChar styleIndex="0">
<text>
<![CDATA[至]]></text>
</RichChar>
<RichChar styleIndex="0">
<text>
<![CDATA[${=$endTime}]]></text>
</RichChar>
</RichText>
</O>
</C>"""

CELLS = RICH + """
<C c="0" r="1" s="0"><O><![CDATA[A]]></O></C>
<C c="1" r="1" s="0"><O><![CDATA[B]]></O></C>
<C c="2" r="1" s="0"><O><![CDATA[C]]></O></C>
<C c="0" r="2" s="0"><O t="DSColumn"><Attributes dsName="ds1" columnName="a"/>
<RG class="com.fr.data.util.function.SummaryGrouper"><FN><![CDATA[com.fr.data.util.function.NoneFunction]]></FN></RG>
</O><Expand dir="0" leftParentDefault="false" left="B3"/></C>
<C c="1" r="2" s="0"><O t="DSColumn"><Attributes dsName="ds1" columnName="b"/>
<Condition class="com.fr.data.condition.CommonCondition"><CNAME><![CDATA[b]]></CNAME>
<Compare op="0"><O><![CDATA[x]]></O></Compare></Condition>
</O><Expand dir="0" leftParentDefault="false" left="A3"/></C>
<C c="2" r="2" s="0"><O t="DSColumn"><Attributes dsName="ds1" columnName="c"/></O>
<Expand dir="0" leftParentDefault="false" left="C3"/></C>
"""


def W(cls, name, x, y, w, extra="", hidden=False, label=""):
    return """<Widget class="com.fr.form.ui.container.WAbsoluteLayout$BoundsWidget">
<InnerWidget class="com.fr.form.ui.%s">
<WidgetName name="%s"/>
<LabelName name="%s"/>
<WidgetAttr invisible="%s" description=""><PrivilegeControl/></WidgetAttr>
%s
</InnerWidget>
<BoundsAttr x="%d" y="%d" width="%d" height="21"/>
</Widget>""" % (cls, name, label, "true" if hidden else "false", extra, x, y, w)


def LBL(text, x, y, w, hidden=False):
    return W("Label", "", x, y, w, "<widgetValue><O><![CDATA[%s]]></O></widgetValue>" % text,
             hidden)


DATE = '<DateAttr format="yyyy-MM-dd HH:mm"/>'
WIDGETS = "\n".join([
    LBL("开始时间:", 10, 10, 70), W("DateEditor", "startTime", 85, 10, 140, DATE),
    LBL("结束时间:", 240, 10, 70), W("DateEditor", "endTime", 315, 10, 140, DATE),
    # 隐藏的辅助控件(真机图1:空框 + 重复的「结束时间」+ 查询按钮被挤到最右)
    LBL("结束时间:", 470, 30, 60, hidden=True),
    W("TextEditor", "czyid", 530, 10, 60, hidden=True,
      extra="<widgetValue><O><![CDATA[007]]></O></widgetValue>"),
    W("DateEditor", "startTime1", 85, 40, 140, '<DateAttr format="yyyy-MM-dd HH:mm:ss"/>'
      '<widgetValue><O t="XMLable" class="com.fr.base.Formula"><Attributes>'
      '<![CDATA[=("2000-00-00 23:59:59")]]></Attributes></O></widgetValue>', label="x"),
    W("FormSubmitButton", "", 480, 10, 60),
])


def convert(cells, widgets):
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "t.cpt")
        open(p, "w", encoding="utf-8").write(HEAD % (cells, widgets))
        out = os.path.join(d, "out")
        rows = C.convert_one(p, out, C.load_config(None))
        assert rows[0]["ok"], rows
        return open(os.path.join(out, "t.mrg"), encoding="utf-8").read(), rows[0]["issues"]


def check_expr(fr, want):
    got, unk = C.translate_expression(fr)
    assert got == want and not unk, "\n  帆软: %s\n  期望: %s\n  实得: %s %s" % (fr, want, got, unk)


def main():
    mrg, issues = convert(CELLS, WIDGETS)
    msgs = " ".join(i["msg"] for i in issues)
    root = ET.fromstring(mrg.encode("utf-8"))

    # 1) 隐藏控件
    assert "czyid" not in re.findall(r'"parameterName":\s*"(\w*)"', mrg), "隐藏输入框不应出组件"
    qf = re.search(r"<queryFormSetting[^>]*><!\[CDATA\[(.*?)\]\]>", mrg, re.S).group(1)
    assert qf.count("结束时间") == 1, "隐藏的「结束时间」标签不应出现"
    assert re.search(r'<parameter[^>]*name="czyid"', mrg), "隐藏控件的参数要保留"
    # 查询按钮应紧跟结束时间(455+12),而不是被隐藏框挤到 600+
    m = re.search(r'"type":\s*"query".*?"x":\s*(\d+)', qf, re.S)
    assert m and int(m.group(1)) < 500, "查询按钮被挤走: %s" % (m and m.group(1))
    # 非法日期默认值清空
    assert "不是合法日期" in msgs
    assert "2000-00-00" not in mrg

    # 2) 富文本
    ec = [e.text for e in root.iter() if e.tag.endswith("expressionContent")]
    want = '"统计时间:" + formatDate($startTime, "yyyy-MM-dd HH:mm:ss") + "至" + ' \
           'formatDate($endTime, "yyyy-MM-dd HH:mm:ss")'
    assert want in ec, ec
    assert "${=" not in mrg

    # 3) datasetContent
    assert 'aggregateType="none"' not in mrg
    for cond in re.findall(r"<condition [^>]*>", mrg):
        assert 'joinType="' in cond, cond

    # 5) 父格:C3 自引用、A3↔B3 成环 → 都要消掉
    lefts = {e.get("name"): e.get("left") for e in root.iter() if e.tag.endswith("cell")}
    assert lefts.get("C3") == "none", lefts
    assert not (lefts.get("A3") == "B3" and lefts.get("B3") == "A3"), lefts

    # 4) 表达式
    check_expr('if($fenlei = 1,"诊间代挂号",)', 'if($fenlei == 1,"诊间代挂号","")')
    check_expr('CONCATENATE(DATEINMONTH(TODAY()-DAY(TODAY()),1)," 00:00:00")',
               'concat( formatDate(monthStart(addDays(now(), -day(now()))), "yyyy-MM-dd")," 00:00:00")')
    check_expr('if(a=1,"x",a=2,"y")', 'if(a==1, "x", if(a==2, "y", ""))')
    check_expr('if(a=1,"x",a=2,"y","z")', 'if(a==1, "x", if(a==2, "y", "z"))')
    check_expr('if(a=1,"x","y")', 'if(a==1,"x","y")')          # 三参不动

    # 6) 合并区压叠:A1 cs=3 盖住 C1(有内容)→ A1 收缩
    over = ('<C c="0" r="0" cs="3" s="0"><O><![CDATA[标题]]></O></C>'
            '<C c="2" r="0" s="0"><O><![CDATA[制表人]]></O></C>'
            '<C c="0" r="1" s="0"><O><![CDATA[x]]></O></C>'
            '<C c="1" r="1" s="0"><O><![CDATA[y]]></O></C>'
            '<C c="2" r="1" s="0"><O><![CDATA[z]]></O></C>')
    mrg2, _ = convert(over, "")
    r2 = ET.fromstring(mrg2.encode("utf-8"))
    cells = {e.get("name"): e for e in r2.iter() if e.tag.endswith("cell")}
    assert cells["C1"].get("visible") == "true", "C1 被合并区吃掉了"
    print("全部通过 ✅ (宁远批量体检回归)")


if __name__ == "__main__":
    main()
