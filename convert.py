#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
帆软 .cpt 报表 → sight-report 网格报表(.xml)半自动转换器

确定性内核:把帆软 .cpt(明文 XML)的结构/数据绑定/扩展分组/参数/样式
机械映射成 sight-report 网格报表 XML(后端 validateStructure 认的格式)。
公式/条件高亮等无法确定性翻译的部分,降级处理并写进「转换报告」交人工。

帆软一个 .cpt(WorkBook)可含多个工作表(sheet),每个 sheet 是一张独立报表,
本工具按「每个非空 sheet 一张 magic 报表」输出。

用法:
    python3 convert.py <文件或目录> [-o 输出目录] [-c 配置.json]

输出(每个 sheet):
    <名称>[__<sheet>].xml          —— sight-report 网格报表
    <名称>[__<sheet>].report.md    —— 转换报告(降级清单/待人工项)
    _summary.md                    —— 批量汇总(转多张时)

不依赖第三方库,标准库即可运行。
"""
import argparse
import html
import json
import os
import re
import xml.etree.ElementTree as ET

# ----------------------------------------------------------------------------
# 默认配置(可被 -c 配置文件覆盖)
# ----------------------------------------------------------------------------
DEFAULT_CONFIG = {
    # 帆软长度单位:1mm = 144000(全库纸张实证:PaperSize width=30240000→210.0mm=A4宽、
    # 42768000→297.0mm=A3宽;Margin left=2743200→19.1mm 标准页边距)。注意 914400 恰=1英寸EMU
    # 是巧合,帆软并非 EMU(那会把 A4 算成 840mm)。magic 行高/列宽按 pt 渲染(后端 HtmlStyle
    # height:..pt / 前端 ptToPx),1in=72pt=25.4mm → FR→pt 除数 = 144000×25.4/72 = 50800。
    # 实测:默认行 723900→14.25pt(5.0mm)、默认列 2743200→54pt(19mm)、标题行 1181100→23.25pt。
    "length_divisor": 50800,
    # 帆软字号单位 = pt×8(默认宋体 size=72 → 9pt)。magic font-size 也按 pt 渲染。
    # 实测 72→9 / 88→11 / 128→16 均整(除数 6 会得 14.67 等非整,错)。
    "font_size_divisor": 8,
    "font_size_min": 9,
    "font_size_max": 28,
    "default_font_family": "微软雅黑",
    # 智能裁剪完全空的行/列(帆软模板常留大量空列,如制表日期放在第48列把表撑到51列宽)。
    # 按「内容单元格的占用(origin+span)」判定保留,合并跨度因占用列全保留而原样不变;
    # 裁后重映射坐标与单元格名引用(表达式/父格/高亮)。设 false 可关闭。
    "trim_empty": True,
    # 多 sheet 的 .cpt 是否合并为「单个多页签(tab)报表」(sight-report 已支持,见
    # docs/report-tab-设计.md)。True(默认)= 一个 .cpt → 一个含 <sheets> 的 .mrg;
    # False = 每个 sheet 拆一张独立 .mrg(旧行为)。单 sheet 无论如何都走扁平老格式。
    "merge_sheets": True,
    # 单元格内边距(pt,整数)。补一点避免数字贴边/挤在一起。0 关闭。
    "cell_padding": 2,
    # 帆软数据库连接名 → magic 数据源。键=帆软 DatabaseName,值={id,name}
    "connection_map": {},
    # 帆软字体名 → 中文字体名
    "font_name_map": {
        "simhei": "黑体", "simsun": "宋体", "nsimsun": "新宋体",
        "kaiti": "楷体", "fangsong": "仿宋",
        "microsoft yahei": "微软雅黑", "microsoft yahei ui": "微软雅黑",
        "arial": "Arial", "times new roman": "Times New Roman",
    },
}

SUMMARY_FN_MAP = {
    "SumFunction": "sum", "CountFunction": "count", "AverageFunction": "avg",
    "MaxFunction": "max", "MinFunction": "min", "NoneFunction": "none",
}
AGG_NUMERIC = {"sum", "avg", "max", "min", "count", "distinctCount"}

# ----------------------------------------------------------------------------
# 表达式翻译:帆软公式 → MagicScript(sight-report 表达式引擎)
# ----------------------------------------------------------------------------
# 经「参数/语义」逐个核对、确认兼容的帆软函数 → magic 规范名(小写键)。
# 只有进入本表(或下方专项重写)的函数才算「干净」;名字偶然与 magic 相同但
# 语义不同的(如 FIND 参数顺序+基准不同、标准 REPLACE 为按位置替换)一律不放,
# 走「未映射」标红,避免静默产出错误结果。
FR_SAFE = {
    # 聚合(magic 同名,单元格引用按扩展求值;sum/avg/max/min/count 同族)
    "sum": "sum", "avg": "avg", "max": "max", "min": "min", "count": "count",
    # 数学
    "round": "round", "abs": "abs", "ceil": "ceil", "floor": "floor",
    # 逻辑
    "if": "if",
    # 日期分量(参数一致)
    "year": "year", "month": "month", "day": "day",
    "hour": "hour", "minute": "minute", "second": "second", "now": "now",
    "date": "date",
    # 字符串(参数一致:left/right(str,n)、replace(str,old,new) 三参查找替换)
    "upper": "upper", "lower": "lower", "trim": "trim",
    "left": "left", "right": "right", "concat": "concat", "replace": "replace",
    # 报表位置/分页(magic 同名)
    "seq": "seq", "row": "row", "rows": "rows", "column": "column",
    "columns": "columns", "page": "page", "pagecount": "pageCount",
    # 专项重写后会产生的 magic 名,需被接受(避免二次误判)
    "formatnumber": "formatNumber", "formatdate": "formatDate",
    "monthstart": "monthStart", "monthend": "monthEnd",
    "quarterstart": "quarterStart", "quarterend": "quarterEnd",
    "adddays": "addDays", "addmonths": "addMonths", "length": "length",
    "isnull": "isNull",
    # 重写产出的 magic 函数名,放行避免二次误判:.split() 原生方法 / arrayGet 安全取元素 /
    # datasetSelect 数据集筛选取数(后端 sight-report 新增)
    "split": "split", "arrayget": "arrayGet", "datasetselect": "datasetSelect",
}
# 改名类(参数语义一致,仅名字不同)
FR_RENAME = {
    "average": "avg", "concatenate": "concat", "len": "length",
    "datedelta": "addDays", "monthdelta": "addMonths",
    # 帆软 CNMONEY(数)= 人民币大写;magic numberToRMB 同义(StringFunctions 实证)
    "cnmoney": "numberToRMB",
    # 帆软 FIND(子串, 串[, 起始]) = 1-based 位置、未找到=0;magic find(串, 子串)=0-based、未找到=-1。
    # 经 _swap_find_args 已把调用改写成 (find(串, 子串) + 1) 形态(参数对调 + 偏移补 1),
    # 此处仅需让裸名 find 通过白名单(改写后内层就是 magic 原生 find,语义已对齐)。
    "find": "find",
    # 帆软 TRUNC(x[,n]) 向零截断、DATETONUMBER(日期) 转毫秒 → magic 同义函数(后端 sight-platform 新增)
    "trunc": "trunc", "datetonumber": "dateToNumber",
    # 帆软 SUBSTITUTE(原文, 旧子串, 新子串) = 字符串替换;magic replace(str, old, new) 同义
    # (StringFunctions.replace:先按正则替换、失败回落普通替换)。常见用法 SUBSTITUTE(机构代码,",","','")
    # 拼 IN 列表,旧子串为纯文本(无正则元字符)→两端结果一致,可安全归一。
    "substitute": "replace",
}


def _balanced_args(tmp, open_pos):
    """从 tmp[open_pos]=='(' 起拆顶层逗号分隔实参,返回 (args列表, 右括号下一位)。
    字符串此前已暂存为占位符,故顶层逗号即实参分隔(括号内逗号按深度跳过)。"""
    depth, cur, args, j = 0, "", [], open_pos
    while j < len(tmp):
        ch = tmp[j]
        if ch == "(":
            depth += 1
            if depth > 1:
                cur += ch
        elif ch == ")":
            depth -= 1
            if depth == 0:
                args.append(cur)
                return args, j + 1
            cur += ch
        elif ch == "," and depth == 1:
            args.append(cur)
            cur = ""
        else:
            cur += ch
        j += 1
    return None, len(tmp)            # 不平衡


def _expand_switch(tmp):
    """帆软 SWITCH(expr, k1,v1, k2,v2, ...[, default]) → 嵌套三元
    `((expr)==k1 ? v1 : ((expr)==k2 ? v2 : ... : default))`。magic 无 switch,
    动态 SQL 片段/取值都靠它;缺省支(参数个数为偶=纯键值对)用 "" 兜底(SQL 片段里=不加子句)。"""
    for _ in range(6):                # 容纳少量嵌套
        m = re.search(r"(?i)(?<![\w$.])switch\s*\(", tmp)
        if not m:
            break
        args, end = _balanced_args(tmp, m.end() - 1)
        if not args or len(args) < 3:
            # 无法解析:把这个 switch 名暂时改写避免死循环,交白名单标红
            tmp = tmp[:m.start()] + "switch\x07" + tmp[m.end() - 1:]
            continue
        expr = args[0].strip()
        rest = [a.strip() for a in args[1:]]
        default = '""'
        if len(rest) % 2 == 1:        # 奇数:末位为缺省
            default = rest[-1]
            rest = rest[:-1]
        res = default
        for k in range(len(rest) - 2, -1, -2):
            res = "((%s) == %s ? %s : %s)" % (expr, rest[k], rest[k + 1], res)
        tmp = tmp[:m.start()] + res + tmp[end:]
    return tmp.replace("switch\x07", "switch")


def _swap_find_args(tmp):
    """帆软 FIND(needle, hay[, start]) → magic (find(hay, needle) + 1)。
    在「字符串已暂存为占位符」的表达式上做平衡括号拆参,对调首两个顶层实参并 +1 补成
    1-based/未找到=0,使外层 `>0`(找到)/`==0`(未找到)比较与帆软完全一致。
    第三参(起始位)magic 无对应,丢弃(绝大多数为 1=从头找,magic 默认即从头)。"""
    if "find" not in tmp.lower():
        return tmp
    out = []
    i = 0
    while True:
        m = re.search(r"(?i)(?<![\w$.])find\s*\(", tmp[i:])
        if not m:
            out.append(tmp[i:])
            break
        start = i + m.start()
        out.append(tmp[i:start])
        j = i + m.end()          # 紧跟左括号之后
        depth, cur, args = 1, "", []
        while j < len(tmp) and depth > 0:
            ch = tmp[j]
            if ch == "(":
                depth += 1
                cur += ch
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    args.append(cur)
                else:
                    cur += ch
            elif ch == "," and depth == 1:
                args.append(cur)
                cur = ""
            else:
                cur += ch
            j += 1
        if depth == 0 and len(args) >= 2:
            out.append("(find(%s, %s) + 1)" % (args[1].strip(), args[0].strip()))
            i = j
        else:                    # 括号不平衡/参数不足:原样保留,交白名单标红
            out.append(tmp[start:(j if j > start else start + 4)])
            i = j if j > start else start + 4
    return "".join(out)


def _rewrite_array_funcs(tmp):
    """帆软数组函数 → magic(含空值/越界保护):
    SPLIT(s,sep) → (s == null ? "" : s).split(sep)(空串不 NPE);
    INDEXOFARRAY(arr,n) → arrayGet(arr, n-1)(帆软 1-based→0-based,空/越界返回 null,后端安全函数)。
    内层经迭代逐层处理;参数个数不符则占位跳过(交后续白名单标红)。"""
    if "split" not in tmp.lower() and "indexofarray" not in tmp.lower():
        return tmp
    for _ in range(8):
        m = re.search(r"(?i)(?<![\w$.])(SPLIT|INDEXOFARRAY)\s*\(", tmp)
        if not m:
            break
        fn = m.group(1).upper()
        args, end = _balanced_args(tmp, m.end() - 1)
        if not args or len(args) != 2:
            tmp = tmp[:m.start()] + m.group(1) + "\x07" + tmp[m.end() - 1:]
            continue
        a0 = args[0].strip()
        if fn == "SPLIT":
            rep = '(%s == null ? "" : %s).split(%s)' % (a0, a0, args[1].strip())
        else:                                  # INDEXOFARRAY(arr, n) → arrayGet(arr, n-1)
            n = args[1].strip()
            idx = str(int(n) - 1) if re.fullmatch(r"\d+", n) else "(%s) - 1" % n
            rep = "arrayGet(%s, %s)" % (a0, idx)
        tmp = tmp[:m.start()] + rep + tmp[end:]
    return tmp.replace("\x07", "")


def _rewrite_select(tmp):
    """帆软 数据集.select(取值字段, 条件字段 == 条件值) → sum(datasetSelect("ds","取值","条件字段", 条件值))。
    仅支持「字段 == 值」简单等值条件(数据集名/字段为裸标识符);复杂条件/非等值 → 不改,交白名单标红交人工。
    数值上下文里 sum(空列表)=0,空数据集天然安全。"""
    if ".select" not in tmp.lower():
        return tmp
    for _ in range(6):
        m = re.search(r"(?<![\w$])([\w一-鿿]+)\s*\.\s*select\s*\(", tmp)
        if not m:
            break
        ds = m.group(1)
        args, end = _balanced_args(tmp, m.end() - 1)
        ok = False
        if args and len(args) == 2:
            vfield = args[0].strip()
            cond = args[1].strip()
            cm = re.match(r"^([\w一-鿿]+)\s*==\s*(.+)$", cond)   # 条件字段 == 条件值
            if cm and re.fullmatch(r"[\w一-鿿]+", vfield):
                rep = 'sum(datasetSelect("%s", "%s", "%s", %s))' % (
                    ds, vfield, cm.group(1).strip(), cm.group(2).strip())
                tmp = tmp[:m.start()] + rep + tmp[end:]
                ok = True
        if not ok:                              # 无法安全转 → 在 select 内插标记断开匹配(保留括号结构),交标红
            matched = tmp[m.start():m.end()]
            tmp = tmp[:m.start()] + matched.replace("select", "\x07select", 1) + tmp[m.end():]
    return tmp.replace("\x07select", "select")


# 帆软 DATEINMONTH/DATEINQUARTER/DATEDELTA/MONTHDELTA 包 TODAY() 会被上面的规则转成
# monthStart(now())/monthEnd(now())/quarterStart(now())/quarterEnd(now())/addDays(now(),n)/
# addMonths(now(),n)——这些都返回 Date 对象。若整段又恰好是 CONCATENATE(...) 的顶层实参,或
# 紧邻字符串字面量经 + 拼接,拼接会走 Java Date.toString() 默认丑陋格式(concat() 场景)或
# 固定 yyyy-MM-dd HH:mm:ss(+ 号场景,ArithmeticHandle 默认格式),两者都不是帆软原语义的纯
# 日期 yyyy-MM-dd。补 formatDate(expr,"yyyy-MM-dd") 显式转字符串,与 wrap_date_params_in_concat
# (同一坑,来源是参数而非函数调用)同一思路。
# 真机复现:CONCATENATE(DATEINMONTH(today(),1)," 00:00:00") 曾错译成
#          concat(monthStart(now())," 00:00:00")(拼出 Date.toString 丑陋格式,非 yyyy-MM-dd)。
_DATE_RESULT_CALL_RE = re.compile(
    r"(?i)^(?:monthStart|monthEnd|quarterStart|quarterEnd|yearStart|yearEnd|"
    r"addDays|addMonths)\s*\((?:[^()]|\([^()]*\))*\)$|^now\(\)$")
_DATE_RESULT_CALL_INLINE = (
    r"(?:(?:monthStart|monthEnd|quarterStart|quarterEnd|yearStart|yearEnd|"
    r"addDays|addMonths)\s*\((?:[^()]|\([^()]*\))*\)|now\(\))")


def _stringify_date_results_in_concat(tmp):
    """CONCATENATE(...) 顶层实参若整段恰好是上面枚举的「返回 Date 对象」调用,
    包成 formatDate(expr,"yyyy-MM-dd")。仅整段匹配才改写,避免误伤日期算术里的子表达式
    (如 addDays(monthStart(x), 3) 整体仍是合法的单一实参,一样会被整段包裹,结果正确)。"""
    for _ in range(6):
        m = re.search(r"(?i)\bCONCATENATE\s*\(", tmp)
        if not m:
            break
        args, end = _balanced_args(tmp, m.end() - 1)
        if args is None:
            break
        changed = False
        new_args = []
        for a in args:
            s = a.strip()
            if _DATE_RESULT_CALL_RE.match(s):
                new_args.append(' formatDate(%s, "yyyy-MM-dd")' % s)
                changed = True
            else:
                new_args.append(a)
        if changed:
            rep = "CONCATENATE(" + ",".join(new_args) + ")"
            tmp = tmp[:m.start()] + rep + tmp[end:]
        else:
            # 无日期实参需要包裹:插入标记断开 CONCATENATE 与 "(" 的相邻关系,避免死循环重复命中
            # (标记须紧跟在函数名后、"(" 之前,\b 单词边界对标记字符前置不敏感,前置不生效)
            matched = tmp[m.start():m.end()]
            tmp = tmp[:m.start()] + matched.replace("CONCATENATE", "CONCATENATE\x07", 1) + tmp[m.end():]
    return tmp.replace("CONCATENATE\x07", "CONCATENATE")


def _stringify_date_results_near_plus(tmp):
    """<date调用> + <字符串占位符> 或反过来,同上原因需要 formatDate 包裹(+ 号拼接场景)。"""
    tmp = re.sub(r"(?i)(%s)(\s*\+\s*\x00\d+\x00)" % _DATE_RESULT_CALL_INLINE,
                 lambda m: ('formatDate(%s, "yyyy-MM-dd")' % m.group(1)) + m.group(2), tmp)
    tmp = re.sub(r"(?i)(\x00\d+\x00\s*\+\s*)(%s)" % _DATE_RESULT_CALL_INLINE,
                 lambda m: m.group(1) + ('formatDate(%s, "yyyy-MM-dd")' % m.group(2)), tmp)
    return tmp


FR_ACCEPT = {**FR_SAFE, **FR_RENAME}


def translate_expression(expr):
    """帆软表达式 → magic(MagicScript)。返回 (新表达式, 未映射函数名集合)。

    参数级已核对的专项重写在前(TODAY 按上下文、FORMAT 按格式串、ROUNDUP、DATEINMONTH),
    其余按 FR_ACCEPT 白名单做名字归一;不在白名单的函数(含 FIND/VALUE/SWITCH 等
    语义不一致者)计入 unknown 标红。
    """
    if not expr:
        return expr, set()
    # 0) 保护字符串字面量,避免误改其中内容
    strings = []

    def _stash(m):
        strings.append(m.group(0))
        return "\x00%d\x00" % (len(strings) - 1)
    tmp = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", _stash, expr)

    # 0b) 帆软花括号包单元格引用 {J4} / {J4:K5} → magic 裸引用 J4 / J4:K5。
    # 真机实证:高值耗材销毁登记册 J5=`sum({J4})`,magic 解析「期待 identifier 获得 J4」整张报表崩。
    tmp = re.sub(r"\{([A-Z]{1,2}\d+(?::[A-Z]{1,2}\d+)?)\}", r"\1", tmp)

    # 1) 自引用 $$$ → magic 当前单元格值 $$value
    tmp = tmp.replace("$$$", "$$value")
    # 1b) 帆软用单 = 作比较 → magic ==(保留 == >= <= != 不动)
    tmp = re.sub(r"(?<![=<>!])=(?!=)", "==", tmp)

    T = r"(?:TODAY|today)\s*\(\s*\)"  # 帆软 TODAY()
    # 2) 日期函数包裹 TODAY:这些场景 TODAY 需当作「日期对象」→ now()
    tmp = re.sub(r"(?i)\bDATEINMONTH\s*\(\s*%s\s*,\s*-\s*1\s*\)" % T, "monthEnd(now())", tmp)
    tmp = re.sub(r"(?i)\bDATEINMONTH\s*\(\s*%s\s*,\s*1\s*\)" % T, "monthStart(now())", tmp)
    # 首参允许两层嵌套括号(如 addMonths(now(),-1)、today()-day(today())),否则这些复杂首参
    # 的 DATEINMONTH 不被匹配→残留未译函数、用在参数默认里会整张报表加载崩。
    _A = r"((?:[^,()]|\((?:[^()]|\([^()]*\))*\))+?)"
    tmp = re.sub(r"(?i)\bDATEINMONTH\s*\(%s,\s*-\s*1\s*\)" % _A, r"monthEnd(\1)", tmp)
    tmp = re.sub(r"(?i)\bDATEINMONTH\s*\(%s,\s*1\s*\)" % _A, r"monthStart(\1)", tmp)
    # 单参 DATEINMONTH(日期)= 该日期本身(其月内不指定日序号即不改日);magic 无此函数,直接取
    # 内层日期对象。真机实证:国家医保门诊费用结算汇总 startTime/endTime 默认 =DATEINMONTH(today())
    # 未译→「找不到函数 DATEINMONTH(String)」报表参数计算失败、整张报表加载即崩。
    tmp = re.sub(r"(?i)\bDATEINMONTH\s*\(\s*%s\s*\)" % T, "now()", tmp)
    tmp = re.sub(r"(?i)\bDATEINMONTH\s*\(\s*(\$[\w一-鿿]+)\s*\)", r"\1", tmp)
    # 任意第 n 日(n≠±1,如 0/15):第 n 日 = 月初 + (n-1) 天(magic 求值 n-1);负 n(除 -1)罕见近似
    tmp = re.sub(r"(?i)\bDATEINMONTH\s*\(%s,\s*(-?\d+)\s*\)" % _A,
                 r"addDays(monthStart(\1), \2 - 1)", tmp)
    # 季度起止(magic 已加 quarterStart/quarterEnd,2026-06-14):DATEINQUARTER(x,1)→起,(x,-1)→止
    tmp = re.sub(r"(?i)\bDATEINQUARTER\s*\(\s*%s\s*,\s*-\s*1\s*\)" % T, "quarterEnd(now())", tmp)
    tmp = re.sub(r"(?i)\bDATEINQUARTER\s*\(\s*%s\s*,\s*1\s*\)" % T, "quarterStart(now())", tmp)
    tmp = re.sub(r"(?i)\bDATEINQUARTER\s*\(([^,()]+?),\s*-\s*1\s*\)", r"quarterEnd(\1)", tmp)
    tmp = re.sub(r"(?i)\bDATEINQUARTER\s*\(([^,()]+?),\s*1\s*\)", r"quarterStart(\1)", tmp)
    tmp = re.sub(r"(?i)\b(?:DATEDELTA)\s*\(\s*%s\s*,\s*([^,()]+?)\s*\)" % T,
                 r"addDays(now(),\1)", tmp)
    tmp = re.sub(r"(?i)\b(?:MONTHDELTA)\s*\(\s*%s\s*,\s*([^,()]+?)\s*\)" % T,
                 r"addMonths(now(),\1)", tmp)
    # 日期±整数(帆软 date±n = ±n 天)→ addDays
    tmp = re.sub(r"(?i)%s\s*-\s*(\d+)" % T, r"addDays(now(),-\1)", tmp)
    tmp = re.sub(r"(?i)%s\s*\+\s*(\d+)" % T, r"addDays(now(),\1)", tmp)
    # 2b) 上面产出的 monthStart(now())/monthEnd(now())/addDays(now(),n) 等 Date 调用,若整段是
    # CONCATENATE(...) 顶层实参、或紧邻字符串字面量经 + 拼接,需要显式格式化(见函数注释)。
    tmp = _stringify_date_results_in_concat(tmp)
    tmp = _stringify_date_results_near_plus(tmp)
    # 3) 其余 TODAY()(字符串/显示场景)→ 纯日期字符串 date()
    tmp = re.sub(r"(?i)%s" % T, "date()", tmp)

    # 3.5) FIND 参数对调 + 1-based 补偿(详见 _swap_find_args)
    tmp = _swap_find_args(tmp)
    # 3.6) SWITCH → 嵌套三元(magic 无 switch;详见 _expand_switch)
    tmp = _expand_switch(tmp)

    # 4) FORMAT(x, "格式") → 按格式串判定 formatNumber / formatDate
    def _format(m):
        arg, pat = m.group(1), m.group(2)
        body = pat.strip("'\"")
        if re.search(r"[yMdHs]", body) and not re.search(r"[#%]", body):
            return "formatDate(%s, %s)" % (arg, pat)
        return "formatNumber(%s, %s)" % (arg, pat)
    tmp = re.sub(r"(?i)\bFORMAT\s*\((.+?),\s*(\x00\d+\x00)\s*\)", _format, tmp)

    # 5) ROUNDUP(x) 单参 → ceil(x)(带位数的 ROUNDUP(x,d) 不匹配,留作标红)
    tmp = re.sub(r"(?i)\bROUNDUP\s*\(([^,()]+)\)", r"ceil(\1)", tmp)

    # 5.5) 数组函数 SPLIT/INDEXOFARRAY(空值/越界安全)+ 数据集 .select(简单等值) 取数
    tmp = _rewrite_array_funcs(tmp)
    tmp = _rewrite_select(tmp)

    # 6) 通用函数名归一:仅 FR_ACCEPT 内的算干净,其余标红
    unknown = set()

    def _repl(m):
        name, paren = m.group(1), m.group(2)
        low = name.lower()
        if low in FR_ACCEPT:
            return FR_ACCEPT[low] + paren
        unknown.add(name)
        return name + paren
    tmp = re.sub(r"\b([A-Za-z_]\w*)(\s*\()", _repl, tmp)

    # 7) 还原字符串
    out = re.sub(r"\x00(\d+)\x00", lambda m: strings[int(m.group(1))], tmp)
    return out, unknown


# 单元格引用做除数的「除零」防护。
# 帆软 `=A4/B4` 在分母为 0 时只让该格显示 Infinity/错误,**整张报表照常渲染**;magic-script
# 的标量除法(ArithmeticHandle)却直接 throw「除零错误」**令整张报表加载失败**(真机实证:
# 多学科会诊率,空日期段分母为 0)。全库 ~2860 个除法公式格,仅 ~13% 作者手写了 IF 防护
# (其防护值正是 0)。为与帆软「不致命」语义一致,把「单元格引用 / 单元格引用」原子包成
# magic-script 三元:`(B4 == 0 ? 0 : A4 / B4)`。0 即作者们自己的惯例返回值,故属忠实转换。
# 仅作用于「格引用/格引用」原子(聚合 sum()/sum()、null 分母在引擎里本就走容错 divideFallback,
# 不会 throw);链式 A/B/C 仅护到第一段(全库 ~12 例,属残留)。注:此守卫只在「单元格公式」
# 链路调用,不进 SQL/参数链路(SQL 里不会出现 A4/B4 形态的格引用)。
_CELLDIV = re.compile(r"(?<![\w$])([A-Z]{1,2}\d+)\s*/\s*([A-Z]{1,2}\d+)(?![\w])")


def guard_zero_division(expr):
    """把单元格公式里「格引用/格引用」的除法包成除零安全的三元式。"""
    if not expr or "/" not in expr:
        return expr
    # 保护字符串字面量,避免误改其中内容(如 formatNumber(.., "0%"))
    strings = []

    def _stash(m):
        strings.append(m.group(0))
        return "\x00%d\x00" % (len(strings) - 1)
    t = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", _stash, expr)
    t = _CELLDIV.sub(r"(\2 == 0 ? 0 : \1 / \2)", t)
    return re.sub(r"\x00(\d+)\x00", lambda m: strings[int(m.group(1))], t)


def wrap_date_params_in_concat(text, date_fmt):
    """把「与字符串字面量经 + 拼接」的日期参数包成 formatDate($p,"模式")。

    帆软公式 `"统计时段:" + $kaishirq` 里日期参数直接拼串,magic 不自动格式化→
    渲染成 Java Date.toString(`Mon Jun 01 ... CST 2026`)。仅在**字符串拼接上下文**
    (参数紧邻字符串字面量、经 + 连接)才包,避开日期算术 `$d+1`、比较 `$d>x`、SQL、条件。
    date_fmt: {参数名: 模式}。"""
    if not text or not date_fmt:
        return text
    # 暂存字符串字面量为占位符;无字面量=非显示拼接,直接返回
    strings = []

    def _stash(m):
        strings.append(m.group(0))
        return "\x00%d\x00" % (len(strings) - 1)
    t = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", _stash, text)
    if "\x00" not in t:
        return text
    for name, pat in date_fmt.items():
        repl = 'formatDate($%s, "%s")' % (name, pat)
        nm = re.escape(name)
        # 左侧:<字符串占位符> + $name  → 包裹(包裹后 $name 后面是 ',' 不再是 '+',右规则不会重复命中)
        t = re.sub(r'(\x00\d+\x00\s*\+\s*)\$%s\b' % nm,
                   lambda m, r=repl: m.group(1) + r, t)
        # 右侧:$name + <字符串占位符>
        t = re.sub(r'\$%s\b(\s*\+\s*\x00\d+\x00)' % nm,
                   lambda m, r=repl: r + m.group(1), t)
    return re.sub(r"\x00(\d+)\x00", lambda m: strings[int(m.group(1))], t)


# ----------------------------------------------------------------------------
# SQL 参数语法翻译:帆软 → magic(MagicScript SQL 模板)
#
# ⭐关键:magic 的 ${...} 是预编译 ? 绑定(安全),#{...} 是直接拼接(仅用于表/列名片段)。
#   后端预处理会「去注释 + ${}→? 」后做 SQL 注入静态校验:用 ${} 的参数变 ? 永远安全;
#   用 #{} 的参数会在预处理阶段被求值拼进 SQL(空参→ in ()/to_timestamp('') 等非法片段)
#   → 触发注入护栏。因此:
#     · 值参数        帆软 ${param}            → magic ${$param}(预编译;若在引号内则去引号)
#     · LIKE/拼接      帆软 '%${kw}%'           → magic ${'%' + $kw + '%'}(预编译整体值)
#     · 动态 SQL 片段  帆软 ${if(c,"和句A","")}  → magic #{if(c,"和句A","")};片段内 '"+p+"' 也改 ${$p}
#   注:#{} 仅承载「子句结构文本」,所有「参数值」一律走 ${} 预编译,既过护栏又防注入。
# ----------------------------------------------------------------------------
_IDENT = r"[A-Za-z_一-鿿][\w一-鿿]*"
# 列/表标识符值(如 a.记账日期、b.发料日期):帆软「日期类型/字段选择」下拉,值是列引用,
# SQL 里以裸标识符文本内联(${col}::timestamp between …)。magic ${} 是 ? 值绑定,会把
# 'a.记账日期' 当字符串绑定→PG「invalid input syntax for type timestamp」。此类参数须走 #{} 内联。
_COL_IDENT = re.compile(r"^[A-Za-z_一-鿿][\w一-鿿]*\.[A-Za-z_一-鿿][\w一-鿿]*$")
_KEYWORDS = {"true", "false", "null", "and", "or", "not"}
# SQL 子句关键词:出现在字符串字面量里 → 该 ${} 在拼 SQL 片段(应走 #{})
_SQLKW = re.compile(r"(?i)(?:^|\s)(and|or|where|in|between|select|from|join|group|"
                    r"order|having|union|like|exists|on|set)(?:\s|$|\()")


def _prefix_params(expr):
    """给表达式里的「裸标识符(非函数调用、非关键字、字符串外)」加 $(即参数)。"""
    strings = []

    def _stash(m):
        strings.append(m.group(0))
        return "\x00%d\x00" % (len(strings) - 1)
    t = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", _stash, expr)

    def _pre(m):
        name = m.group(1)
        if name.lower() in _KEYWORDS:
            return name
        return "$" + name
    # 完整标识符((?![\w一-鿿]) 防贪婪回溯成部分名)、非成员访问/已加$(前)、非函数调用(后不接 ()
    t = re.sub(r"(?<![\w$.])(%s)(?![\w一-鿿])(?!\s*\()" % _IDENT, _pre, t)
    return re.sub(r"\x00(\d+)\x00", lambda m: strings[int(m.group(1))], t)


def _sql_expr(inner):
    """翻译 ${}/#{} 内表达式:函数映射 + 参数加 $。返回 (文本, 未映射函数集)。"""
    expr, unk = translate_expression(inner)
    return _prefix_params(expr), unk


def translate_sql(sql, ident_params=None, prequoted_params=None, date_params=None,
                  multi_params=None):
    """帆软 SQL → magic SQL。返回 (新SQL, 未映射函数集)。"""
    if not sql:
        return sql, set()
    unknown = set()

    # ⭐帆软源码里 in (${p}) 未加引号 ≠ in ('${p}'):前者参数值本身就是「SQL 列表文本」
    # (如 fenlei 默认值 "1,2",帆软原样内联成 1 in (1,2)),不可再包引号 —— 包了就成
    # 1 in ('1,2') → PG「invalid input syntax for type integer: "1,2"」(真机:医技科室费用
    # 汇总/明细 fenlei)。此处在「引号处理前」按原文记下这类裸 IN 参数,供下面 _in_guard 区分。
    _raw_in = {m.group(1) for m in
               re.finditer(r"(?i)\bin\s*\(\s*\$\{(%s)\}\s*\)" % _IDENT, sql)}

    # 占位符内换行折叠为空格:MagicScript 字符串字面量不能跨行(SQL 对空白不敏感)
    def _collapse(s):
        return re.sub(r"\s+", " ", s).strip()

    def _is_fragment(s):
        """该 ${} 是在拼 SQL 子句(→#{})还是一个值(→${})?字符串字面量含 SQL 关键词即片段"""
        if re.match(r"(?is)\s*(?:if|switch)\b", s):
            return True
        for a, b in re.findall(r"'([^'\\]*)'|\"([^\"\\]*)\"", s):
            if _SQLKW.search(a or b):
                return True
        return False

    def _frag_bind(expr):
        """片段内拼接的参数值 → ${$p} 预编译绑定(A:SQL单引号包裹值; B:裸拼接如 in(...))"""
        expr = re.sub(r"'\"\s*\+\s*(\$[\w一-鿿]+)\s*\+\s*\"'", r"${\1}", expr)
        expr = re.sub(r"(['\"])\s*\+\s*(\$[\w一-鿿]+)\s*\+\s*\1", r"${\2}", expr)
        return expr

    def _repl(m):
        inner = m.group(1).strip()
        if re.fullmatch(_IDENT, inner):                  # 纯参数 → 预编译 ${$name}
            return "${$%s}" % inner
        expr, unk = _sql_expr(inner)
        unknown.update(unk)
        if _is_fragment(inner):                          # 动态 SQL 子句片段 → #{...}
            return "#{%s}" % _collapse(_frag_bind(expr))
        return "${%s}" % _collapse(expr)                 # 值表达式 → 预编译 ${...}
    # ⭐列名/表名位置的参数(如 f.${日期类型} 动态列名、schema.${表})→ 内联 #{$p};列名不可
    # 预编译绑定(f.? 非法 SQL),帆软是文本内联。仅当 ${IDENT} 紧跟 . 后(列/表引用位)才改。
    sql = re.sub(r"(?<=\.)\$\{([\w一-鿿]+)\}", r"#{$\1}", sql)
    out = re.sub(r"\$\{([^}]*)\}", _repl, sql, flags=re.S)
    # 保护 #{} 片段,避免下面的引号处理误改其内部 ${} 绑定
    frags = []
    out = re.sub(r"#\{(?:[^{}]|\$\{[^{}]*\})*\}",
                 lambda m: frags.append(m.group(0)) or "\x02%d\x02" % (len(frags) - 1),
                 out)
    # 预编译占位符不能裹在引号内(否则成 '?' 失去绑定):'${$x}'→${$x};'%${$x}%'→${'%'+$x+'%'}
    _dp = date_params or set()

    def _qfix(m):
        op = m.group(1)
        pre, inner, suf = _collapse(m.group(2)), m.group(3), _collapse(m.group(4))
        # ⭐比较运算符右侧的纯引号参数(col = '${p}'):帆软是文本内联字面量,PG 把 '1' 当 unknown
        # 类型隐式强转;magic 去引号成 ? varchar 预编译绑定后,数值列报 operator does not exist:
        # smallint = character varying(真机:手术室手术情况统计 menzhenzybz='${shoushu}')。还原成
        # 内联字面量 '#{$p}' + 空值守卫(空→= null 不匹配也不崩),数值列('1' 强转 int)/字符串列两宜。
        # ⚠️排除日期参数:其值是 Date 对象,内联 "'"+$p+"'" 会得到 Java Date.toString 非法日期串;
        # 日期参数维持 ? 绑定(对日期列本就正确)。仅纯参数(无前后缀)才改。
        if op and not pre and not suf:
            p = inner.lstrip("$")
            if p not in _dp:
                return ('%s #{isEmpty($%s) || $%s == \'\' ? "null" : "\'" + $%s + "\'"}'
                        % (op, p, p, p))
        # ⚠️ op 是正则「可选前导比较运算符」捕获来的,不属于占位符本身,任何分支都必须原样吐回去。
        # 漏吐会把 `d > '${ks}'` 变成 `d ${$ks}` → `d ?` → SQL 语法错(日期参数走这条分支,
        # 因为上面的内联改写把日期排除了)。
        _op = "%s " % op if op else ""
        if not pre and not suf:
            return "%s${%s}" % (_op, inner)
        parts = (["'%s'" % pre] if pre else []) + [inner] + (["'%s'" % suf] if suf else [])
        return "%s${%s}" % (_op, " + ".join(parts))
    # ⭐前后缀限定为「字面量内文本」(禁空白/括号/逗号/分号等 SQL 结构):被引号包裹的占位符
    # 形如 '${$x}' / '%${$x}%',前后缀只可能是 % _ 之类短字符。若放宽成贪婪负类,会把某字面量的
    # 收尾引号当成开头,跨过 ) as x FROM ... WHERE ${裸参} BETWEEN to_timestamp( 一大段 SQL 匹配到
    # 下一个 '${参}',把中间结构误裹进一个 ${...}→ 产出 '%x%${' 伪影、SQL 崩坏(真机:收入分类统计、
    # 门诊收费工作量统计;后者整段在同一行,故必须按「字面量内容字符集」而非「禁换行」来限定)。
    # 可选前导比较运算符(=、<>、!=、<、>、<=、>=)用于识别「值比较位」的纯引号参数→内联。
    out = re.sub(r"(?:([=<>]=?|<>|!=)\s*)?'([^'$\s();,]*)\$\{(\$?[^}\s]*)\}([^'\s();,]*)'", _qfix, out)
    out = re.sub(r"\x02(\d+)\x02", lambda m: frags[int(m.group(1))], out)
    # 纯参数占位 ${$name} → $name(裸参形态,供下面 to_timestamp 剥离匹配;同时把 #{} 内的
    # ${$p} 简写成 $p——#{} 是 MagicScript,裸参才对)。
    out = re.sub(r"\$\{(\$[\w一-鿿]+)\}", r"\1", out)
    # ⭐多选参数(magic 多选下拉/弹窗→ArrayList)在动态 IN 片段的修复(仅 #{} 片段内):
    #  ① length($p)/len($p)==0 在 ArrayList 上报「找不到函数length(ArrayList)」(真机:入库明细 选多药品)
    #     → isEmpty($p) || $p == ''。⚠️真机实证 isEmpty("") 在该运行时返 false(未选的 String 型
    #     多选参数缺省是空串而非 null/空集),只 isEmpty 会让空参也进 in('') → 数值列报
    #     「invalid input syntax for type smallint: ""」(真机:入出院病人查询)。故须补 == '' 短路。
    #  ② 帆软 in('"+p+"') 转后成插值串 "...in($p)",$p 是 ArrayList → 内联成 [1,2] 非法 SQL。
    #     断开字符串、用 magic-script 集合方法 .join 拼成 'v1','v2':in ('" + $p.join("','") + "')。
    #     空值由守卫短路,不会对空表/空串调 join。
    # ⚠️ .join 只对「真·多选参数」(ComboCheckBox/CheckBoxGroup → ArrayList)成立:
    #    StreamExtension(join 的来源)只注册给 Collection/Object[]/Enumeration/Iterator
    #    (JavaReflection 静态块),String 上没有 join 扩展。单选 ComboBox(→String 参数)
    #    上调 .join 要么找不到方法直接报错,要么误命中 JDK 静态 String.join(sep, 空变参)
    #    恒返 "" → 守卫恒真 → 该筛选条件永远不生效(静默错数据)。真机:医技科室费用汇总
    #    xiangmuid/hesuanxm 均为单选 ComboBox。故按控件类型区分,单选走普通字符串拼接。
    _mp = multi_params or set()

    def _is_multi(pname):
        return pname.lstrip("$") in _mp

    def _empty_guard(mm):
        # ⚠️真机实证(入出院病人查询 在院状态List):未选的多选参数运行时是空集 [] 或含空串的
        # ['']——isEmpty 返 false 且 != '',但 .join 出 "" → in ('') → 数值列 smallint "" 崩。
        # 故守卫改判「join 结果是否为空」:既挡 null/[](isEmpty 短路)又挡 [''](join=="")。
        p = mm.group(1)
        q = chr(39)  # 单引号
        if not _is_multi(p):
            # 单选/文本参数是 String:直接判空串即可(isEmpty 挡 null,== '' 挡空串)
            return "(isEmpty(%s) || %s == %s%s)" % (p, p, q, q)
        return '(isEmpty(%s) || %s.join("%s,%s") == %s%s)' % (p, p, q, q, q, q)

    def _fix_multi_in(mm):
        frag = mm.group(0)
        frag = re.sub(r"(?i)\b(?:length|len)\s*\(\s*(\$[\w一-鿿]+)\s*\)\s*==\s*0",
                      _empty_guard, frag)
        frag = re.sub(r"(?i)\bin\s*\(\s*(\$[\w一-鿿]+)\s*\)",
                      lambda m2: ('''in ('" + %s.join("','") + "')''' % m2.group(1))
                      if _is_multi(m2.group(1))
                      else ('''in ('" + %s + "')''' % m2.group(1)),
                      frag)
        return frag
    out = re.sub(r"#\{(?:[^{}]|\$\{[^{}]*\})*\}", _fix_multi_in, out)
    # 剥掉包在参数外的 to_timestamp/to_date(...,'掩码'):帆软 ${参数} 是文本内联,
    # to_timestamp('2022-10-01 00:00:00','掩码') 能解析;magic 预编译绑定把日期参数当
    # Timestamp 对象传入 → to_timestamp(timestamp,掩码) 函数不存在 → 0 行(真机实证)。
    # 参数本就是日期(或可隐式转),去掉转换函数直接比较 col between $p and $q 即可(PG/Oracle 均可)。
    out = re.sub(
        r"(?i)\bto_(?:timestamp|date)\s*\(\s*(\$[\w一-鿿]+)\s*,\s*'[^']*'\s*\)",
        r"\1", out)
    # 主 SQL 里的裸参 $name 先统一回包成 ${$name}:下面几条规则(列选择型参数、IN 守卫、
    # ORDER BY 内联)都按 ${$name} 形态匹配。全部规则跑完后,再由 _unwrap_simple_params()
    # 把「主 SQL 里剩下的单一参数」还原成裸参 $name(见函数末尾)。
    #   #{} 内的 $p 是 MagicScript 变量、${expr} 值表达式内的 $p 也不能再包→先 stash 起来。
    frags2 = []
    out = re.sub(r"#\{(?:[^{}]|\$\{[^{}]*\})*\}|\$\{[^{}]*\}",
                 lambda m: frags2.append(m.group(0)) or "\x03%d\x03" % (len(frags2) - 1), out)
    out = re.sub(r"(?<![\w$])\$([A-Za-z_一-鿿][\w一-鿿]*)", r"${$\1}", out)
    out = re.sub(r"\x03(\d+)\x03", lambda m: frags2[int(m.group(1))], out)
    # ⭐列选择型参数(值为 a.记账日期 这类列引用)从 ${} 值绑定改 #{} 内联文本:
    # ${$riqigs}::timestamp → #{$riqigs}::timestamp,运行期内联为 a.记账日期::timestamp。
    for _p in (ident_params or ()):
        out = out.replace("${$%s}" % _p, "#{$%s}" % _p)
    # ⭐IN 列表参数:帆软 in ('${p}') 是文本内联字面量;magic ${} 绑定成 ? varchar,
    # 整数列 in (?) 报「operator does not exist: integer = character varying」(PG 不隐式
    # 转 varchar→int;而帆软内联的字面量 '1' 是 unknown 类型会被隐式转)。改 #{} 内联,
    # 并加空值守卫(空→in (null) 不崩;有值→in ('1') 数值列隐式转 int、字符串列也对):
    #   in (#{isEmpty($p) ? "null" : "'" + $p + "'"})
    # 数值列空参 in ('') 会报「invalid input syntax for type smallint: ""」,故必须 null 守卫。
    # 空值守卫须同时挡 null 和空串 ""(真机:isEmpty("") 在该 MagicScript 返 false →
    # in ('') → 数值列报 invalid input syntax for type smallint: "")。
    # 预格式化参数(默认值已自带引号,如 '4734','25301')原样内联,不再包引号(真机:ICU keshi)。
    _pq = prequoted_params or set()

    def _in_guard(m):
        p = m.group(1)
        # 预格式化参数('4734','25301')与「帆软源码里本就没加引号」的列表参数(fenlei="1,2")
        # 都是 SQL 列表文本,原样内联;只有源码写成 in ('${p}') 的单值参数才补引号。
        if p in _pq or p in _raw_in:
            return 'in (#{isEmpty($%s) || $%s == \'\' ? "null" : $%s})' % (p, p, p)
        return 'in (#{isEmpty($%s) || $%s == \'\' ? "null" : "\'" + $%s + "\'"})' % (p, p, p)

    out = re.sub(r"(?i)\bin\s*\(\s*\$\{\$([A-Za-z_一-鿿][\w一-鿿]*)\}\s*\)", _in_guard, out)
    # ⭐ORDER BY 里的参数永远是列名/排序方向(asc/desc),不是值。绑定 ? 在排序方向位非法
    # (真机:国家医保住院医疗费用结算表 `order by col ${$a}` 报 syntax error near "$4")。
    # 把 ORDER BY 子句(到下一个 ) 或语句尾)内的 ${$p} 改 #{$p} 内联;空值→无方向(默认升序)。
    out = re.sub(
        r"(?is)\border\s+by\b[^)]*",
        lambda m: re.sub(r"\$\{\$([A-Za-z_一-鿿][\w一-鿿]*)\}", r"#{$\1}", m.group(0)),
        out)
    return _unwrap_simple_params(out), unknown


def _unwrap_simple_params(sql):
    """${$name} → $name:单一变量不必用 ${} 包装。

    执行期 SqlBuilder.build() 会先去注释、再调 preprocessStandaloneDollarVariables 把独立
    $var 补成 ${$var} 后转 ?,所以裸参与 ${$var} 完全等价,后者只是噪音。
    (历史上转换器坚持回包 ${$name},是为绕开「注释里的撇号让 preprocess 的引号配对错位、
     其后 $var 漏转 → PG syntax error at or near $」——真机:精神疾病统计表。该缺陷已在引擎侧
     根治:build() 改为先去注释再做 $ 预处理,见 SqlBuilder.build 与 SqlBuilderStandaloneDollarTest。)

    只还原「单一变量名」这一种形态:
      · ${'%' + $kw + '%'} 这类表达式必须保留 ${},裸参语法表达不了;
      · #{} 片段是 MagicScript,内部本就用裸参,不参与还原(先 stash 保护)。
    """
    frags = []
    sql = re.sub(r"#\{(?:[^{}]|\$\{[^{}]*\})*\}",
                 lambda m: frags.append(m.group(0)) or "\x04%d\x04" % (len(frags) - 1), sql)
    sql = re.sub(r"\$\{\$([A-Za-z_一-鿿][\w一-鿿]*)\}", r"$\1", sql)
    return re.sub(r"\x04(\d+)\x04", lambda m: frags[int(m.group(1))], sql)


def extract_sql_params(sql):
    """从 SQL 的 ${...} 提取参数名(纯参数 + 表达式里的裸标识符)。"""
    names = set()
    for m in re.finditer(r"\$\{([^}]*)\}", sql or ""):
        inner = m.group(1).strip()
        if re.fullmatch(_IDENT, inner):
            names.add(inner)
            continue
        # 表达式内裸标识符(非函数、非关键字、字符串外)= 参数
        strings = []
        tmp = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"",
                     lambda mm: strings.append(mm.group(0)) or "\x00", inner)
        for im in re.finditer(r"(?<![\w$.])(%s)(?![\w一-鿿])(?!\s*\()" % _IDENT, tmp):
            if im.group(1).lower() not in _KEYWORDS:
                names.add(im.group(1))
    return names


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------
def local(tag):
    return tag.rsplit("}", 1)[-1]


def col_letter(n):
    """1-based 列号 → Excel 列字母(1→A)"""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def fr_color_to_hex(val):
    """帆软 FineColor 的有符号 ARGB 整数 → #RRGGBB;-1 视为缺省(返回 None)"""
    if val is None:
        return None
    try:
        c = int(val)
    except ValueError:
        return None
    if c == -1:
        return None
    return "#%06X" % (c & 0xFFFFFF)


def cdata(text):
    text = "" if text is None else str(text)
    text = text.replace("]]>", "]]]]><![CDATA[>")
    return "<![CDATA[%s]]>" % text


def attr(d):
    out = []
    for k, v in d.items():
        if v is None or v == "":
            continue
        out.append('%s="%s"' % (k, html.escape(str(v), quote=True)))
    return " ".join(out)


def safe_name(s):
    return re.sub(r"[^\w一-鿿（）()-]+", "_", s or "").strip("_") or "sheet"


def cellref(r, c):
    return "%s%d" % (col_letter(c + 1), r + 1)


class Issue:
    def __init__(self, level, where, msg):
        self.level = level   # manual / degraded / info
        self.where = where
        self.msg = msg


# ----------------------------------------------------------------------------
# 帆软 .cpt 解析 → 中间模型(workbook 共享 datasets/styles + 多 sheet)
# ----------------------------------------------------------------------------
def parse_cpt(path):
    tree = ET.parse(path)
    root = tree.getroot()  # WorkBook

    # ---- 样式表(workbook 级,s="N" 引用其第 N 个 Style) ----
    styles = []
    for sl in root.iter():
        if local(sl.tag) == "StyleList":
            for st in sl:
                if local(st.tag) == "Style":
                    styles.append(_parse_style(st))
            break

    # ---- 数据集(workbook 级,DBTableData:SQL + 连接) ----
    datasets = {}
    for td in root.iter():
        if local(td.tag) != "TableData":
            continue
        name = td.get("name")
        if "DBTableData" not in td.get("class", ""):
            continue
        sql, conn, defaults = None, None, {}
        for ch in td:
            lt = local(ch.tag)
            if lt == "Query":
                sql = "".join(ch.itertext()).strip()
            elif lt == "Connection":
                for d in ch:
                    if local(d.tag) == "DatabaseName":
                        conn = (d.text or "").strip()
            elif lt == "Parameters":
                for p in ch:
                    pn = pv = None
                    for pa in p:
                        if local(pa.tag) == "Attributes":
                            pn = pa.get("name")
                        elif local(pa.tag) == "O":
                            pv = (pa.text or "").strip()
                    if pn:
                        defaults[pn] = pv
        if name:
            datasets[name] = {"name": name, "sql": sql, "conn": conn,
                              "fields": {}, "defaults": defaults}

    # ---- 逐工作表(Report)解析 ----
    sheets = []
    for rep in root.iter():
        if local(rep.tag) != "Report":
            continue
        sheet_name = rep.get("name") or ("sheet%d" % (len(sheets) + 1))
        issues, cells = [], {}
        for cel in rep.iter():
            if local(cel.tag) != "CellElementList":
                continue
            for C in cel:
                if local(C.tag) == "C":
                    _parse_cell(C, cells, styles, datasets, issues)
            break
        row_h, col_w = {}, {}
        for el in rep.iter():
            lt = local(el.tag)
            if lt == "RowHeight" and not row_h:
                row_h = _parse_size_list(el)
            elif lt == "ColumnWidth" and not col_w:
                col_w = _parse_size_list(el)
        n_content = sum(1 for c in cells.values() if c["kind"] != "empty")
        sheets.append({"sheet": sheet_name, "cells": cells, "row_h": row_h,
                       "col_w": col_w, "issues": issues, "n_content": n_content})

    query = _parse_query_panel(root, datasets)
    name = os.path.splitext(os.path.basename(path))[0]
    return {"name": name, "datasets": datasets, "styles": styles,
            "sheets": sheets, "query": query}


# 帆软查询控件 → magic 查询组件类型
WIDGET_TYPE = {
    "Label": "text", "DateEditor": "date", "TextEditor": "input",
    "NumberEditor": "number", "ComboBox": "select",
    "ComboCheckBox": "multiselect", "RadioGroup": "radio",
    "CheckBoxGroup": "checkbox", "CheckBox": "checkbox",
    "FormSubmitButton": "query",
}


def _parse_query_panel(root, datasets=None):
    """帆软 ReportParameterAttr → {components, meta(参数类型/默认/必填), delay, issues, ds_used}
    datasets:workbook 级数据集字典,传入则 DatabaseDictionary 可自动合成数据集并接绑定。"""
    rpa = next((e for e in root.iter()
                if local(e.tag) == "ReportParameterAttr"), None)
    if rpa is None:
        return None
    attrs = next((e for e in rpa if local(e.tag) == "Attributes"), None)
    delay = attrs is not None and attrs.get("delayPlaying") == "true"
    meta, issues, ds_used = {}, [], set()
    labels, params = [], []   # 先分别收集「静态标签」与「参数/按钮控件」
    for bw in rpa.iter():
        if local(bw.tag) != "Widget" or "BoundsWidget" not in bw.get("class", ""):
            continue
        inner = next((e for e in bw if local(e.tag) == "InnerWidget"), None)
        bounds = next((e for e in bw if local(e.tag) == "BoundsAttr"), None)
        if inner is None:
            continue
        kind = inner.get("class", "").rsplit(".", 1)[-1]
        mtype = WIDGET_TYPE.get(kind)
        name = _child_attr(inner, "WidgetName", "name") or ""
        label = _child_attr(inner, "LabelName", "name") or ""
        if _has_real_js(inner):
            issues.append(Issue("manual", "查询面板:" + (name or label or kind),
                                "控件含自定义 JS(联动/赋值),已忽略 JS,如需请在设计器重配"))
        if mtype is None:
            if kind == "FreeButton":
                issues.append(Issue("manual", "查询面板",
                                    "FreeButton 自定义按钮(常为重置/自定义动作)未转换,需手工加"))
                continue
            if kind == "TreeComboBoxEditor":
                # 分层数据集树:①可约化为单表自引用→UNION 扁平(eager,零后端);②否则→懒加载 treeLevels
                # (按层取子,需后端 /queryform/tree/children);③都不行→人工。
                tree, lazy = _synth_tree_dataset(inner, name, datasets, ds_used), False
                if tree is None:
                    tree = _synth_tree_lazy(inner, datasets, ds_used)
                    lazy = tree is not None
                if tree is not None:
                    tprops = tree["props"]
                    if _child_text(inner, "allowBlank") == "false":
                        tprops["required"] = True
                    if name:
                        meta[name] = {"datatype": "String", "default": None,
                                      "default_expr": False, "required": tprops.get("required", False)}
                    params.append({"type": "tree-select", "name": name, "label": label,
                                   "pos": _bounds(bounds), "props": tprops})
                    if issues is not None:
                        how = ("懒加载(%d 层,按需取子)" % tree["levels"]) if lazy else \
                              ("UNION 扁平,数据集 %s" % tree["ds"])
                        issues.append(Issue("info", "查询面板:" + (name or label or "树"),
                                            "树形下拉已自动转为「树形选择」(%s),连接映射后即生效" % how))
                else:
                    issues.append(Issue("manual", "查询面板:" + (name or label or kind),
                                        "TreeComboBoxEditor 层级信息不全,无法自动转,需手工加;"
                                        "magic 有「树形选择」组件(数据集 flat / 懒加载两种)"))
                continue
            if kind not in ("FormSubmitButton",):
                issues.append(Issue("manual", "查询面板:" + (name or label or kind),
                                    "查询控件 %s 暂不支持,需手工加" % kind))
            continue
        pos = _bounds(bounds)
        if mtype == "text":
            labels.append({"content": _widget_text(inner) or label, "pos": pos})
            continue
        if mtype == "query":
            params.append({"type": "query", "name": "", "label": "", "pos": pos,
                           "props": {"buttonText": "查询"}})
            continue
        # 跳过隐藏辅助控件:极窄(<35px)文本/数字框几乎都是帆软 JS 驱动的隐藏字段(操作员id/
        # 级联中转),转换后会变成可见小方框搅乱排版。跳过组件、保留参数(走其默认值),并标注。
        if mtype in ("input", "number") and pos["width"] < 35:
            issues.append(Issue("info", "查询面板:" + (name or label or kind),
                                "隐藏辅助控件(宽 %dpx,多为JS驱动)已自动跳过渲染,如需可在设计器补回"
                                % pos["width"]))
            continue
        props = {}
        if _child_text(inner, "allowBlank") == "false":
            props["required"] = True
        if mtype == "date":
            fmt = _child_attr(inner, "DateAttr", "format") or "yyyy-MM-dd"
            props["format"] = fmt
            props["valueFormat"] = fmt
            props["datePickerType"] = ("datetime" if ("HH" in fmt or "hh" in fmt)
                                       else "month" if re.fullmatch(r"yyyy[-/]?MM", fmt)
                                       else "date")
        if mtype in ("select", "multiselect", "radio", "checkbox"):
            _fill_options(inner, {"props": props}, ds_used, issues, name or label, datasets)
        default, is_expr = _widget_default(inner)
        dtype = ("DateTime" if mtype == "date" and "HH" in (props.get("format") or "")
                 else "Date" if mtype == "date"
                 else "Number" if mtype == "number" else "String")
        if name:
            meta[name] = {"datatype": dtype, "default": default,
                          "default_expr": is_expr, "required": props.get("required", False)}
        params.append({"type": mtype, "name": name, "label": label, "pos": pos, "props": props})

    # 关联:把「紧邻在参数控件左侧、同一行」的静态标签并入该控件(避免标签重复 + 修正排版)
    used = set()
    for p in params:
        if p["type"] == "query":
            continue
        py = p["pos"]["y"] + p["pos"]["height"] / 2
        best, gapbest = None, 1e9
        for i, L in enumerate(labels):
            if i in used:
                continue
            ly = L["pos"]["y"] + L["pos"]["height"] / 2
            if abs(ly - py) > 16:               # 同一行
                continue
            gap = p["pos"]["x"] - (L["pos"]["x"] + L["pos"]["width"])
            if -12 <= gap <= 80 and gap < gapbest:   # 标签紧贴在左
                best, gapbest = i, gap
        if best is not None:
            L = labels[best]; used.add(best)
            p["label"] = (L["content"] or p["label"]).strip()  # 用标签文字作组件标签
            right = p["pos"]["x"] + p["pos"]["width"]
            p["pos"] = dict(x=L["pos"]["x"], y=p["pos"]["y"],
                            width=right - L["pos"]["x"], height=p["pos"]["height"])

    # 查询按钮重定位:帆软原位常与相邻控件重叠(标签合并撑宽后更甚)。把每个查询按钮挪到
    # 同行(y相近)最靠右控件之后留固定间距,消除压叠。
    _real = [p for p in params if p["type"] != "query"]
    for p in params:
        if p["type"] == "query" and _real:
            by = p["pos"]["y"] + p["pos"]["height"] / 2
            row = [r for r in _real
                   if abs(r["pos"]["y"] + r["pos"]["height"] / 2 - by) <= 18] or _real
            p["pos"]["x"] = max(r["pos"]["x"] + r["pos"]["width"] for r in row) + 12

    components, cid = [], 0
    for p in params:
        cid += 1
        comp = {"id": "qc_%d" % cid, "type": p["type"], "label": p["label"],
                "parameterName": p["name"], "position": p["pos"], "props": p["props"]}
        if p["type"] not in ("query", "reset") and p["label"]:
            comp["style"] = {"showLabel": True, "labelPosition": "left"}
        components.append(comp)
    for i, L in enumerate(labels):     # 未被并入的标签 → 独立文字组件(多为分区标题)
        if i in used:
            continue
        cid += 1
        components.append({"id": "qc_%d" % cid, "type": "text", "label": "",
                           "parameterName": "", "position": L["pos"],
                           "props": {"content": L["content"]}})

    # ⭐大数据量人员/患者类字典 → 远程搜索下拉(判定口径=名称关键词,用户指定):医生/医师/患者 等
    # 数据集字典候选可达数千~数万条,datasetBinding 会一次性加载全部行→卡。magic 已加 remote 模式
    # (el-select remote + 后端 /report/view/queryform/options/search,服务端按需搜+回显;单选多选通吃)。
    # 故把这类字典从 optionsBindingType=dataset 切到 remote(沿用 datasetBinding 的 datasetName/labelField/
    # valueField,显示值/实际值不变);中小枚举(院区/费用类别/科室/类别)保持 dataset+filterable 一次加载够用。
    _BIG_DICT = ("医生", "医师", "患者", "病人", "职工", "人员", "护士", "医护",
                 "yisheng", "yishi", "huanzhe", "bingren", "zhigong", "renyuan", "hushi",
                 # 药品(药名/药品目录/药品字典等大列表;用具体词避开"药品属性/分类"小枚举:
                 # 裸"yaopin"会命中 药品属性 的参数名 yaopinshuxing,故用 yaopinmc/ypmc)
                 "药品名称", "药品目录", "药品字典", "yaopinmc", "ypmc", "drug")

    def _is_big_person_dict(comp):
        if comp["props"].get("optionsBindingType") != "dataset":
            return False
        db = comp["props"].get("datasetBinding") or {}
        blob = " ".join([comp.get("label") or "", comp.get("parameterName") or "",
                         db.get("datasetName") or "", db.get("labelField") or "",
                         db.get("valueField") or ""]).lower()
        return any(k in blob for k in _BIG_DICT)
    for comp in components:
        if comp["type"] in ("select", "multiselect") and _is_big_person_dict(comp):
            comp["props"]["optionsBindingType"] = "remote"   # datasetBinding 原样保留
            comp["props"]["remotePageSize"] = 20
            if issues is not None:
                title = (comp.get("label") or "下拉").rstrip(":：").strip() or "下拉"
                issues.append(Issue("info", "查询面板:" + title,
                                    "大字典→远程搜索下拉(服务端按需查),输入关键字即搜"))

    # ⭐隐藏辅助输入框清理:帆软把 操作员id/菜单id/中转显示 等隐藏输入框放在参数面板可见区**之下**
    # (y 远低于主控件带)、靠 JS 赋值、用户不可见;magic 渲染整片区域→显示成一排空白输入框。
    # 判定:无标签的 input/number,若 y 明显低于「有标签控件」的最低底边 → 隐藏辅助,跳过(标注)。
    _lab_bottom = max((c["position"]["y"] + c["position"]["height"]
                       for c in components if c["type"] not in ("text", "query", "reset")
                       and (c.get("label") or "").strip()), default=0)
    if _lab_bottom > 0:
        _kept = []
        for c in components:
            if (c["type"] in ("input", "number") and not (c.get("label") or "").strip()
                    and c["position"]["y"] > _lab_bottom + 8):
                if issues is not None:
                    issues.append(Issue("info", "查询面板:" + (c.get("parameterName") or "辅助框"),
                                        "主控件带下方的无标签输入(疑帆软JS隐藏辅助框)已自动跳过渲染"))
                continue
            _kept.append(c)
        components = _kept

    # ⭐radio/checkbox 选项换行修复:magic el-radio/checkbox 比帆软占宽,帆软的紧凑宽度(如163)放不下
    # 多选项→换行(真机:发生日期/计费日期)。把 radio/checkbox 拓宽到「同行右侧最近控件之前」的可用空间
    # (按选项文字估算上限),配合前端 CSS 收窄选项边距即单行容纳。
    for c in components:
        if c["type"] not in ("radio", "checkbox"):
            continue
        opts = c["props"].get("customBinding") or c["props"].get("options") or []
        if not opts:
            continue
        cy = c["position"]["y"] + c["position"]["height"] / 2
        cx = c["position"]["x"]
        rights = [o["position"]["x"] for o in components
                  if o is not c and abs(o["position"]["y"] + o["position"]["height"] / 2 - cy) <= 18
                  and o["position"]["x"] > cx]
        need = sum(len(str(o.get("label") or "")) * 16 + 34 for o in opts) + 16
        avail = (min(rights) - cx - 8) if rights else need
        c["position"]["width"] = int(max(c["position"]["width"], min(need, avail)))

    # 整体上移/左移查询表单,消除帆软面板顶部/左侧留白(保留控件相对布局)。magic 预览用
    # 绝对定位 top:y、容器高=max(y+h);源里控件常放在 y=31 等→表单贴容器底、上方空一段。
    if components:
        PAD = 6
        dx = max(0, min(c["position"]["x"] for c in components) - PAD)
        dy = max(0, min(c["position"]["y"] for c in components) - PAD)
        if dx or dy:
            for c in components:
                c["position"]["x"] -= dx
                c["position"]["y"] -= dy
    # ⭐成对日期 → dateOrder 跨字段校验(magic queryFormSetting.validations,2026-06-14 已支持)。
    # 按名/标签关键词判定开始/结束,按位置排序成对产出「开始≤结束」;开始/结束数不等则不强加
    # (避免给无关日期硬塞约束)。
    _START = ("kaishi", "start", "begin", "qishi", "开始", "起始")
    _END = ("jieshu", "end", "zhongzhi", "结束", "截止", "终止")

    def _date_role(c):
        s = ((c.get("parameterName") or "") + " " + (c.get("label") or "")).lower()
        is_s = any(k in s for k in _START)
        is_e = any(k in s for k in _END)
        return "start" if (is_s and not is_e) else "end" if (is_e and not is_s) else None

    _dates = [c for c in components if c["type"] == "date" and c.get("parameterName")]
    _starts = sorted((c for c in _dates if _date_role(c) == "start"),
                     key=lambda c: c["position"]["x"])
    _ends = sorted((c for c in _dates if _date_role(c) == "end"),
                   key=lambda c: c["position"]["x"])
    validations = []
    if _starts and len(_starts) == len(_ends):
        for s, e in zip(_starts, _ends):
            sl = (s.get("label") or "开始").rstrip(":：").strip() or "开始"
            el = (e.get("label") or "结束").rstrip(":：").strip() or "结束"
            validations.append({"type": "dateOrder", "start": s["parameterName"],
                                "end": e["parameterName"],
                                "message": "%s不能晚于%s" % (sl, el)})

    return {"components": components, "meta": meta, "delay": delay,
            "issues": issues, "ds_used": ds_used, "validations": validations}


def _child_attr(el, tag, attr_name):
    c = next((e for e in el if local(e.tag) == tag), None)
    return c.get(attr_name) if c is not None else None


def _child_text(el, tag):
    c = next((e for e in el if local(e.tag) == tag), None)
    return "".join(c.itertext()).strip() if c is not None else None


def _bounds(b):
    if b is None:
        return {"x": 0, "y": 0, "width": 120, "height": 28}
    return {"x": int(float(b.get("x", 0))), "y": int(float(b.get("y", 0))),
            "width": int(float(b.get("width", 120))),
            "height": int(float(b.get("height", 28)))}


def _has_real_js(inner):
    for lis in inner.iter():
        if local(lis.tag) == "Content":
            t = "".join(lis.itertext()).strip()
            if t and t != "null" and not t.lstrip().startswith("//"):
                return True
    return False


def _widget_text(inner):
    wv = next((e for e in inner if local(e.tag) == "widgetValue"), None)
    if wv is not None:
        return "".join(wv.itertext()).strip()
    return None


def _widget_default(inner):
    """返回 (默认值, 是否表达式)"""
    wv = next((e for e in inner if local(e.tag) == "widgetValue"), None)
    if wv is None:
        return None, False
    o = next((e for e in wv if local(e.tag) == "O"), None)
    if o is None:
        return None, False
    if "Formula" in o.get("class", ""):
        raw = "".join(next((e for e in o if local(e.tag) == "Attributes"), o)
                      .itertext()).strip().lstrip("=").strip()
        return translate_expression(raw)[0], True
    return "".join(o.itertext()).strip(), False


def _sanitize_ds_name(s):
    """生成合法数据集名:保留中英文数字下划线,其余转下划线。"""
    s = re.sub(r"[^0-9A-Za-z_一-鿿]", "_", (s or "").strip())
    return re.sub(r"_+", "_", s).strip("_") or "dict"


def _synth_db_dictionary(dic, name, datasets, ds_used):
    """DatabaseDictionary(直连表字典)→ 自动合成 SELECT DISTINCT 数据集并返回 datasetBinding。
    成功返回 (binding, ds_name, sql, conn);信息不足返回 None,交调用方走手工提示。"""
    if datasets is None:
        return None
    db = next((e for e in dic.iter() if local(e.tag) == "DBDictAttr"), None)
    if db is None:
        return None
    tbl = (db.get("tableName") or "").strip()
    sch = (db.get("schemaName") or "").strip()
    vi = (db.get("viName") or "").strip()          # 显示字段(列名)
    ki = (db.get("kiName") or "").strip() or vi    # 值字段,缺省同显示
    if not tbl or not vi:                           # 没有表或显示字段名→无法建 SQL
        return None
    cn = next((e for e in dic.iter() if local(e.tag) == "DatabaseName"), None)
    conn = ("".join(cn.itertext()).strip() if cn is not None else "") or None
    full = (sch + "." + tbl) if sch else tbl
    cols = vi if ki == vi else "%s, %s" % (vi, ki)
    sql = "SELECT DISTINCT %s FROM %s ORDER BY %s" % (cols, full, vi)
    # 去重:同 SQL+连接已建过则复用
    for dn, d in datasets.items():
        if d.get("_synth") and d.get("sql") == sql and d.get("conn") == conn:
            ds_used.add(dn)
            return ({"datasetName": dn, "labelField": vi, "valueField": ki}, dn, sql, conn)
    base = "dict_" + _sanitize_ds_name(name or vi or tbl)
    dn, i = base, 1
    while dn in datasets:                            # 名称占用→加序号
        i += 1; dn = "%s_%d" % (base, i)
    datasets[dn] = {"name": dn, "sql": sql, "conn": conn,
                    "fields": {vi: "String", ki: "String"} if ki != vi else {vi: "String"},
                    "defaults": {}, "_synth": True}
    ds_used.add(dn)
    return ({"datasetName": dn, "labelField": vi, "valueField": ki}, dn, sql, conn)


def _strip_layer_filter(sql):
    """剥掉帆软层级子查询的 `where <col> = '${layerN}'` 单一过滤,返回 (base_sql, parent_col)。
    仅处理「整个 WHERE 就是这一个参数等值条件」的干净情形;复杂 WHERE(含 AND/OR)返回 (None,None) 回退。"""
    if not sql:
        return None, None
    m = re.search(r"(?is)\bwhere\b\s+([\w.]+)\s*=\s*'?\$\{[^}]+\}'?\s*$", sql)
    if not m:
        return None, None
    return sql[:m.start()].rstrip(), m.group(1).split(".")[-1]


def _synth_tree_dataset(inner, name, datasets, ds_used):
    """帆软 TreeComboBoxEditor(分层数据集树)→ UNION 扁平节点数据集 + tree-select props 片段。
    成功返回 {props, ds, levels};无法干净约化(单表自引用)返回 None,交调用方走人工提示。"""
    if datasets is None:
        return None
    tattr = next((e for e in inner.iter() if local(e.tag) == "TreeAttr"), None)
    multi = tattr is not None and tattr.get("mutiSelect") == "true"
    leaf_only = tattr is not None and tattr.get("selectLeafOnly") == "true"
    levels = []                                    # 逐层 {ds, value(kiName), label(viName)}
    for tn in inner.iter():
        if local(tn.tag) != "TreeNodeAttr":
            continue
        fda = next((e for e in tn.iter() if local(e.tag) == "FormulaDictAttr"), None)
        nm = next((e for e in tn.iter() if local(e.tag) == "Name"), None)
        dsn = "".join(nm.itertext()).strip() if nm is not None else ""
        if fda is None or not dsn:
            return None
        levels.append({"ds": dsn, "value": (fda.get("kiName") or "").strip(),
                       "label": (fda.get("viName") or "").strip()})
    if len(levels) < 2:                            # 单层走普通 select,不算树
        return None
    conn, parts = None, []
    for i, lv in enumerate(levels):
        ds = datasets.get(lv["ds"])
        if ds is None or not ds.get("sql") or not lv["value"] or not lv["label"]:
            return None
        conn = conn or ds.get("conn")
        sql = ds["sql"].strip().rstrip(";")
        if i == 0:
            base, parent_expr = sql, "CAST(NULL AS VARCHAR)"
        else:
            base, pcol = _strip_layer_filter(sql)  # 子层剥父参数过滤 + 取父连接键
            if not base or not pcol:
                return None
            parent_expr = pcol
        parts.append("SELECT DISTINCT %s AS node_id, %s AS parent_id, %s AS node_label FROM (%s) _l%d"
                     % (lv["value"], parent_expr, lv["label"], base, i + 1))
    union_sql = "\nUNION ALL\n".join(parts)
    dsn = None
    for dn, d in datasets.items():                 # 去重同 SQL+连接
        if d.get("_synth") and d.get("sql") == union_sql and d.get("conn") == conn:
            ds_used.add(dn); dsn = dn; break
    if dsn is None:
        base_nm = "tree_" + _sanitize_ds_name(name or levels[-1]["value"])
        dsn, k = base_nm, 1
        while dsn in datasets:
            k += 1; dsn = "%s_%d" % (base_nm, k)
        datasets[dsn] = {"name": dsn, "sql": union_sql, "conn": conn, "_synth": True,
                         "defaults": {}, "fields": {"node_id": "String",
                                                    "parent_id": "String", "node_label": "String"}}
        ds_used.add(dsn)
    return {"ds": dsn, "levels": len(levels), "props": {
        "treeDataSourceType": "dataset",
        "treeDataset": {"datasetName": dsn, "dataStructure": "flat", "idField": "node_id",
                        "parentIdField": "parent_id", "labelField": "node_label", "valueField": "node_id"},
        "treeSelectMode": "multiple" if multi else "single",
        "treeOnlyLeaf": bool(leaf_only), "treeFilterable": True, "treeClearable": True}}


def _synth_tree_lazy(inner, datasets, ds_used):
    """多层数据集树无法约化为单表自引用(多表/复杂层级)→ 懒加载 treeLevels:保留各层数据集(带 ${layerN}
    父参数)+ 标记 treeLazy,运行时由后端 /queryform/tree/children 按层取子。成功返回 {props,levels};否则 None。"""
    if datasets is None:
        return None
    tattr = next((e for e in inner.iter() if local(e.tag) == "TreeAttr"), None)
    multi = tattr is not None and tattr.get("mutiSelect") == "true"
    leaf_only = tattr is not None and tattr.get("selectLeafOnly") == "true"
    tree_levels = []
    nodes = [e for e in inner.iter() if local(e.tag) == "TreeNodeAttr"]
    for i, tn in enumerate(nodes):
        fda = next((e for e in tn.iter() if local(e.tag) == "FormulaDictAttr"), None)
        nm = next((e for e in tn.iter() if local(e.tag) == "Name"), None)
        dsn = "".join(nm.itertext()).strip() if nm is not None else ""
        ds = datasets.get(dsn) if dsn else None
        if fda is None or ds is None or not ds.get("sql"):
            return None
        lvl = {"datasetName": dsn, "labelField": (fda.get("viName") or "").strip(),
               "valueField": (fda.get("kiName") or "").strip()}
        if not lvl["labelField"] or not lvl["valueField"]:
            return None
        if i > 0:                                  # 子层:取 SQL 里父参数名(${layerN})
            m = re.search(r"\$\{(\w+)\}", ds["sql"])
            if not m:
                return None
            lvl["parentParam"] = m.group(1)
        ds_used.add(dsn)                           # 各层数据集需序列化(保留 ${layerN} 参数)
        tree_levels.append(lvl)
    if len(tree_levels) < 2:
        return None
    return {"levels": len(tree_levels), "props": {
        "treeLazy": True, "treeLevels": tree_levels,
        "treeSelectMode": "multiple" if multi else "single",
        "treeOnlyLeaf": bool(leaf_only), "treeFilterable": True, "treeClearable": True}}


def _fill_options(inner, comp, ds_used, issues=None, name="", datasets=None):
    dic = next((e for e in inner if local(e.tag) == "Dictionary"), None)
    if dic is None:
        return
    dcls = dic.get("class", "")
    if "CustomDictionary" in dcls:
        opts = []
        for d in dic.iter():
            if local(d.tag) == "Dict":
                opts.append({"value": d.get("key"), "label": d.get("value")})
        comp["props"]["optionsBindingType"] = "custom"
        # ⭐运行时 select 读 props.customBinding(query-form-component.vue computedOptions),
        # 不是 options;早期写 options 致下拉「无数据」
        comp["props"]["customBinding"] = opts
    elif "TableDataDictionary" in dcls:
        fda = next((e for e in dic.iter()
                    if local(e.tag) == "FormulaDictAttr"), None)
        dsname = None
        for td in dic.iter():
            if local(td.tag) == "Name":
                dsname = "".join(td.itertext()).strip()
                break
        comp["props"]["optionsBindingType"] = "dataset"
        comp["props"]["datasetBinding"] = {
            "datasetName": dsname or "",
            "labelField": (fda.get("viName") if fda is not None else "") or "",
            "valueField": (fda.get("kiName") if fda is not None else "") or ""}
        if dsname:
            ds_used.add(dsname)
    elif "DatabaseDictionary" in dcls:
        # 直连表字典:自动合成「SELECT DISTINCT 显示[,值] FROM 表」数据集并接 datasetBinding,
        # 走既有 conn_map(连接映射一次即生效)+大字典→remote 序列化。无法建 SQL 时退回手工提示。
        syn = _synth_db_dictionary(dic, name, datasets, ds_used)
        if syn is not None:
            binding, dn, sql, conn = syn
            comp["props"]["optionsBindingType"] = "dataset"
            comp["props"]["datasetBinding"] = binding
            if issues is not None:
                issues.append(Issue("info", "查询面板:" + (name or "下拉"),
                                    "字典已自动建数据集 %s(%s)%s,连接映射后下拉即生效" % (
                                        dn, sql, ("(连接 %s)" % conn if conn else ""))))
        elif issues is not None:
            issues.append(Issue("manual", "查询面板:" + (name or "下拉"),
                                "DatabaseDictionary 缺表名/字段名,无法自动建数据集,需手工配置选项"))
    elif dcls and issues is not None:
        # FormulaDictionary(公式字典)等其余长尾:暂不支持自动产出选项,标注避免静默落空。
        issues.append(Issue("manual", "查询面板:" + (name or "下拉"),
                            "字典类型 %s 暂不支持→选项为空,需在设计器手工配置选项或改数据集字典"
                            % dcls.rsplit(".", 1)[-1]))


def _parse_size_list(el):
    txt = "".join(el.itertext()).strip()
    sizes = {}
    for i, tok in enumerate(txt.split(",")) if txt else []:
        tok = tok.strip()
        if tok:
            try:
                sizes[i] = float(tok)
            except ValueError:
                pass
    return sizes


def _parse_style(st):
    style = {"foreColor": None, "backgroundColor": None, "fontFamily": None,
             "fontSize": None, "bold": False, "italic": False, "borders": {},
             "fmt_type": None, "fmt_pattern": None,
             "halign": st.get("horizontal_alignment")}
    for ch in st:
        lt = local(ch.tag)
        if lt == "Format":
            cls = ch.get("class", "").rsplit(".", 1)[-1]
            pat = "".join(ch.itertext()).strip()
            if "DateFormat" in cls:
                style["fmt_type"], style["fmt_pattern"] = "date", pat
            elif "Percent" in cls or (pat and "%" in pat):
                style["fmt_type"], style["fmt_pattern"] = "percent", pat
            elif "Decimal" in cls or "Number" in cls:
                style["fmt_type"], style["fmt_pattern"] = "number", pat
            # TextFormat 等 → 不设格式(纯文本)
        elif lt == "FRFont":
            style["fontFamily"] = ch.get("name")
            sv = ch.get("style")
            if sv and sv.lstrip("-").isdigit():
                style["bold"] = bool(int(sv) & 1)
                style["italic"] = bool(int(sv) & 2)
            sz = ch.get("size")
            if sz and sz.lstrip("-").isdigit():
                style["fontSize"] = int(sz)
            for fg in ch:
                if local(fg.tag) == "foreground":
                    for x in fg.iter():
                        if local(x.tag) == "FineColor":
                            style["foreColor"] = x.get("color")
                            break
        elif lt == "Background":
            if ch.get("name") == "ColorBackground":
                for x in ch.iter():
                    if local(x.tag) == "FineColor":
                        style["backgroundColor"] = x.get("color")
                        break
        elif lt == "Border":
            for side in ch:
                sl = local(side.tag)
                if sl in ("Top", "Bottom", "Left", "Right"):
                    color = None
                    for x in side.iter():
                        if local(x.tag) == "FineColor":
                            color = x.get("color")
                            break
                    style["borders"][sl.lower()] = {
                        "style": side.get("style", "0"), "color": color}
    return style


def _parse_cell(C, cells, styles, datasets, issues):
    r = int(C.get("r", 0))
    c = int(C.get("c", 0))
    cs = int(C.get("cs", 1))
    rs = int(C.get("rs", 1))
    s = C.get("s")
    st = (styles[int(s)] if (s is not None and s.lstrip("-").isdigit()
                             and 0 <= int(s) < len(styles)) else None)
    cell = {"r": r, "c": c, "cs": cs, "rs": rs, "style": st,
            "kind": "empty", "text": "", "dsName": None, "field": None,
            "agg": None, "expand": "none", "left": "default", "top": "default",
            "highlights": []}
    O = Expand = HList = None
    for ch in C:
        lt = local(ch.tag)
        if lt == "O" and O is None:
            O = ch
        elif lt == "Expand":
            Expand = ch
        elif lt == "HighlightList":
            HList = ch
    _parse_cell_content(O, cell, datasets, issues)
    if Expand is not None:
        cell["expand"] = {"0": "down", "1": "right"}.get(Expand.get("dir"), "none")
        # 帆软显式父格(leftParentDefault=false → left;upParentDefault=false → up)
        if Expand.get("leftParentDefault") == "false" and Expand.get("left"):
            cell["left"] = Expand.get("left")
        if Expand.get("upParentDefault") == "false" and Expand.get("up"):
            cell["top"] = Expand.get("up")
    if cell["agg"] in AGG_NUMERIC:
        cell["expand"] = "none"
    if HList is not None:
        _parse_highlights(HList, cell, issues)
    cells[(r, c)] = cell


# 帆软 Compare op 码 → magic 运算符。顺序对齐帆软官方运算符列表(等于/不等于/大于/大于等于/
# 小于/小于等于),并与全库 op 码频次分布(数值类 0-4 高频、字符串类 6+/10/13 低频)互证。
# 仅数值比较(0-5)确定性翻译;字符串类(开头是/包含/在…内 等 op≥6)语义另需引号/IN 不硬猜→标红。
_CMP_OP = {"0": "==", "1": "!=", "2": ">", "3": ">=", "4": "<", "5": "<="}


def _structured_cond_expr(cond):
    """帆软结构化条件 → (magic 表达式, 是否按推定 op 语义)。无法安全翻译返回 None。
    - 空 ListCondition(无子条件)= 帆软「条件属性留空即始终套用」→ ("true", False),确定性、无需抽查。
    - ObjectCondition(本格值 op 字面量,数值 op 0-5)→ ("$$value op 字面量", True),按推定运算符语义。
    - ColumnRow 单元格引用、CommonCondition 跨字段/字段自比、字符串 op、JoinCondition 组合 → None 交人工(不猜)。"""
    cls = cond.get("class", "")
    if "ListCondition" in cls:
        inner = [c for c in cond.iter() if local(c.tag) == "Condition" and c is not cond]
        if not inner:                  # 空 = 无条件 = 恒真(始终套用,常用于把静态样式走条件属性)
            return ("true", False)
        return None                    # 含子条件(JoinCondition 包 CommonCondition)→ 字段自比语义不定,标红
    if "ObjectCondition" not in cls:
        return None
    cmp = next((c for c in cond if local(c.tag) == "Compare"), None)
    if cmp is None:
        return None
    op = _CMP_OP.get(cmp.get("op"))
    if op is None:
        return None
    o = next((c for c in cmp if local(c.tag) == "O"), None)
    if o is None:                      # ColumnRow 单元格引用等非字面量 → 不支持
        return None
    t = (o.get("t") or "").upper()
    val = "".join(o.itertext()).strip()
    if t in ("I", "L", "D", "F", "N") and re.fullmatch(r"-?\d+(\.\d+)?", val or ""):
        lit = val                      # 数值字面量
    elif t == "B":
        lit = "true" if val.lower() in ("true", "1") else "false"
    else:                              # 字符串/其他 → 引号转义
        lit = '"%s"' % (val or "").replace("\\", "\\\\").replace('"', '\\"')
    return ("$$value %s %s" % (op, lit), True)


def _parse_highlights(hlist, cell, issues):
    """帆软 HighlightList → 条件渲染项列表。每项 {name, expr, contents:[...]}。

    FormulaCondition(公式条件)直译;ObjectCondition(本格值 op 字面量,数值 op 0-5)按
    推定运算符语义译并标 info 抽查;其余结构化条件(跨字段/字符串 op/单元格引用/组合)仍标红交人工。
    """
    for h in hlist:
        if local(h.tag) != "Highlight":
            continue
        name = None
        cond_expr = None
        cond_ok = False
        cond_assumed = False           # 结构化条件按推定 op 语义译 → 标 info 抽查
        contents = []
        for ch in h:
            lt = local(ch.tag)
            if lt == "Name":
                name = "".join(ch.itertext()).strip()
            elif lt == "Condition":
                if "FormulaCondition" in ch.get("class", ""):
                    f = next(("".join(x.itertext()) for x in ch
                              if local(x.tag) == "Formula"), None)
                    if f:
                        cond_expr, unk = translate_expression(f.strip())
                        cond_ok = not unk
                else:
                    se = _structured_cond_expr(ch)
                    if se:
                        cond_expr, cond_ok, cond_assumed = se[0], True, se[1]
            elif lt == "HighlightAction":
                cont = _parse_hl_action(ch)
                if cont:
                    contents.append(cont)
        if cond_ok and cond_expr and contents:
            cell["highlights"].append({"name": name or "条件", "expr": cond_expr,
                                       "contents": contents})
            if cond_assumed and issues is not None:
                issues.append(Issue("info", cellref(cell["r"], cell["c"]),
                                    "条件高亮「%s」已按推定运算符语义(=/≠/>/≥/</≤)自动转换,建议抽查颜色方向"
                                    % (name or "")))
        else:
            issues.append(Issue("manual", cellref(cell["r"], cell["c"]),
                                "条件高亮「%s」未转换(结构化条件/不支持的样式,需手工配)"
                                % (name or "")))


def _hl_scope(action):
    """帆软 HighlightAction 的 <Scope val=N/> → magic scope(0/缺省=cell,1=row,2=column)"""
    sc = next((x for x in action if local(x.tag) == "Scope"), None)
    return {"1": "row", "2": "column"}.get(sc.get("val") if sc is not None else None,
                                           "cell")


def _parse_hl_action(action):
    """帆软 HighlightAction → magic renderItem content dict,或 None(不支持)。"""
    cls = action.get("class", "")
    scope = _hl_scope(action)
    if "BackgroundHighlightAction" in cls:
        bg = next((x for x in action if local(x.tag) == "Background"), None)
        if bg is None:
            return None
        raw = bg.get("color")
        # ⭐ColorBackground 是「显式颜色填充」;color=-1 在 ARGB 即白色(0xFFFFFFFF)。
        # 基础单元格样式里 -1 当缺省丢弃,但高亮里 ColorBackground(-1) 是用户明确设的白底→译白色。
        if raw == "-1" and "Color" in (bg.get("name") or ""):
            color = "#FFFFFF"
        else:
            color = fr_color_to_hex(raw)
        return {"type": "background", "scope": scope,
                "backgroundColor": color} if color else None
    if "FRFontHighlightAction" in cls:
        font = next((x for x in action if local(x.tag) == "FRFont"), None)
        if font is None:
            return None
        c = {"type": "font", "scope": scope}
        sv = font.get("style")
        if sv and sv.lstrip("-").isdigit():
            if int(sv) & 1:
                c["bold"] = "true"
            if int(sv) & 2:
                c["italic"] = "true"
        if font.get("foreground") is not None:      # FRFont 颜色常在 foreground 属性
            h = fr_color_to_hex(font.get("foreground"))
            if h:
                c["color"] = h
        for fg in font:
            if local(fg.tag) == "foreground":
                for x in fg.iter():
                    if local(x.tag) == "FineColor":
                        h = fr_color_to_hex(x.get("color"))
                        if h:
                            c["color"] = h
        return c
    if "ForegroundHighlightAction" in cls:
        # 真实结构是 <Foreground color="-65536"/>(color 在属性),旧代码只找 FineColor 元素→全漏。
        color = None
        fgel = next((x for x in action if local(x.tag) == "Foreground"), None)
        if fgel is not None and fgel.get("color") is not None:
            color = fr_color_to_hex(fgel.get("color"))
        if color is None:                       # 兜底:嵌套 FineColor
            for x in action.iter():
                if local(x.tag) == "FineColor":
                    color = fr_color_to_hex(x.get("color"))
                    break
        return {"type": "color", "scope": scope, "color": color} if color else None
    return None  # ValueHighlightAction / ColWidth 等暂不支持


def _parse_cell_content(O, cell, datasets, issues):
    if O is None:
        return
    t = O.get("t")
    cls = O.get("class", "")
    if t == "DSColumn":
        attrs = next((ch for ch in O if local(ch.tag) == "Attributes"), None)
        dsName = attrs.get("dsName") if attrs is not None else None
        field = attrs.get("columnName") if attrs is not None else None
        agg = "group"
        for ch in O:
            if local(ch.tag) == "RG":
                if "SummaryGrouper" in ch.get("class", ""):
                    fn = next((("".join(x.itertext()).strip().rsplit(".", 1)[-1])
                               for x in ch if local(x.tag) == "FN"), None)
                    agg = SUMMARY_FN_MAP.get(fn, "sum")
                else:
                    agg = "group"
        cell.update(kind="dataset", dsName=dsName, field=field, agg=agg)
        if dsName in datasets and field:
            cur = datasets[dsName]["fields"].get(field, "String")
            datasets[dsName]["fields"][field] = (
                "Number" if agg in AGG_NUMERIC else cur)
    elif "Formula" in cls:
        expr = "".join(next((ch for ch in O if local(ch.tag) == "Attributes"),
                            O).itertext()).strip().lstrip("=").strip()
        _set_expression(cell, expr, issues)
    else:
        txt = "".join(O.itertext()).strip()
        if txt.startswith("="):
            _set_expression(cell, txt[1:].strip(), issues)
        else:
            cell.update(kind="text", text=txt)
        if t in ("RichText", "BiasTextPainter"):
            issues.append(Issue("manual", cellref(cell["r"], cell["c"]),
                                "帆软富文本/斜线头(%s)仅提取纯文本,样式需手工还原" % t))


def _set_expression(cell, expr, issues):
    """翻译公式并据未映射函数决定是否标红"""
    new, unknown = translate_expression(expr)
    new = guard_zero_division(new)
    cell.update(kind="expression", text=new)
    if unknown:
        issues.append(Issue("degraded", cellref(cell["r"], cell["c"]),
                            "公式含未映射函数 %s,需复核/AI:%s"
                            % ("、".join(sorted(unknown)),
                               new[:50] + ("…" if len(new) > 50 else ""))))


# ----------------------------------------------------------------------------
# 版面整理:标题跨度 + 孤立格收回(配合裁剪)
# ----------------------------------------------------------------------------
def _normalize_layout(cells):
    """整理帆软模板的两类「不规整」版面,使裁剪后更紧凑端正:
    ①孤立右置格:与主体之间隔着大段空列的内容格(如「制表日期」放在第47列)→ 收回主体
      宽度内、本行右对齐(空出的远端列随后被 trim 裁掉)。
    ②标题/副标题行:表头/表尾区里「整行仅一个合并格、从第0列起、窄于主体宽」的格(如
      标题、统计时间只 cs=3 而数据是6列)→ 扩展到主体宽度,使其横跨整表居中。
    主体宽度=从第0列起连续被占用到的最后一列。只在确定语义时改,保守不误伤数据带。
    """
    non_empty = [c for c in cells.values() if c["kind"] != "empty"]
    if not non_empty:
        return cells
    occ = set()
    for c in non_empty:
        for cc in range(c["c"], c["c"] + c["cs"]):
            occ.add(cc)
    if 0 not in occ:
        return cells
    body_max = 0
    while (body_max + 1) in occ:
        body_max += 1
    body_w = body_max + 1
    data_rows = [c["r"] for c in non_empty if c["kind"] == "dataset"]
    first_data = min(data_rows) if data_rows else None
    last_data = max(data_rows) if data_rows else None
    by_row = {}
    for c in non_empty:
        by_row.setdefault(c["r"], []).append(c)
    out = dict(cells)
    for r, rcells in by_row.items():
        rcells = sorted(rcells, key=lambda c: c["c"])
        # ① 孤立右置格(跨过空隙)→ 主体内右对齐
        for c in list(rcells):
            if c["c"] > body_max + 1:
                others = [o for o in rcells if o is not c]
                new_c = max(0, body_w - c["cs"])
                while new_c > 0 and any(new_c < o["c"] + o["cs"] and new_c + c["cs"] > o["c"]
                                        for o in others):
                    new_c -= 1
                if (c["r"], c["c"]) in out:
                    del out[(c["r"], c["c"])]
                out[(c["r"], new_c)] = dict(c, c=new_c)
        # ② 表头/表尾区单合并格标题 → 扩到主体宽
        header_zone = (first_data is None or r < first_data or r > last_data)
        if header_zone and len(rcells) == 1:
            c = rcells[0]
            if c["kind"] in ("text", "expression") and c["c"] == 0 and 1 < c["cs"] < body_w:
                # ⭐标题自身可能纵向合并(rs>1):扩宽不能盖过「落在标题行跨度内、锚点在标题右侧」
                # 的真实格(真机实证:手术记录 标题 A1 cs=9 rs=2 被扩到 cs=10,盖住同处第 2 行的
                # 竖向合并表头 J2(rs=2)→ J2 锚点被当成标题子格 → 其子格 J3 找不到属主格,整张报表崩)。
                # 故扩宽止于「标题行跨度内最靠左的他格锚列」,无碰撞才扩到主体宽。
                rs = c.get("rs", 1)
                limit = body_w
                for o in non_empty:
                    if o is c:
                        continue
                    if (o["r"] < r + rs and o["r"] + o["rs"] > r
                            and o["c"] >= c["cs"]):
                        limit = min(limit, o["c"])
                if limit > c["cs"] and (r, 0) in out:
                    out[(r, 0)] = dict(out[(r, 0)], cs=limit)
    return out


# ----------------------------------------------------------------------------
# 智能裁剪空行/空列
# ----------------------------------------------------------------------------
def trim_empty_grid(cells, row_h, col_w):
    """裁掉完全空的行/列(没有任何非空单元格占用),重映射坐标与单元格名引用。

    保留依据=「内容单元格的占用(origin+span)」:被合并单元格跨到的列/行也算占用→保留,
    故合并跨度天然完整保留(不破坏 colspan/rowspan)。裁后靠右/靠下的单元格名会变
    (如 AV6→G6),需同步重映射表达式、显式父格、高亮条件里的单元格引用。
    返回 (新cells, 新row_h, 新col_w)。
    """
    non_empty = [c for c in cells.values() if c["kind"] != "empty"]
    if not non_empty:
        return cells, row_h, col_w
    keep_cols, keep_rows = set(), set()
    for cell in non_empty:
        for cc in range(cell["c"], cell["c"] + cell["cs"]):
            keep_cols.add(cc)
        for rr in range(cell["r"], cell["r"] + cell["rs"]):
            keep_rows.add(rr)
    # 总是重建:即使内容列已连续(无需移列),重建也会丢掉高列号的空占位格,
    # 避免它们把 max_c 撑大(连续时下面的映射是恒等映射,不改坐标/引用)。
    col_map = {old: i for i, old in enumerate(sorted(keep_cols))}
    row_map = {old: i for i, old in enumerate(sorted(keep_rows))}
    # 单元格名重映射(只记变化的)
    name_remap = {}
    for cell in non_empty:
        old = "%s%d" % (col_letter(cell["c"] + 1), cell["r"] + 1)
        new = "%s%d" % (col_letter(col_map[cell["c"]] + 1), row_map[cell["r"]] + 1)
        if old != new:
            name_remap[old] = new

    def _remap_refs(s):
        if not s or not name_remap:
            return s
        stash = []
        t = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"",
                   lambda m: stash.append(m.group(0)) or "\x00%d\x00" % (len(stash) - 1), s)
        t = re.sub(r"\b[A-Z]+\d+\b", lambda m: name_remap.get(m.group(0), m.group(0)), t)
        return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], t)

    new_cells = {}
    for cell in non_empty:
        nr, nc = row_map[cell["r"]], col_map[cell["c"]]
        nc2 = dict(cell, r=nr, c=nc)
        nc2["cs"] = col_map[cell["c"] + cell["cs"] - 1] - nc + 1
        nc2["rs"] = row_map[cell["r"] + cell["rs"] - 1] - nr + 1
        if nc2.get("kind") in ("expression",) and nc2.get("text"):
            nc2["text"] = _remap_refs(nc2["text"])
        for k in ("left", "top"):
            v = nc2.get(k)
            if v and v not in ("default", "none"):
                nc2[k] = name_remap.get(v, v)
        if nc2.get("highlights"):
            nc2["highlights"] = [dict(h, expr=_remap_refs(h.get("expr", "")))
                                 for h in nc2["highlights"]]
        new_cells[(nr, nc)] = nc2
    new_row_h = {row_map[r]: h for r, h in (row_h or {}).items() if r in keep_rows}
    new_col_w = {col_map[c]: w for c, w in (col_w or {}).items() if c in keep_cols}
    return new_cells, new_row_h, new_col_w


def _col_output_name(col):
    """单列 SQL 文本 → 输出列名(别名优先);无法确定返回 None。"""
    col = col.strip()
    if not col:
        return None
    m = re.search(r"(?is)\bas\s+[\"\[`]?([\w一-鿿]+)[\"\]`]?\s*$", col)   # ... as 名
    if m:
        return m.group(1)
    parts = col.rsplit(None, 1)                                          # 末尾空格别名
    if len(parts) == 2 and re.fullmatch(r"[\"\[`]?[\w一-鿿]+[\"\]`]?", parts[1]):
        return parts[1].strip('"[]`')
    if re.fullmatch(r"[\w一-鿿]+(\.[\w一-鿿]+)?", col):                    # 裸列 a.b / b
        return col.rsplit(".", 1)[-1]
    return None                                                          # 表达式无别名→不确定


def fields_from_sql(sql):
    """从数据集 SQL 顶层 SELECT 列推断字段名(单元格推断不到时兜底)。
    仅当每一列都能明确判定输出名时返回列表;SELECT * 或含不确定列→返回 [](维持现状+告警)。"""
    if not sql:
        return []
    s = re.sub(r"'(?:[^'\\]|\\.)*'", "''", sql)        # 抹掉字符串字面量(避免内部逗号/from 干扰)
    s = re.sub(r"--[^\n]*", "", s)                      # 去行注释
    low = s.lower()
    si = low.find("select")
    if si < 0:
        return []
    depth, fi, i = 0, -1, si + 6                        # 从 select 后找顶层(depth0)的 from
    while i < len(s):
        c = s[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and low[i:i + 4] == "from" \
                and (i == 0 or not (low[i - 1].isalnum() or low[i - 1] == "_")) \
                and (i + 4 >= len(low) or not (low[i + 4].isalnum() or low[i + 4] == "_")):
            fi = i
            break
        i += 1
    if fi < 0:
        return []
    collist = re.sub(r"(?is)^\s*distinct\s+", "", s[si + 6:fi])
    cols, depth, cur = [], 0, ""                        # 顶层逗号切分
    for ch in collist:
        if ch == "(":
            depth += 1; cur += ch
        elif ch == ")":
            depth -= 1; cur += ch
        elif ch == "," and depth == 0:
            cols.append(cur); cur = ""
        else:
            cur += ch
    if cur.strip():
        cols.append(cur)
    names, seen = [], set()
    for col in cols:
        col = col.strip()
        if not col or col == "*" or col.endswith(".*"):
            return []                                  # SELECT * 无法确定→整体放弃
        nm = _col_output_name(col)
        if not nm:
            return []                                  # 有不确定列→整体放弃(避免部分字段误导)
        if nm not in seen:
            seen.add(nm); names.append(nm)
    return names


# ----------------------------------------------------------------------------
# 单个 sheet → sight-report 网格报表 XML
# ----------------------------------------------------------------------------
def _process_grid(sm, cfg, issues):
    """网格级处理(裁空、引用撑格、父格纠偏、日期公式包裹),返回处理后网格与几何。
    单 sheet 与多页签(每 sheet)共用此函数,保证两条路网格语义完全一致。"""
    cells = sm["cells"]
    if not cells:
        issues.append(Issue("manual", "-", "未解析到单元格"))
    row_h, col_w = sm["row_h"], sm["col_w"]
    if cfg.get("trim_empty", True):
        before = (max((c["c"] + c["cs"] for c in cells.values()), default=0),
                  max((c["r"] + c["rs"] for c in cells.values()), default=0))
        cells = _normalize_layout(cells)         # 先整理标题跨度/孤立格,再裁空列
        cells, row_h, col_w = trim_empty_grid(cells, row_h, col_w)
        sm = dict(sm, cells=cells, row_h=row_h, col_w=col_w)
        after = (max((c["c"] + c["cs"] for c in cells.values()), default=0),
                 max((c["r"] + c["rs"] for c in cells.values()), default=0))
        if after != before:
            issues.append(Issue("info", "-",
                                "已自动裁剪空行列:列 %d→%d、行 %d→%d"
                                % (before[0], after[0], before[1], after[1])))
    max_r = max((c["r"] + c["rs"] for c in cells.values()), default=1)
    max_c = max((c["c"] + c["cs"] for c in cells.values()), default=1)

    # 公式/高亮/父格引用到、但裁剪后落在网格外的单元格(如 =SUM(Z4) 引用空列 Z):
    # 帆软容忍引用空格(=0),magic 引用不存在的格会硬报错「目标单元格…不存在」令整张报表崩。
    # 撑大网格尺寸即可——下方占位循环会在 max_r×max_c 内自动补出空占位格(带 name),引用即可解析。
    # 仅在合理范围内撑(原尺寸+6),防个别笔误引用把网格炸大。
    _refrc = re.compile(r"(?<![A-Za-z$])([A-Z]{1,2})(\d+)")

    def _ref_cells(s):
        if not s:
            return
        t = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "", s)
        for m in _refrc.finditer(t):
            cc = 0
            for ch in m.group(1):
                cc = cc * 26 + (ord(ch) - 64)
            yield int(m.group(2)) - 1, cc - 1
    need_r, need_c = max_r, max_c
    for cell in cells.values():
        refs = []
        if cell.get("kind") == "expression":
            refs += list(_ref_cells(cell.get("text")))
        for h in (cell.get("highlights") or []):
            refs += list(_ref_cells(h.get("expr", "")))
        for k in ("left", "top"):
            v = cell.get(k)
            if v and v not in ("default", "none"):
                refs += list(_ref_cells(v))
        for rr, cc in refs:
            if rr < 0 or cc < 0 or (rr, cc) in cells:
                continue
            if rr < max_r + 6 and cc < max_c + 6:
                need_r, need_c = max(need_r, rr + 1), max(need_c, cc + 1)
    max_r, max_c = need_r, need_c

    subordinate = {}
    for (r, c), cell in cells.items():
        if cell["cs"] > 1 or cell["rs"] > 1:
            for rr in range(r, r + cell["rs"]):
                for cc in range(c, c + cell["cs"]):
                    if (rr, cc) != (r, c):
                        subordinate[(rr, cc)] = (r, c)

    # ⭐公式引用了「被合并吸收的格」→ 重映射到同列下扩数据格。
    # 真机(国家医保各结算表,多 sheet 结算清单):统计时段副标题横幅 cs=38 盖住整行,
    # 而汇总/差值公式 SUM(R2)/AJ2-AL2 引用的 R2、AJ2 正落在横幅下被吸收 → magic 报
    # 「目标单元格 R2/G2 不存在」整张崩。帆软容忍(那些格其实是该列下扩数据格的旧行号位)。
    # 修:把引用从被吸收格映射到「同列的下扩 dataset 数据格」(如 R2→R4 绑 feiyongze)。
    # 仅当目标格确被吸收(subordinate 且无独立格)且该列有下扩数据格时改;否则原样(不致更糟)。
    _coldata = {}
    for (r, c), cell in cells.items():
        if cell.get("kind") == "dataset" and cell.get("expand") == "down":
            _coldata.setdefault(c, "%s%d" % (col_letter(c + 1), r + 1))
    _absref = {}
    for (rr, cc) in subordinate:
        if (rr, cc) not in cells and cc in _coldata:
            old = "%s%d" % (col_letter(cc + 1), rr + 1)
            if old != _coldata[cc]:
                _absref[old] = _coldata[cc]
    if _absref:
        def _remap_absorbed(s):
            if not s:
                return s
            stash = []
            t = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"",
                       lambda m: stash.append(m.group(0)) or "\x00%d\x00" % (len(stash) - 1), s)
            t = _refrc.sub(lambda m: _absref.get(m.group(0), m.group(0)), t)
            return re.sub(r"\x00(\d+)\x00", lambda m: stash[int(m.group(1))], t)
        for cell in cells.values():
            if cell.get("kind") == "expression" and cell.get("text"):
                cell["text"] = _remap_absorbed(cell["text"])
            for h in (cell.get("highlights") or []):
                if h.get("expr"):
                    h["expr"] = _remap_absorbed(h["expr"])
            for k in ("left", "top"):
                v = cell.get(k)
                if v and v not in ("default", "none") and v in _absref:
                    cell[k] = _absref[v]

    # ⭐父格纠偏:下扩数据带靠「左父格」串联,纵向本不该挂父格;但 magic 的「默认父格」会把
    # 纵向父格解析成正上方最近的格——若那是静态表头,配合 enabledParentCellFilter 会把数据
    # 按表头文字过滤成空(真机实证:SQL 返 9 行却渲染 0 行)。故:下扩格若上方最近内容格是
    # 静态格(或无),top→none;右扩格同理 left→none。仅改默认父格,保留帆软显式父格与「父格本
    # 身是扩展格」的真实嵌套(如交叉表/多级分组)。
    def _nearest_content(r, c, dr, dc):
        rr, cc = r + dr, c + dc
        while rr >= 0 and cc >= 0:
            key = subordinate.get((rr, cc), (rr, cc))
            cc2 = cells.get(key)
            if cc2 and cc2["kind"] != "empty":
                return cc2
            rr += dr
            cc += dc
        return None
    for cell in cells.values():
        if cell["kind"] == "empty":
            continue
        if cell["expand"] == "down" and cell.get("top", "default") == "default":
            nb = _nearest_content(cell["r"], cell["c"], -1, 0)
            if nb is None or nb["expand"] == "none":
                cell["top"] = "none"
        elif cell["expand"] == "right" and cell.get("left", "default") == "default":
            nb = _nearest_content(cell["r"], cell["c"], 0, -1)
            if nb is None or nb["expand"] == "none":
                cell["left"] = "none"

    # ⭐左父格去链(真机实证:门诊收入分类统计 报「[D5]引用了子格[F5]」):magic 默认父格把同行
    # 相邻格逐个串成左父链 B←C←D←E←F,使靠右的格成为靠左格的子格;若某格公式引用了它右侧的格
    # (交叉表里 比例=金额/合计列),即触发「父格表达式不能引用子格」。帆软默认父格只挂到「扩展
    # 维度格」、跳过静态/公式/值格。故:非扩展格(expand none/-)且 left=default → 改挂同行最近的
    # 「左侧下扩维度格」,令它们成为该维度下的兄弟格(互相引用合法)且仍随维度纵向扩展;无则保持
    # default。注:挂到维度而非相邻度量格,parentCellFilter 过滤也更正确。
    def _nearest_left_down(r, c):
        # ⭐左父格只挂到「下扩 *数据* 维度格」,跳过下扩的 *表达式度量格*:度量格不是分组维度,
        # 让它当父格会把右侧数据格串成它的子格,而度量公式又常引用右侧数据格(医保结算表
        # T4=`V4-Y4`),即触发 magic「父格表达式不能引用子格」/「无法处理单元格依赖」。跳过
        # 表达式格后,数据格们都挂到同一左侧数据维度成为兄弟,互相引用合法(真机:国家医保各结算表)。
        cc = c - 1
        while cc >= 0:
            nb = cells.get(subordinate.get((r, cc), (r, cc)))
            if nb and nb["kind"] == "dataset" and nb["expand"] == "down":
                return nb
            cc -= 1
        return None
    for cell in cells.values():
        # 右扩格的 left 已在上面单独处理;其余(下扩维度格 + 静态/公式/值格)统一在此重挂左父。
        if cell["kind"] == "empty" or cell["expand"] == "right":
            continue
        if cell.get("left", "default") != "default":   # 保留帆软显式左父格(如序号 left=某数据列)
            continue
        dim = _nearest_left_down(cell["r"], cell["c"])
        # 有左侧下扩维度 → 挂为其兄弟(随维度纵扩、嵌套分组逐层挂上一维度);无(合计行/表头行/
        # 明细首列)→ left=none 断链。这样:①交叉表合计行 D6=金额/总额 引用 F6 不再算子格;②明细
        # 列只挂到「下扩维度」、跳过中间的静态序号格,避免「数据列←序号←数据列」成环(真机:胰岛素
        # 报「无法处理单元格依赖关系」=序号 left=姓名 + 数据列默认左父链回序号 的环)。
        cell["left"] = ("%s%d" % (col_letter(dim["c"] + 1), dim["r"] + 1)
                        if dim is not None else "none")

    # ⭐横向交叉表的「全宽 banner 行」(标题/统计时段等):必须 columnAutoStretch=true。
    # 引擎实证(RightColumnExpanderProcessor):右扩展时,扩展行之上、无左父格、全宽的表头格
    # 若 columnAutoStretch=false 会「为每个折叠列复制一份」→ 标题每 N 列重复;设 true 则
    # riseColspan 让其横跨所有展开列(对标 AI 生成交叉表的标题写法)。仅在存在右扩展时处理,
    # 不影响普通行式/分组报表。
    _right = [c for c in cells.values()
              if c.get("kind") != "empty" and c.get("expand") == "right"]
    if _right:
        _expand_row = min(c["r"] for c in _right)
        _expand_col = min(c["c"] for c in _right)   # 右扩展起始列
        _full_w = max((c["c"] + c["cs"] for c in cells.values()), default=1)
        for cell in cells.values():
            # 标题/统计时段等 banner 行(列0、跨多列、在右扩行之上)需 columnAutoStretch=true,
            # 否则右扩展时「为每个折叠列复制一份」→ banner 重复(真机:综合查询 药品销售汇总
            # 统计时间横幅重复 3 份)。原仅放行「全宽」banner;但统计时段格常只跨左半(右侧跟隐藏
            # helper 格),非全宽却仍跨入右扩列区→照样重复。故放宽:列0 + 在扩行之上 + 跨入右扩列区
            # (c+cs > 扩展起始列)即视为 banner 拉伸。列组表头(西药/合计)在扩行本身或更右、非列0,
            # 不会误伤。
            if (cell.get("kind") in ("text", "expression")
                    and cell["c"] == 0 and cell["cs"] > 1
                    and cell["r"] < _expand_row
                    and (cell["c"] + cell["cs"] >= _full_w
                         or cell["c"] + cell["cs"] > _expand_col)):
                cell["col_stretch"] = True

    conn_map = cfg["connection_map"]
    query = sm.get("query")
    used_ds = {c["dsName"] for c in cells.values() if c.get("dsName")}
    if query:
        used_ds |= query.get("ds_used", set())   # 下拉字典绑定的数据集也要 emit

    # 日期参数拼字符串时包 formatDate(避免显示 Java Date.toString)。参数类型取自查询面板 meta;
    # 此处后置处理(parse 阶段 _set_expression 早于查询面板解析,拿不到类型)
    date_fmt = {}
    if query and query.get("meta"):
        _DATE_PAT = {"Date": "yyyy-MM-dd", "DateTime": "yyyy-MM-dd HH:mm:ss"}
        date_fmt = {n: _DATE_PAT[m["datatype"]]
                    for n, m in query["meta"].items()
                    if m.get("datatype") in _DATE_PAT}
    if date_fmt:
        for c in cells.values():
            if c.get("kind") == "expression" and c.get("text"):
                c["text"] = wrap_date_params_in_concat(c["text"], date_fmt)

    return {"sm": sm, "cells": cells, "row_h": row_h, "col_w": col_w,
            "subordinate": subordinate, "max_r": max_r, "max_c": max_c,
            "used_ds": used_ds, "query": query}


def _report_open(sm, cfg, multi=False):
    """报表根元素 + (多页签时)<meta minEngine="2"> + <fonts>。"""
    rname = html.escape(sm.get("report_name", sm["name"]), quote=True)
    out = ['<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
           '<report xmlns="http://sightdata.top/schema/report-template" '
           'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'fileType="grid" reportName="%s" version="20260301.1">' % rname]
    if multi:
        # schema 能力门禁:多页签模板要求引擎 >=2,旧引擎读到会明确报错而非静默写坏
        # (与前端 generator addMeta / 后端 ReportParser.ENGINE_SCHEMA_CAPABILITY 一致)
        out.append('    <meta xmlns="" minEngine="2" />')
    out.append('    <fonts xmlns="" name="%s" />' % cfg["default_font_family"])
    return out


def _emit_report_head(out, sm, cfg, issues, used_ds):
    """发射报表级共享节点:dataset / pageSetting / setting / parameter / queryFormSetting。
    多页签下这些节点在根级只出现一次(datasets/params 为各 sheet 的并集)。"""
    query = sm.get("query")
    conn_map = cfg["connection_map"]
    date_fmt = {}
    if query and query.get("meta"):
        _DATE_PAT = {"Date": "yyyy-MM-dd", "DateTime": "yyyy-MM-dd HH:mm:ss"}
        date_fmt = {n: _DATE_PAT[m["datatype"]]
                    for n, m in query["meta"].items()
                    if m.get("datatype") in _DATE_PAT}
    # 列选择型参数集合(值为 a.记账日期 这类列引用):SQL 翻译时这些参数走 #{} 内联而非 ${} 绑定。
    ident_params = set()
    _qmeta = (query or {}).get("meta", {})
    for _pn, _pm in _qmeta.items():
        _dv = _pm.get("default")
        if _dv and _COL_IDENT.match(str(_dv)):
            ident_params.add(_pn)
    for _c in (query or {}).get("components", []):
        _pn = _c.get("parameterName") or _c.get("name")
        _opts = (_c.get("props") or {}).get("customBinding") or []
        if _pn and _opts and all(_COL_IDENT.match(str((o or {}).get("value", ""))) for o in _opts):
            ident_params.add(_pn)

    # 预格式化列表参数(默认值已自带引号,如帆软 \'4734\',\'25301\'):in (${p}) 是把这串
    # 直接文本内联,不可再包引号。这类参数 IN 规则走原样内联 #{$p}(默认值的反斜杠转义在
    # parameter emit 处一并去掉)。真机:ICU患者收治率 keshi 默认 \'4734\',\'25301\'。
    prequoted_params = set()
    for _pn, _pm in _qmeta.items():
        _dv = str(_pm.get("default") or "").replace("\\'", "'")
        if "'" in _dv:
            prequoted_params.add(_pn)

    # 日期类参数集合(用于 SQL 比较值内联时排除):①datatype Date/DateTime(date_fmt)
    # ②查询组件是日期/时间选择器(运行时传 Date 对象,内联会得 Date.toString 非法串)。
    # 字符串型选择器(radio/select,如 riqi=计费日期、endTime=某选项)值是字符串,可安全内联。
    date_param_set = set(date_fmt)
    for _c in (query or {}).get("components", []):
        if (_c.get("type") or "") in ("date", "datetime", "time", "daterange", "datetimerange"):
            _dn = _c.get("parameterName") or _c.get("name")
            if _dn:
                date_param_set.add(_dn)

    # 真·多选参数集合(运行时是 ArrayList,动态 IN 片段才可用 .join 拼列表):
    # 仅 ComboCheckBox→multiselect / CheckBox(Group)→checkbox。单选 ComboBox→select 是
    # String,String 上没有 join 扩展方法(见 translate_sql 内注释),不可走 join 分支。
    multi_param_set = set()
    for _c in (query or {}).get("components", []):
        if (_c.get("type") or "") in ("multiselect", "checkbox"):
            _mn = _c.get("parameterName") or _c.get("name")
            if _mn:
                multi_param_set.add(_mn)

    di = 0
    _unmapped_seen = set()      # 每个连接每张报表只提示一次(同连接多数据集=同一次映射解决)
    for dsName, ds in sm["datasets"].items():
        if used_ds and dsName not in used_ds:
            continue
        di += 1
        conn = ds.get("conn")
        # 映射值=数据连接名称(字符串);兼容旧 {id,name}(取 name)。运行时按名称解析数据源,无需 id。
        # 未显式映射时,默认直接沿用帆软原始连接名(转换结果不再留空;若目标系统连接名不同,
        # 在转换器映射表里改一次即可覆盖默认值,全部相关报表同步生效)。
        if conn and conn in conn_map:
            _mv = conn_map.get(conn)
            ds_conn_name = (_mv.get("name") if isinstance(_mv, dict) else _mv) or ""
        else:
            ds_conn_name = conn or ""
        ds_conn_name = ds_conn_name.strip()
        if conn and conn not in conn_map and conn not in _unmapped_seen:
            _unmapped_seen.add(conn)
            issues.append(Issue("manual", "连接:" + conn,
                                "帆软连接「%s」未在转换器显式映射,已默认使用同名数据连接「%s」;"
                                "若目标系统里的数据连接名称不同,请在映射表调整,映射一次即全部生效"
                                % (conn, conn)))
        # 数据集 id 用唯一的 ds_N;数据源只写 dataSourceName(后端按名称解析,无需 dataSourceId)
        da = ('xmlns="" id="ds_%d" name="%s" type="sql"'
              % (di, html.escape(dsName, quote=True)))
        if ds_conn_name:
            da += ' dataSourceName="%s"' % html.escape(ds_conn_name, quote=True)
        out.append('    <dataset %s>' % da)
        sql_out, sql_unk = translate_sql(ds.get("sql") or "", ident_params,
                                         prequoted_params, date_param_set,
                                         multi_param_set)
        out.append('        <sql>%s</sql>' % cdata(sql_out))
        if sql_unk:
            issues.append(Issue("degraded", "数据集:" + dsName,
                                "SQL 动态条件含未映射函数 %s,需复核"
                                % "、".join(sorted(sql_unk))))
        if not ds["fields"]:
            # 单元格推断不到字段时,从 SQL 顶层 SELECT 列兜底(全部列可确定才采用)
            inferred = fields_from_sql(ds.get("sql") or "")
            for fn in inferred:
                ds["fields"].setdefault(fn, "String")
            if inferred:
                issues.append(Issue("info", "数据集:" + dsName,
                                    "字段从 SQL SELECT 自动推断(%d 列):%s"
                                    % (len(inferred), "、".join(inferred[:12]))))
            else:
                issues.append(Issue("degraded", "数据集:" + dsName,
                                    "字段列表为空(SELECT * 或动态列),运行时由结果集自动发现,"
                                    "通常无需处理;若需固定列请在设计器补字段"))
        for fn, ft in ds["fields"].items():
            out.append('        <field name="%s" type="%s" />'
                       % (html.escape(fn, quote=True), ft))
        out.append('    </dataset>')

    out.append('    <pageSetting xmlns="" paper="A4" paperWidth="210" '
               'paperHeight="297" marginTop="20" marginBottom="20" '
               'marginLeft="20" marginRight="20" orientation="portrait" />')
    fetch = "false" if (query and query.get("delay")) else "true"
    out.append('    <setting xmlns="" rowLimit="0" splitRowForPaging="false" '
               'contentPosition="left" fetchDataWhenOpen="%s">' % fetch)
    out.append('        <watermark enabled="false" layout="diagonal" opacity="0.3" '
               'fontFamily="" fontSize="" fontColor=""><![CDATA[]]></watermark>')
    out.append('        <background type="none" />')
    out.append('    </setting>')
    # 顺序:setting → parameter → queryFormSetting → row …(遵循 XSD)
    meta = (query or {}).get("meta", {})
    for pi, (pn, pv) in enumerate(sm["params"].items(), 1):
        m = meta.get(pn, {})
        dt = m.get("datatype") or (
            "Date" if re.search(r"\d{4}-\d{2}-\d{2}", str(pv or "")) else "String")
        dv = m["default"] if m.get("default") is not None else pv
        # 去帆软对默认值里引号的反斜杠转义(\'4734\' → '4734'):magic 运行期把默认值原样
        # 内联进 SQL,残留的 \' 会变 in ('\'4734\'') 触发 syntax error(真机:ICU患者收治率)。
        dv = str(dv or "").replace("\\'", "'").replace('\\"', '"')
        pa = ('xmlns="" id="p_%d" name="%s" datatype="%s" defaultValue="%s"'
              % (pi, html.escape(pn, quote=True), dt,
                 html.escape(dv, quote=True)))
        if m.get("default_expr"):
            pa += ' defaultValueIsExpression="true"'
        if m.get("required"):
            pa += ' required="true"'
        out.append('    <parameter %s />' % pa)

    comps = (query or {}).get("components", [])
    qfs = {"components": comps}
    vals = (query or {}).get("validations") or []
    if vals:                                 # 跨字段日期校验(开始≤结束)
        qfs["validations"] = vals
    qjson = json.dumps(qfs, ensure_ascii=False)
    out.append('    <queryFormSetting xmlns="">%s</queryFormSetting>' % cdata(qjson))


def _emit_grid_lines(out, sm, cfg, cells, subordinate, max_r, max_c):
    """发射一个网格的 row/col/cell(单 sheet 直接在根级;多页签在 <sheet> 内)。"""
    div = cfg["length_divisor"]
    for r in range(1, max_r + 1):
        h = sm["row_h"].get(r - 1)
        out.append('    <row xmlns="" id="row_%d" num="%d" height="%s" '
                   'hidden="false" lock="false" />'
                   % (r, r, round(h / div, 2) if h else 30))
    for c in range(1, max_c + 1):
        w = sm["col_w"].get(c - 1)
        out.append('    <col xmlns="" id="col_%d" num="%d" width="%s" '
                   'hidden="false" lock="false" />'
                   % (c, c, round(w / div, 2) if w else 100))

    for r in range(max_r):
        for c in range(max_c):
            if (r, c) in cells and (r, c) not in subordinate:
                out.append(_emit_cell(cells[(r, c)], cfg))
            elif (r, c) in subordinate:
                out.append(_emit_placeholder(r, c, "false", 0, 0))
            else:
                out.append(_emit_placeholder(r, c, "true", 1, 1))


def map_to_xml(sm, cfg, issues):
    proc = _process_grid(sm, cfg, issues)
    sm = proc["sm"]
    out = _report_open(sm, cfg, multi=False)
    _emit_report_head(out, sm, cfg, issues, proc["used_ds"])
    _emit_grid_lines(out, sm, cfg, proc["cells"], proc["subordinate"],
                     proc["max_r"], proc["max_c"])
    out.append('</report>')
    return "\n".join(out)


def map_to_xml_multi(head_sm, sheets_proc, cfg, issues):
    """多 sheet → 单个多页签报表。head_sm 提供共享 datasets/params/query/report_name;
    sheets_proc 是各 sheet 的 _process_grid 结果 + sheet_id/sheet_name。契约见 docs/report-tab-设计.md §3.1。"""
    union_used = set()
    for p in sheets_proc:
        union_used |= (p.get("used_ds") or set())
    out = _report_open(head_sm, cfg, multi=True)
    _emit_report_head(out, head_sm, cfg, issues, union_used)
    out.append('    <sheets xmlns="">')
    for p in sheets_proc:
        sid = html.escape(p["sheet_id"], quote=True)
        sname = html.escape(p["sheet_name"], quote=True)
        out.append('        <sheet id="%s" name="%s">' % (sid, sname))
        _emit_grid_lines(out, p["sm"], cfg, p["cells"], p["subordinate"],
                         p["max_r"], p["max_c"])
        out.append('        </sheet>')
    out.append('    </sheets>')
    out.append('</report>')
    return "\n".join(out)


def _font_size(style, cfg):
    if style and style.get("fontSize"):
        sz = round(style["fontSize"] / cfg["font_size_divisor"])
        return max(cfg["font_size_min"], min(cfg["font_size_max"], sz))
    # 无样式(源单元格无 s= 索引)→ 帆软内置默认字号 = 宋体 9pt
    return 9


def _font_family(style, cfg):
    if style and style.get("fontFamily"):
        return cfg["font_name_map"].get(style["fontFamily"].strip().lower(),
                                        style["fontFamily"])
    return cfg["default_font_family"]


def _borders(style):
    lines = []
    bs = (style or {}).get("borders", {})
    for side in ("left", "top", "right", "bottom"):
        b = bs.get(side)
        color = (fr_color_to_hex(b.get("color")) or "#000000") if b else "#000000"
        lines.append('        <%sBorder style="solid" width="1" color="%s" />'
                     % (side, color))
    return "\n".join(lines)


def _emit_cell(cell, cfg):
    r, c = cell["r"], cell["c"]
    row, col = r + 1, c + 1
    style, kind = cell["style"], cell["kind"]
    typ = {"dataset": "dataset", "expression": "expression"}.get(kind, "text")
    a = {"row": row, "col": col, "name": "%s%d" % (col_letter(col), row),
         "colspan": cell["cs"], "rowspan": cell["rs"], "type": typ,
         "left": cell.get("left", "default"), "top": cell.get("top", "default")}
    if typ in ("dataset", "expression"):
        a["pagingRepeatContent"] = "true"
    a["rowAutoStretch"] = "true" if cell["expand"] == "down" else "false"
    a["columnAutoStretch"] = ("true" if (cell["expand"] == "right"
                                          or cell.get("col_stretch")) else "false")
    if typ in ("dataset", "expression"):
        a["expand"] = cell["expand"]
    a["visible"] = "true"
    pad = cfg.get("cell_padding", 0)
    if pad:                                  # 补内边距,避免数字贴边/挤在一起(pt)
        a["leftPadding"] = pad
        a["rightPadding"] = pad
        a["topPadding"] = pad
        a["bottomPadding"] = pad
    bg = fr_color_to_hex(style.get("backgroundColor")) if style else None
    fg = fr_color_to_hex(style.get("foreColor")) if style else None
    if bg:
        a["backgroundColor"] = bg
    if fg:
        a["foreColor"] = fg
    a["fontSize"] = _font_size(style, cfg)
    a["fontFamily"] = _font_family(style, cfg)
    if style and style.get("bold"):
        a["bold"] = "true"
    if style and style.get("italic"):
        a["italic"] = "true"
    if style and style.get("fmt_type") in ("number", "percent"):
        a["align"] = "right"                      # 数值/百分比右对齐
    elif cell["cs"] > 1 or kind == "expression":
        a["align"] = "center"
    elif kind == "dataset" and cell["agg"] in AGG_NUMERIC:
        a["align"] = "right"
    elif kind == "dataset":
        a["align"] = "left"
    else:
        a["align"] = "center"
    a["valign"] = "middle"

    s = ['    <cell xmlns="" %s>' % attr(a)]
    if kind == "dataset":
        s.append('        <datasetContent %s />' % attr({
            "dataset": cell["dsName"] or "", "field": cell["field"] or "",
            "wordWrap": "false", "aggregateType": cell["agg"] or "select",
            "enabledParentCellFilter": "true", "enabledCollapse": "false",
            "order": "none"}))
    elif kind == "expression":
        s.append('        <expressionContent wordWrap="false">%s'
                 '</expressionContent>' % cdata(cell["text"]))
    else:
        s.append('        <textContent wordWrap="false">%s</textContent>'
                 % cdata(cell["text"]))
    # 显示格式化(数字/百分比/日期)→ 仅数值/表达式格(遵循 XSD:content 后、renderItem 前)
    if kind in ("dataset", "expression") and style and style.get("fmt_type"):
        s.append('        <format formatType="%s">%s</format>'
                 % (style["fmt_type"], cdata(style.get("fmt_pattern") or "")))
    for hl in cell.get("highlights", []):
        s.append(_emit_render_item(hl))
    s.append(_borders(style))
    s.append('    </cell>')
    return "\n".join(s)


def _emit_render_item(hl):
    """条件渲染项 → <renderItem>(content 在 borders 之前,遵循 XSD)。"""
    contents = []
    for c in hl["contents"]:
        ca = {"type": c["type"], "scope": c.get("scope", "cell")}
        for k in ("backgroundColor", "color", "bold", "italic"):
            if c.get(k):
                ca[k] = c[k]
        contents.append('                <content %s />' % attr(ca))
    return ('        <renderItem name="%s">\n'
            '            <rule ruleType="if">\n'
            '                <condition itemType="expr" expression="%s" />\n'
            '%s\n'
            '            </rule>\n'
            '        </renderItem>'
            % (html.escape(hl["name"], quote=True),
               html.escape(hl["expr"], quote=True), "\n".join(contents)))


def _emit_placeholder(r, c, visible, colspan, rowspan):
    row, col = r + 1, c + 1
    a = {"row": row, "col": col, "name": "%s%d" % (col_letter(col), row),
         "colspan": colspan, "rowspan": rowspan, "type": "text",
         "left": "default", "top": "default", "rowAutoStretch": "false",
         "columnAutoStretch": "false", "visible": visible, "fontSize": 12,
         "fontFamily": "微软雅黑", "align": "center", "valign": "middle"}
    return ('    <cell xmlns="" %s>\n        <textContent wordWrap="false"><![CDATA[]]>'
            '</textContent>\n%s\n    </cell>' % (attr(a), _borders(None)))


# ----------------------------------------------------------------------------
# 转换报告
# ----------------------------------------------------------------------------
def write_report(title, sm, issues):
    seen, uniq = set(), []
    for i in issues:
        k = (i.level, i.where, i.msg)
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    manual = [i for i in uniq if i.level == "manual"]
    degraded = [i for i in uniq if i.level == "degraded"]
    n_cells = sum(1 for c in sm["cells"].values() if c["kind"] != "empty")
    L = ["# 转换报告:%s\n" % title, "## 概览\n",
         "- 数据单元格:%d" % n_cells,
         "- 数据集:%d" % len({c["dsName"] for c in sm["cells"].values()
                              if c.get("dsName")}),
         "- 参数:%d" % len(sm["params"]),
         "- 待人工项:%d" % len(manual),
         "- 已降级项(需复核):%d\n" % len(degraded),
         "**自动化判断**:%s\n" % ("高" if not manual else
                                  ("中" if len(manual) <= 3 else "需重点复核"))]
    if manual:
        L.append("## ⚠️ 待人工处理\n")
        L += ["- `%s` — %s" % (i.where, i.msg) for i in manual] + [""]
    if degraded:
        L.append("## 🔶 已降级(请复核)\n")
        L += ["- `%s` — %s" % (i.where, i.msg) for i in degraded] + [""]
    if not manual and not degraded:
        L.append("✅ 未发现需人工的项,建议导入后在设计器抽查扩展/分组。\n")
    return "\n".join(L), len(manual), len(degraded), n_cells


# ----------------------------------------------------------------------------
# 编排
# ----------------------------------------------------------------------------
def compute_params(datasets, used_ds):
    params = {}
    for dsName in used_ds:
        ds = datasets.get(dsName)
        if not ds:
            continue
        for k, v in ds["defaults"].items():
            params.setdefault(k, v)
        for name in extract_sql_params(ds["sql"] or ""):
            params.setdefault(name, None)
    return params


def load_config(path):
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path and os.path.exists(path):
        for k, v in json.load(open(path, encoding="utf-8")).items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k].update(v)
            else:
                cfg[k] = v
    return cfg


def _issue_rows(issues):
    """去重可操作问题(待人工+降级),并统计按推定语义自动转的高亮数。"""
    _seen, _iss, _assumed_hl = set(), [], 0
    for _i in issues:
        if _i.level in ("manual", "degraded"):
            _k = (_i.level, _i.where, _i.msg)
            if _k not in _seen:
                _seen.add(_k)
                _iss.append({"level": _i.level, "where": _i.where, "msg": _i.msg})
        elif _i.level == "info" and "按推定运算符语义" in _i.msg:
            _assumed_hl += 1
    return _iss, _assumed_hl


def _resolve_dest(dest, subdir, base, overwrite):
    """按覆盖策略解析落盘名。返回 (base, rel, mrg, skip)；skip=True 表示已存在且策略为跳过。"""
    rel = os.path.join(subdir, base) if subdir else base
    mrg = os.path.join(dest, base + ".mrg")
    if os.path.exists(mrg):
        if overwrite == "skip":
            return base, rel, mrg, True
        if overwrite == "rename":
            k = 1
            while os.path.exists(os.path.join(dest, "%s_%d.mrg" % (base, k))):
                k += 1
            base = "%s_%d" % (base, k)
            rel = os.path.join(subdir, base) if subdir else base
            mrg = os.path.join(dest, base + ".mrg")
    return base, rel, mrg, False


def convert_one(path, outdir, cfg, subdir="", overwrite="overwrite"):
    """overwrite: overwrite=覆盖 / skip=已存在则跳过 / rename=自动改名不覆盖。
    多 sheet 且 cfg['merge_sheets'](默认 True):合并为一个多页签 .mrg;否则每 sheet 拆一张。
    单 sheet 无论如何都走扁平老格式(对既有单 sheet 报表字节级零变化)。"""
    try:
        model = parse_cpt(path)
    except ET.ParseError as e:
        return [{"name": os.path.basename(path), "ok": False,
                 "error": "XML 解析失败:%s" % e}]
    sheets = [s for s in model["sheets"] if s["n_content"] > 0]
    if not sheets:
        return [{"name": model["name"], "ok": False, "error": "无内容 sheet"}]
    multi = len(sheets) > 1
    merge = cfg.get("merge_sheets", True)
    dest = os.path.join(outdir, subdir) if subdir else outdir
    os.makedirs(dest, exist_ok=True)
    query = model.get("query")

    # ---- 多 sheet 合并为单个多页签(tab)报表 ----
    if multi and merge:
        base, rel, mrg, skip = _resolve_dest(dest, subdir, model["name"], overwrite)
        if skip:
            return [{"name": rel, "ok": True, "skipped": True,
                     "cells": 0, "manual": 0, "degraded": 0}]
        combined, processed, union_used, report_cells = [], [], set(), {}
        if query:
            combined.extend(query["issues"])
        for si, s in enumerate(sheets, 1):
            s_issues = list(s["issues"])
            s_sm = {"name": model["name"], "cells": s["cells"],
                    "row_h": s["row_h"], "col_w": s["col_w"], "query": query}
            proc = _process_grid(s_sm, cfg, s_issues)
            proc["sheet_id"] = "s_%d" % si          # 报表内唯一、非空;供 API/缓存/深链引用
            proc["sheet_name"] = s["sheet"]
            processed.append(proc)
            union_used |= proc["used_ds"]
            for (r, c), cell in s["cells"].items():  # 报告计数用原始格(与拆分模式口径一致)
                report_cells[(si, r, c)] = cell
            # sheet 级网格问题前缀 sheet 名,报告里能定位是哪个页签
            for it in s_issues:
                combined.append(Issue(it.level, "[%s] %s" % (s["sheet"], it.where), it.msg))
        params = compute_params(model["datasets"], union_used)
        for pn in (query or {}).get("meta", {}):     # 面板控件参数也登记
            params.setdefault(pn, None)
        head_sm = {"name": model["name"], "report_name": model["name"],
                   "datasets": model["datasets"], "params": params, "query": query}
        xml_text = map_to_xml_multi(head_sm, processed, cfg, combined)
        title = "%s(多页签 · %d 个 sheet)" % (model["name"], len(sheets))
        report, n_manual, n_deg, n_cells = write_report(
            title, {"cells": report_cells, "params": params}, combined)
        with open(mrg, "w", encoding="utf-8") as f:
            f.write(xml_text)
        with open(os.path.join(dest, base + ".report.md"), "w", encoding="utf-8") as f:
            f.write(report)
        _iss, _assumed_hl = _issue_rows(combined)
        return [{"name": rel, "ok": True, "skipped": False, "cells": n_cells,
                 "manual": n_manual, "degraded": n_deg, "issues": _iss,
                 "assumed_hl": _assumed_hl, "sheets": len(sheets)}]

    # ---- 每 sheet 拆一张独立报表(单 sheet,或多 sheet + merge=False)----
    rows = []
    for s in sheets:
        # 多 sheet 命名去冗余:帆软作者常把工作表命名为「报表名」或「报表名-子类」(如
        # 手术室手术情况统计.cpt 的 sheet 名就叫 手术室手术情况统计 / 手术室手术情况统计-介入手术室)。
        # 旧逻辑无脑前缀 cpt 名 → 「手术室手术情况统计_手术室手术情况统计-介入手术室」重复冗长。
        # 故:sheet 名已等于/以 cpt 名开头时,直接用 sheet 名,不再叠前缀。
        _sh = s["sheet"]
        _redun = multi and (_sh == model["name"] or _sh.startswith(model["name"]))
        base0 = (safe_name(_sh) if _redun
                 else ("%s__%s" % (model["name"], safe_name(_sh)) if multi
                       else model["name"]))
        base, rel, mrg, skip = _resolve_dest(dest, subdir, base0, overwrite)
        if skip:
            rows.append({"name": rel, "ok": True, "skipped": True,
                         "cells": 0, "manual": 0, "degraded": 0})
            continue
        issues = list(s["issues"])
        if query:
            issues.extend(query["issues"])
        used_ds = {c["dsName"] for c in s["cells"].values() if c.get("dsName")}
        params = compute_params(model["datasets"], used_ds)
        for pn in (query or {}).get("meta", {}):   # 面板控件参数也登记
            params.setdefault(pn, None)
        report_name = (_sh if _redun
                       else ("%s_%s" % (model["name"], _sh) if multi else model["name"]))
        sm = {"name": model["name"], "cells": s["cells"], "row_h": s["row_h"],
              "col_w": s["col_w"], "datasets": model["datasets"],
              "params": params, "query": query, "report_name": report_name}
        xml_text = map_to_xml(sm, cfg, issues)
        title = (_sh if _redun
                 else ("%s / %s" % (model["name"], _sh) if multi else model["name"]))
        report, n_manual, n_deg, n_cells = write_report(title, sm, issues)
        with open(mrg, "w", encoding="utf-8") as f:
            f.write(xml_text)
        with open(os.path.join(dest, base + ".report.md"), "w",
                  encoding="utf-8") as f:
            f.write(report)
        _iss, _assumed_hl = _issue_rows(issues)
        rows.append({"name": rel, "ok": True, "skipped": False, "cells": n_cells,
                     "manual": n_manual, "degraded": n_deg, "issues": _iss,
                     "assumed_hl": _assumed_hl})
    return rows


_ISSUE_TYPE_RULES = [
    ("数据源未映射",     lambda m: "已默认使用同名数据连接" in m),
    ("SQL未映射函数",    lambda m: "未映射函数" in m and "SQL" in m),
    ("公式未映射函数",   lambda m: "未映射函数" in m),
    ("控件自定义JS",     lambda m: "自定义 JS" in m),
    ("FreeButton自定义按钮", lambda m: "FreeButton" in m),
    ("查询控件不支持",   lambda m: "查询控件" in m and "暂不支持" in m),
    ("字典类型不支持",   lambda m: "字典类型" in m and "暂不支持" in m),
    ("条件高亮未转换",   lambda m: "条件高亮" in m),
    ("富文本/斜线头",    lambda m: ("富文本" in m) or ("斜线头" in m)),
    ("字段需复核",       lambda m: "字段列表为空" in m or "推断字段" in m),
]


def issue_type(msg):
    for t, f in _ISSUE_TYPE_RULES:
        try:
            if f(msg):
                return t
        except Exception:
            pass
    return "其它"


def write_issues_report(outdir, results):
    """聚合所有报表的「待人工/降级」问题 → _issues.csv(Excel可筛选)+ _issues.txt(人读)。
    返回汇总 dict(供 GUI 展示);无问题返回 None。"""
    import csv as _csv
    import collections as _co
    rows_csv, by_type, ds_conn = [], _co.Counter(), _co.Counter()
    for r in results:
        if not r.get("ok"):
            continue
        for it in r.get("issues", []):
            t = issue_type(it["msg"])
            lvl_cn = "待人工" if it["level"] == "manual" else "降级"
            by_type[(it["level"], t)] += 1
            rows_csv.append((r["name"], lvl_cn, it["where"], t, it["msg"]))
            if t == "数据源未映射":
                m = re.search(r"连接「([^」]+)」", it["msg"])
                if m:
                    ds_conn[m.group(1)] += 1
    total_assumed = sum(r.get("assumed_hl", 0) for r in results if r.get("ok"))
    if not rows_csv and not total_assumed:
        return None

    csv_path = os.path.join(outdir, "_issues.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["报表", "级别", "位置", "类型", "说明"])
        w.writerows(rows_csv)

    txt_path = os.path.join(outdir, "_issues.txt")
    L = ["帆软转换 — 待处理问题清单", "=" * 46, "",
         "共 %d 条(明细见同目录 _issues.csv,可用 Excel 按「类型/报表」筛选排序)" % len(rows_csv),
         "", "【按类型汇总】"]
    for (lvl, t), c in by_type.most_common():
        L.append("  %5d  [%s] %s" % (c, "待人工" if lvl == "manual" else "降级", t))
    if total_assumed:
        L += ["", "【已自动转换 · 建议抽查】",
              "  %5d  条件高亮(结构化条件)已按推定运算符语义(=/≠/>/≥/</≤)自动转换。"
              "数据不受影响,仅颜色方向需抽查;明细见 _issues.csv 同名报表的 renderItem。" % total_assumed]
    if ds_conn:
        L += ["", "【数据源未确认映射 — 已默认使用帆软同名连接,如目标系统连接名不同,"
                  "在转换器里改一次即可解决其全部报表】"]
        for conn, c in ds_conn.most_common():
            L.append("  连接「%s」:%d 张报表用到 → 默认沿用同名连接,如不同请调整" % (conn, c))
    # 逐条明细(按报表;排除已在上面聚合的「数据源未映射」,避免重复刷屏);超量则截断指向 CSV
    detail = [x for x in rows_csv if x[3] != "数据源未映射"]
    L += ["", "【逐条明细(按报表;数据源类见上面聚合)】"]
    CAP = 4000
    cur = None
    for i, (name, lvl, where, t, msg) in enumerate(detail):
        if i >= CAP:
            L.append("  …… 其余 %d 条见 _issues.csv" % (len(detail) - CAP))
            break
        if name != cur:
            L.append(""); L.append("◆ " + name); cur = name
        L.append("   - [%s] %s @ %s — %s" % (lvl, t, where, msg))
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")

    return {
        "csv": csv_path, "txt": txt_path, "count": len(rows_csv),
        "by_type": [{"level": l, "type": t, "count": c} for (l, t), c in by_type.most_common()],
        "datasource_conns": [{"conn": c0, "reports": c1} for c0, c1 in ds_conn.most_common()],
        "assumed_highlights": total_assumed,
    }


def _tool_version():
    try:
        import version as _ver
        return _ver.full_version()
    except Exception:
        return "unknown"


def main():
    ap = argparse.ArgumentParser(description="帆软 .cpt → sight-report 网格报表转换器")
    ap.add_argument("--version", action="version",
                    version="finereport-import %s" % _tool_version())
    ap.add_argument("input", help="单个 .cpt 文件或目录")
    ap.add_argument("-o", "--out", default="./out", help="输出目录(默认 ./out)")
    ap.add_argument("-c", "--config", default=None, help="配置 JSON(连接映射等)")
    ap.add_argument("--zip", default=None,
                    help="把转出的 .mrg 按目录树打包到此 zip,供报表系统 /import 一次性批量导入")
    ap.add_argument("--split-sheets", action="store_true",
                    help="多 sheet 的 .cpt 拆成多张独立 .mrg(默认合并为单个多页签报表)")
    args = ap.parse_args()
    cfg = load_config(args.config)
    if args.split_sheets:
        cfg["merge_sheets"] = False
    os.makedirs(args.out, exist_ok=True)

    pairs = []  # (cpt路径, 相对子目录)
    if os.path.isdir(args.input):
        root = os.path.abspath(args.input)
        for dp, _, fns in os.walk(args.input):
            for fn in fns:
                if fn.lower().endswith(".cpt"):
                    rel = os.path.relpath(dp, root)
                    pairs.append((os.path.join(dp, fn), "" if rel == "." else rel))
    else:
        pairs.append((args.input, ""))

    results = []
    for fp, sub in sorted(pairs):
        results.extend(convert_one(fp, args.out, cfg, sub))

    if args.zip:
        import zipfile
        with zipfile.ZipFile(args.zip, "w", zipfile.ZIP_DEFLATED) as z:
            for dp, _, fns in os.walk(args.out):
                for fn in fns:
                    if fn.endswith(".mrg"):
                        full = os.path.join(dp, fn)
                        z.write(full, os.path.relpath(full, args.out))
        print("已打包可导入 zip:%s" % args.zip)

    ok = [r for r in results if r["ok"]]
    bad = [r for r in results if not r["ok"]]
    print("转换完成:成功 %d / 失败 %d(输入 %d 个文件,展开 %d 张报表)"
          % (len(ok), len(bad), len(pairs), len(results)))
    for r in results:
        if r["ok"]:
            print("  ✓ %-34s 单元格%-4d 待人工%-2d 降级%-2d"
                  % (r["name"], r["cells"], r["manual"], r["degraded"]))
        else:
            print("  ✗ %-34s %s" % (r["name"], r["error"]))
    if len(results) > 1:
        with open(os.path.join(args.out, "_summary.md"), "w",
                  encoding="utf-8") as f:
            f.write("# 批量转换汇总\n\n成功 %d / 失败 %d\n\n" % (len(ok), len(bad)))
            f.write("| 报表 | 单元格 | 待人工 | 降级 | 状态 |\n|---|---|---|---|---|\n")
            for r in results:
                if r["ok"]:
                    f.write("| %s | %d | %d | %d | ✓ |\n"
                            % (r["name"], r["cells"], r["manual"], r["degraded"]))
                else:
                    f.write("| %s | - | - | - | ✗ %s |\n" % (r["name"], r["error"]))
    # 聚合问题清单(待处理可在此 txt/csv 查看)
    summ = write_issues_report(args.out, results)
    if summ:
        print("待处理问题清单:%s(共 %d 条;另有 _issues.csv 可 Excel 筛选)"
              % (summ["txt"], summ["count"]))


if __name__ == "__main__":
    main()
