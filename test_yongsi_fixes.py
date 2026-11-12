# -*- coding: utf-8 -*-
"""永四 1544 张报表批量体检(2026-11-12)暴露问题的回归自测。

用法: python3 test_yongsi_fixes.py

覆盖:
  1. CDATA `]A` 转义还原(xpath(..)[1]A / ARRAY[..]A / 正则 [0-9]A+)
  2. 引号内带参数的字面量:'${d} 23:59:59'、INTERVAL '${n} minutes'、纯 '${日期}'
  3. to_timestamp('${p}','掩码') 不再剥掉(防 $d+1 / $d - interval 类型推断错)
  4. IN 列表:多选 List 参数 join、预格式化列表判定、帆软裸 in ("+p+")
  5. 去引号后与关键字粘连('${a}'and、LIKE'%${k}%')
  6. 值本身是 SQL 片段的参数(c.col ${kaiDanKs})/ ORDER BY 规则收窄 / 数值位参数 CAST
  7. 片段内 LIKE '%"+p+"%' 绑定、注释里的 #{...}
  8. 表达式:$$参数、全角括号、(if(..))、if(..)+x、LEN 与 0 比较、ARRAY/VALUE、DATEINMONTH(YEAR(),1)
  9. 引用被合并单元格覆盖的格 → 改指合并格左上角
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import convert as C


def sql(s, **kw):
    out, unk = C.translate_sql(s, **kw)
    return out


def has(got, *parts):
    for p in parts:
        assert p in got, "\n  缺少: %s\n  实得: %s" % (p, got)


def lacks(got, *parts):
    for p in parts:
        assert p not in got, "\n  不应出现: %s\n  实得: %s" % (p, got)


def check_expr(fr, want):
    got, unk = C.translate_expression(fr)
    assert got == want, "\n  帆软: %s\n  期望: %s\n  实得: %s %s" % (fr, want, got, unk)


DP = {"s", "e"}
DF = {"s": "yyyy-MM-dd", "e": "yyyy-MM-dd HH:mm:ss"}


def main():
    # 1) ]A 转义:全部 ] 都带 A 才还原;混有裸 ] 的文件不动
    raw = "<a><![CDATA[select (xpath('/d[@n=\"x\"]A', c))[1]A::text]]></a>"
    assert C._fr_decode_cdata(raw) == "<a><![CDATA[select (xpath('/d[@n=\"x\"]', c))[1]::text]]></a>"
    mixed = "<a><![CDATA[a[1]A b[2]]]></a>"
    assert C._fr_decode_cdata(mixed) == mixed
    assert C._fr_decode_cdata("<a><![CDATA[x]AA]]></a>") == "<a><![CDATA[x]A]]></a>"

    # 2) 带后缀的字面量 → to_timestamp 内绑表达式 / 其它位置内联字面量
    got = sql("where d between to_timestamp('${s}','yyyy-mm-dd') and "
              "to_timestamp('${e} 23:59:59','yyyy-mm-dd hh24:mi:ss')", date_params=DP, date_fmt=DF)
    has(got, "to_timestamp(${formatDate($s, \"yyyy-MM-dd\")},'yyyy-mm-dd')",
        "to_timestamp(${formatDate($e, \"yyyy-MM-dd\") + ' 23:59:59'},'yyyy-mm-dd hh24:mi:ss')")
    lacks(got, "'$e 23:59:59'")
    got = sql("where to_char(d,'yyyy-MM-dd HH:mm:ss') >= '${s} 00:00:00'", date_params=DP, date_fmt=DF)
    has(got, "'#{formatDate($s, \"yyyy-MM-dd\")} 00:00:00'")
    got = sql("where t <= k + INTERVAL '${n} minutes'")
    has(got, "INTERVAL '#{$n} minutes'")
    # 纯 '${日期}' 内联(兼容 timestamp 列与 to_char 文本两种比较),空值 → null
    got = sql("where to_char(d,'yyyy') between '${s}'and '${e}'", date_params=DP, date_fmt=DF)
    has(got, '#{isEmpty($s) ? "null" : "\'" + formatDate($s, "yyyy-MM-dd") + "\'"} and')
    # 字符串参数进 to_timestamp:保留 to_timestamp,值原样绑定
    got = sql("where d between to_timestamp('${x}','yyyy-MM-dd') and to_timestamp('${y}','yyyy-MM-dd')+1")
    has(got, "to_timestamp(${$x},'yyyy-MM-dd')", "to_timestamp(${$y},'yyyy-MM-dd')+1")

    # 3) 日期参数 + 运算:不再剥掉 to_timestamp
    got = sql("where c between (to_timestamp('${s}', 'yyyy-MM-dd hh24:mi:ss') - interval '24 hour') and x",
              date_params=DP, date_fmt={"s": "yyyy-MM-dd HH:mm:ss"})
    has(got, "(to_timestamp(${formatDate($s, \"yyyy-MM-dd HH:mm:ss\")}, 'yyyy-MM-dd hh24:mi:ss') - interval")

    # 4) IN 列表
    got = sql("where k in (${keshi}) and '门诊' in ('${mz}')", multi_params={"keshi", "mz"},
              prequoted_params={"keshi"})
    has(got, "in (#{isEmpty($keshi) || $keshi.join(\"','\") == '' ? \"null\" : \"'\" + $keshi.join(\"','\") + \"'\"})",
        "$mz.join(")
    got = sql("where j in ('${jiaoYiLx}')")                      # 默认值 1','-1 不是预格式化
    has(got, "\"'\" + $jiaoYiLx + \"'\"")
    got = sql("select 1 ${if(f==0, \"\",\" and y.c in (\"+f+\")\")}")
    has(got, 'in (" + $f + ")')
    lacks(got, "in ('\" + $f")

    # 5) 粘连
    got = sql("where d between '${a}'and '${b}'")
    lacks(got, "$aand")
    has(got, "$a and")
    got = sql("where m LIKE'%${k}%'")
    has(got, "LIKE ${'%' + $k + '%'}")

    # 6) 片段参数 / ORDER BY
    got = sql("where c.bingrenksid ${kaiDanKs} and x = '${y}'")
    has(got, "c.bingrenksid #{$kaiDanKs}")
    got = sql("where a = ${p}", frag_params={"p"})
    has(got, "a = #{$p}")
    got = sql("select * from t order by coalesce(t2.x, to_timestamp('${s}', 'yyyy-MM-dd hh24:mi:ss') - interval '60 day') desc",
              date_params=DP, date_fmt=DF)
    lacks(got, "#{$s}")
    got = sql("select * from t order by a ${dir}")
    has(got, "order by a #{$dir}")
    got = sql("select * from t order by a) x union select * from y where d between '${s}' and '${e}'",
              date_params=DP, date_fmt=DF)
    lacks(got, "#{$s}")

    # 6b) 裸 ${p} 参与算术 / 与数字比较 → CAST(? AS numeric);引号参数在算术位 → 内联
    got = sql("select count(*)*${jixiao} from t where 1 = ${zd} and d - ${s} > 0",
              date_params=DP, date_fmt=DF)
    has(got, "count(*)*CAST(${$jixiao} AS numeric)", "1 = CAST(${$zd} AS numeric)")
    lacks(got, "CAST(${$s}")
    got = sql("select (a - b) - '${t}' > 0 from q")
    has(got, "- #{isEmpty($t) || $t == '' ? \"null\" : \"'\" + $t + \"'\"}")

    # 7) 片段内 LIKE 带 % / 注释里的 #{
    got = sql("select 1 where 1=1 ${if(len(k)==0,\"\",\"a.m LIKE '%\" + k + \"%'\") }")
    has(got, "LIKE ${'%' + $k + '%'}")
    lacks(got, "'%$k%'", "${${")
    got = sql("select 1 -- ${if(len(a)==0,\"\",\"x\")}\nfrom t")
    has(got, "-- # {if(")

    # 8) 表达式
    check_expr('"统计时间:" + $$kaishiriqi', '"统计时间:" + $kaishiriqi')
    check_expr("（F4-G4）", "(F4-G4)")
    check_expr('(if($a=1,"x","y"))', 'if($a==1,"x","y")')
    check_expr('if(a=1,"x","y") + "z"', '((a==1) ? ("x") : ("y")) + "z"')
    check_expr("len($x)=0", "(isEmpty($x) || $x == '')")
    check_expr("if(len($x)>0,1,2)", "if(!(isEmpty($x) || $x == ''),1,2)")
    check_expr('ARRAY("a","b")', '["a", "b"]')
    check_expr('value("院区","yuanQuId")', 'dataset("院区", "yuanQuId")')
    check_expr("DATEINMONTH(YEAR(),1)", "yearStart(now())")
    check_expr("year(today())", "year(now())")
    check_expr('"a" + $b}', '"a" + $b')
    check_expr('count(K4[!0;!0])', 'count(K4[!0])')

    # 9) 合并覆盖格引用
    xml = ('<report><cell xmlns="" row="1" col="1" name="A1" colspan="4" rowspan="1" type="text">'
           '<renderItem><rule><condition itemType="expr" expression="$$value == D1" /></rule></renderItem></cell>'
           '<cell xmlns="" row="1" col="4" name="D1" colspan="0" rowspan="0" type="text"></cell>'
           '<cell xmlns="" row="2" col="1" name="A2" colspan="1" rowspan="1" type="expression">'
           '<expressionContent><![CDATA[C1 + "D1"]]></expressionContent></cell></report>')
    got = C._redirect_covered_refs(xml)
    has(got, 'expression="$$value == A1"', '<![CDATA[A1 + "D1"]]>')

    print("全部通过 ✅ (永四批量体检回归)")


if __name__ == "__main__":
    main()
