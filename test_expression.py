# -*- coding: utf-8 -*-
"""translate_expression 无头自测(不依赖 .cpt/GUI)。

用法: python3 test_expression.py

覆盖:DATEINMONTH/DATEINQUARTER 包裹 TODAY() 在 CONCATENATE / + 拼接场景下必须显式
formatDate(...,"yyyy-MM-dd"),不能直接把 Date 对象扔进 concat()/+(见 function-mapping.md §3.1b)。
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert as C


def check(expr, expected, note=""):
    out, unk = C.translate_expression(expr)
    assert out == expected, (
        "翻译不符预期%s\n  帆软 : %s\n  期望 : %s\n  实得 : %s\n  未映射: %s"
        % (("(" + note + ")" if note else ""), expr, expected, out, unk)
    )
    assert not unk, "不应有未映射函数: %s -> %s (unknown=%s)" % (expr, out, unk)


def main():
    # 真机复现的原始 bug:CONCATENATE(DATEINMONTH(today(),1)," 00:00:00")
    # 曾错译成 concat(monthStart(now())," 00:00:00")(Date.toString 丑陋格式)
    check('CONCATENATE(DATEINMONTH(today(),1)," 00:00:00")',
          'concat( formatDate(monthStart(now()), "yyyy-MM-dd")," 00:00:00")',
          "CONCATENATE 包月初")
    check('CONCATENATE(DATEINMONTH(today(),-1)," 23:59:59")',
          'concat( formatDate(monthEnd(now()), "yyyy-MM-dd")," 23:59:59")',
          "CONCATENATE 包月末")
    check('CONCATENATE(DATEINQUARTER(today(),1)," 00:00:00")',
          'concat( formatDate(quarterStart(now()), "yyyy-MM-dd")," 00:00:00")',
          "CONCATENATE 包季初")

    # + 号拼接场景,同一类坑
    check('DATEINMONTH(today(),1) + " 00:00:00"',
          'formatDate(monthStart(now()), "yyyy-MM-dd") + " 00:00:00"',
          "+ 号右侧字符串字面量")
    check('"起:" + DATEINMONTH(today(),1)',
          '"起:" + formatDate(monthStart(now()), "yyyy-MM-dd")',
          "+ 号左侧字符串字面量")

    # 裸 TODAY() 既有行为不受影响(仍是 date() 纯字符串)
    check('CONCATENATE(TODAY()," 23:59:59")', 'concat(date()," 23:59:59")',
          "裸 TODAY() 既有行为")

    # 日期对象上下文(非字符串拼接)不应被误包 formatDate
    check('DATEINMONTH(today(),1)', 'monthStart(now())', "裸值/日期参数默认值上下文")
    check('DATEDELTA(DATEINMONTH(today(),1), 5)', 'addDays(monthStart(now()), 5)',
          "继续作为日期对象参与日期算术")
    check('IF(A1>0, DATEINMONTH(today(),1), DATEINMONTH(today(),-1))',
          'if(A1>0, monthStart(now()), monthEnd(now()))',
          "IF 分支,非字符串拼接上下文")

    # 多实参 CONCATENATE:仅日期实参被包,其余不受影响
    check('CONCATENATE(A1, DATEINMONTH(today(),1))',
          'concat(A1, formatDate(monthStart(now()), "yyyy-MM-dd"))',
          "多实参,单元格引用不受影响")

    print("全部通过 ✅ (%d 条)" % 10)


if __name__ == "__main__":
    main()
