#!/usr/bin/env python3
"""convert_frm 的纯单元测试(不依赖真实报表):公式→SQL、列名引用、单元格解析、仪表盘表达式。"""
import sys
import xml.etree.ElementTree as ET
import convert as C
import convert_frm as F


def sql(expr, cell=None):
    cell = cell or (lambda c, r: "t.c%d_%d" % (c, r))
    return F._P(F._tokenize(expr), cell, lambda fn, inner: "%s(%s)" % (fn, inner)).parse()


def main():
    # 小写/大写单元格引用都认,函数名不被当成引用
    assert sql("ROUND(c5/d5,2)") == "round(1.0 * t.c2_4 / nullif(t.c3_4, 0), 2)", sql("ROUND(c5/d5,2)")
    assert sql("round(C5/D5,2)") == sql("ROUND(c5/d5,2)")
    assert sql("sum(D5)") == "sum(t.c3_4)"
    # PROPORTION = 本行 / 列合计
    assert sql("PROPORTION(C4)") == "(t.c2_3) / nullif(sum(t.c2_3) over (), 0)"
    # 列名引用:数字开头加引号
    assert F._qn("ZRS") == "ZRS" and F._qn("2001") == '"2001"' and F._qn('SUM("7")') == '"SUM("7")"'

    # 报表块单元格 → SQL(数据行引用 + 合计行 sum + 比率)
    xml = """<InnerWidget><FormElementCase><CellElementList>
      <C c="0" r="2"><O t="DSColumn"><Attributes dsName="ds1" columnName="YLRS"/></O></C>
      <C c="1" r="2"><O t="DSColumn"><Attributes dsName="ds1" columnName="GRRS"/></O></C>
      <C c="0" r="1"><O t="Formula"><Attributes>=sum(A3)</Attributes></O></C>
      <C c="1" r="1"><O t="Formula"><Attributes>=sum(B3)</Attributes></O></C>
      <C c="2" r="1"><O t="Formula"><Attributes>=B2 / A2</Attributes></O></C>
      <C c="0" r="0"><O>名称</O></C>
    </CellElementList></FormElementCase></InnerWidget>"""
    cm = F._report_cell_map(ET.fromstring(xml))
    assert cm[(0, 0)] == ("t", "名称") and cm[(0, 2)][0] == "ds"
    cellsql, dss, used = F._cell_resolver(cm)
    assert cellsql(2, 1) == "1.0 * sum(t.GRRS) / nullif(sum(t.YLRS), 0)", cellsql(2, 1)
    assert dss == {"ds1"} and ("ds1", "GRRS") in used
    assert cellsql(0, 0) == "'名称'"

    # 查询控件
    assert C.WIDGET_TYPE["TextArea"] == "input"
    print("全部通过 ✅ (frm 单元测试)")


if __name__ == "__main__":
    main()
