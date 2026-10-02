# -*- coding: utf-8 -*-
"""帆软决策报表 .frm → SightReport 仪表盘 .mrs(语义化转换,不是机械 1:1)。

转换思路(每条都对应一个「帆软做法 → 仪表盘惯用做法」的取舍,逐条写进 .report.md):
  * 仪表盘(Gauge/Meter)图 → KPI 指标卡:一行多个占比仪表盘在仪表盘产品里就是指标卡;卡片位置按原版面推断
  * 柱/线/面积/饼 VanChart → chart 区块(数据绑定 + 聚合),不搬样式(配色走主题)
  * ElementCaseEditor(嵌入的报表块) → table 区块:字典翻译(DictPresent)并进 SQL、公式列改写成 SQL 计算列、
    隐藏列(宽 0)与序号列去掉、合计行改成「合计数据集」(占比列也能算对)、斑马纹丢弃(表格自带)
  * 查询面板(WParameterLayout)→ filterBar,控件复用 .cpt 的查询控件转换
  * 版面:按控件绝对坐标聚成「行」,宽度按比例→ size,KPI 行固定 108、表格行自适应高度
"""
import hashlib
import html
import json
import os
import re
import xml.etree.ElementTree as ET

import convert as C

KPI_H = 108
GAP = 12


# ---------------------------------------------------------------- 小工具
def _kids(e, tag):
    return [x for x in e if C.local(x.tag) == tag]


def _first(e, tag):
    for x in e:
        if C.local(x.tag) == tag:
            return x
    return None


def _cls(e):
    return (e.get("class") or "").rsplit(".", 1)[-1]


def _txt(e):
    return ("".join(e.itertext()).strip()) if e is not None else ""


def _strip_q(s):
    """帆软标题常是公式字面量 ="  标题"(或 =\"..\" 转义),去掉引号与首尾空白。"""
    s = (s or "").strip()
    if s.startswith("="):
        s = s[1:].strip()
    s = s.replace('\\"', '"')
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1]
    return s.strip()


_UNIT_RE = re.compile(r"\s*[(（]\s*([^()（）]{1,6})\s*[)）]\s*$")


def _split_unit(title):
    """'当天药占比(%)' → ('当天药占比', '%')"""
    m = _UNIT_RE.search(title or "")
    if m:
        return title[:m.start()].strip(), m.group(1).strip()
    return (title or "").strip(), ""


def _bounds(bw):
    b = _first(bw, "BoundsAttr")
    if b is None:
        return None
    g = lambda k: int(float(b.get(k) or 0))
    return g("x"), g("y"), g("width"), g("height")


def _safe_alias(s):
    s = re.sub(r"[^0-9A-Za-z_]", "_", s or "")
    return s.lower() or "c"


# ---------------------------------------------------------------- 版面控件收集
def _wname(inner):
    e = _first(inner, "WidgetName")
    return e.get("name") if e is not None else ""


def _winvisible(inner):
    e = _first(inner, "WidgetAttr")
    return e is not None and e.get("invisible") == "true"


def _collect(node, ox, oy, out, in_param=False):
    for bw in node:
        if C.local(bw.tag) != "Widget":
            continue
        inner = _first(bw, "InnerWidget")
        b = _bounds(bw)
        if inner is None or b is None:
            continue
        x, y, w, h = b
        k = _cls(inner)
        if k == "WTitleLayout":
            title, body = "", None
            for sub in _kids(inner, "Widget"):
                si = _first(sub, "InnerWidget")
                if si is None:
                    continue
                if _cls(si) == "Label":
                    title = _strip_q(_txt(_first(_first(si, "widgetValue"), "O")
                                          if _first(si, "widgetValue") is not None else None))
                else:
                    body = si
            if body is not None:
                out.append({"inner": body, "kind": _cls(body), "title": title,
                            "x": ox + x, "y": oy + y, "w": w, "h": h, "param": in_param,
                            "name": _wname(body), "invisible": _winvisible(body)})
        elif k.endswith("Layout"):
            _collect(inner, ox + x, oy + y, out, in_param or k == "WParameterLayout")
        else:
            out.append({"inner": inner, "kind": k, "title": "", "x": ox + x, "y": oy + y,
                        "w": w, "h": h, "param": in_param,
                        "name": _wname(inner), "invisible": _winvisible(inner)})


def _find_layouts(root):
    """frm 的 Layout 根(WBorderLayout)下各区域:返回 [(region_tag, element, is_param)]"""
    lay = next((e for e in root.iter() if C.local(e.tag) == "Layout"
                and _cls(e) == "WBorderLayout"), None)
    res = []
    if lay is None:
        return res
    for ch in lay:
        if ch.get("class") and C.local(ch.tag) in ("North", "Center", "South", "East", "West"):
            res.append((C.local(ch.tag), ch, _cls(ch) == "WParameterLayout"))
    return res


# ---------------------------------------------------------------- 数据集
def _embedded_ds(root):
    d = {}
    for td in root.iter():
        if C.local(td.tag) == "TableData" and "EmbeddedTableData" in td.get("class", ""):
            d[td.get("name")] = True
    return d


class Ctx:
    def __init__(self, root, cfg, issues, name):
        self.root, self.cfg, self.issues, self.name = root, cfg, issues, name
        self.ds = C._collect_datasets(root)            # 本 frm 内的 SQL 数据集
        self.embedded = _embedded_ds(root)
        self.server = C._server_datasets(cfg) or {}
        self.scroll_names = _autoscroll_names(root)
        self.named = {}                                # 控件名 → 收集项(供图表取报表块单元格)
        self.out_ds = {}                               # 名 → {sql, conn, fields{name:(type,label)}}
        self.num = {}
        self.col_alias = {}                            # (数据集, 列名小写) → 补的别名(源 SQL 里未命名的表达式列)
        self.pub_noted = set()
        self.refs = {}                                 # 源数据集名 → 引用到的列(小写→原写)
        self.blocks = []                               # 区块 dict
        self.seq = {"k": 0, "c": 0, "t": 0, "x": 0, "m": 0}

    def bid(self, p):
        self.seq[p] += 1
        return "%s%d" % (p, self.seq[p])

    def src(self, dsname):
        d = self.ds.get(dsname) or self.server.get(dsname)
        return d

    def alias_col(self, dsname, col):
        """源 SQL 里未起别名的表达式列(帆软列名形如 SUM(DVALUE)、ROUND(a/b,2)、sum("1"))不是合法字段名,
        仪表盘按字段名取数/外包 SQL 都会坏 → 在源 SQL 的列清单里给它补 `as c_xxx`,返回别名。
        普通标识符返回 None;补不上(找不到原文)记待人工并返回 None。同一列只补一次,所有区块共用。"""
        if re.fullmatch(r"\w+", col or ""):
            return None                                  # 含纯数字名(PIVOT 出来的 2021):是真列,引用时加引号即可
        key = (dsname, col.lower())
        if key in self.col_alias:
            return self.col_alias[key]
        d = self.src(dsname)
        alias = None
        if d is not None and d.get("sql"):
            pat = re.compile(r"(?i)(?<![\w.\"])" + r"\s*".join(re.escape(ch) for ch in re.sub(r"\s+", "", col))
                             + r"(?=\s*(?:,|\bfrom\b))")
            al = "c_" + _safe_alias(col).strip("_")
            used = {v for (dn, _c), v in self.col_alias.items() if dn == dsname and v}
            base_al, i = al, 1
            while al in used:                            # 不同列清洗后同名(纯中文名等)→ 加序号
                i += 1
                al = "%s_%d" % (base_al, i)
            new, n = pat.subn(lambda m: m.group(0) + " as " + al, d["sql"], count=1)
            if n:
                d["sql"] = new
                if dsname in self.out_ds:
                    self.out_ds[dsname]["sql"] = new
                alias = al
        if alias is None and d is not None and d.get("sql"):
            self.issues.append(C.Issue("manual", "数据集:" + dsname,
                                       "源 SQL 中未命名的表达式列 %s 无法自动补别名,引用它的区块会取不到数,请手工给该列加别名" % col))
        self.col_alias[key] = alias
        return alias

    def ref(self, dsname, col, num=False):
        al = self.alias_col(dsname, col)
        if al:
            col = al
        self.refs.setdefault(dsname, {}).setdefault(col.lower(), col)
        if num:
            self.num.setdefault(dsname, set()).add(col.lower())

    def field_name(self, dsname, col):
        """帆软列名大小写不敏感:优先 SQL 推断出的原列名。"""
        al = self.col_alias.get((dsname, (col or "").lower()))
        if al:
            return al
        d = self.src(dsname)
        if d is not None:
            inf = C.fields_from_sql(d.get("sql") or "")
            for f in inf:
                if f.lower() == col.lower():
                    return f
        return col

    def need_ds(self, dsname, where):
        """区块引用了数据集:本 frm 内有 SQL 定义→嵌入;否则假定同名公共数据集(按名引用)或标待人工。"""
        if dsname in self.out_ds:
            return True
        d = self.src(dsname)
        if d is not None and d.get("sql"):
            self.out_ds[dsname] = {"sql": d["sql"], "conn": d.get("conn"), "orig": dsname, "fields": {}}
            return True
        if dsname in self.embedded:
            self.issues.append(C.Issue("manual", where,
                                       "数据集「%s」是帆软内嵌静态数据(已加密存储,无法还原),需手工补数据或换成 SQL" % dsname))
            return False
        if self.cfg.get("assume_public_datasets", True):
            C._note_public_ref(dsname, where)
            if dsname not in self.pub_noted:
                self.pub_noted.add(dsname)
                self.issues.append(C.Issue("manual", "数据集:" + dsname,
                                           "服务器数据集,区块按同名引用;请在仪表盘里「引用公共数据集」同名数据集(转换器无法把它拷进模板)"))
            return True
        self.issues.append(C.Issue("manual", where, "数据集「%s」不在 .frm 内(服务器数据集),需补充" % dsname))
        return False


# ---------------------------------------------------------------- 图表/仪表盘 → 区块
_PLOT_MAP = {"VanChartColumnPlot": ("bar", {}), "VanChartBarPlot": ("bar", {"horizontal": True}),
             "VanChartLinePlot": ("line", {}), "VanChartAreaPlot": ("area", {}),
             "PiePlot4VanChart": ("pie", {}), "PiePlot": ("pie", {}),
             "VanChartRadarPlot": ("radar", {}), "RadarPlot": ("radar", {}),
             "RangePlot": ("area", {}),
             "Bar2DPlot": ("bar", {}), "Donut3DPlot": ("pie", {"pieRing": True})}


def _qn(n):
    """列名引用:纯标识符原样,以数字开头或含特殊字符的加双引号(2001 → "2001")"""
    return n if re.fullmatch(r"[A-Za-z_]\w*", n) else '"%s"' % n


def _report_cell_map(inner):
    """报表块单元格 → {(col,row): ("ds",数据集,列) | ("f",公式) | ("t",文本)}"""
    fec = _first(inner, "FormElementCase")
    cl = _first(fec, "CellElementList") if fec is not None else None
    m = {}
    for c in (_kids(cl, "C") if cl is not None else []):
        o = _first(c, "O")
        a = _first(o, "Attributes") if o is not None else None
        if o is None:
            continue
        key = (int(c.get("c")), int(c.get("r")))
        t = o.get("t")
        if t == "DSColumn" and a is not None:
            m[key] = ("ds", a.get("dsName"), a.get("columnName"))
        elif t == "Formula":
            m[key] = ("f", _txt(a))
        else:
            m[key] = ("t", _txt(o))
    return m


def _cell_resolver(cm):
    """报表块单元格 → SQL 表达式解析器。返回 (cellsql(col,row), 用到的数据集集合, 用到的(数据集,列)列表)。
    数据集列 → t.列;文字 → 字面量;公式 → 递归改写(sum/avg/... 聚合照写,数据行引用即 t.列)。"""
    dss, used_cols, stack = set(), [], set()

    def cellsql(cc, rr):
        v = cm.get((cc, rr))
        if v is None:
            raise _ExprFail("empty")
        if (cc, rr) in stack:
            raise _ExprFail("loop")
        if v[0] == "ds":
            dss.add(v[1])
            used_cols.append((v[1], v[2]))
            return "t.%s" % _qn(v[2])
        if v[0] == "t":
            return v[1] if re.fullmatch(r"-?\d+\.?\d*", v[1]) else "'%s'" % v[1].replace("'", "''")
        stack.add((cc, rr))
        try:
            return _P(_tokenize(v[1].lstrip("=")), cellsql,
                      lambda fn, inner: "%s(%s)" % (fn, inner)).parse()
        finally:
            stack.discard((cc, rr))
    return cellsql, dss, used_cols


def _cell_report_chart(ctx, it, where, title, pcls, defn):
    """数据取自(隐藏)报表块单元格的图表 → 把「系列名单元格/值单元格」翻成 SQL,union all 成 (指标名,值) 长表数据集。
    只支持:每个系列 = 一个名字单元格 + 一个值单元格,值单元格是数据集列或可改写成 SQL 的算术公式。"""
    ctype, extra = _PLOT_MAP[pcls]
    ref_re = re.compile(r"^=?\s*(\w+)~\$?([A-Za-z]{1,2})\$?(\d+)\s*$")
    series = []                                                # [(name_ref|literal, value_ref)]
    for sd in defn.iter():
        if C.local(sd.tag) != "SeriesDefinition":
            continue
        pair = []
        for tag in ("SeriesName", "SeriesValue"):
            e = _first(sd, tag)
            o = _first(e, "O") if e is not None else None
            a = _first(o, "Attributes") if o is not None and o.get("t") == "Formula" else None
            if a is not None:
                m = ref_re.match(_txt(a))
                pair.append(("ref", m.groups()) if m else ("expr", _txt(a)))
            else:
                pair.append(("lit", _txt(o) if o is not None else ""))
        series.append(pair)
    if not series:
        return None, "图表数据定义没有系列"
    names = {p[0][1][0] for p in series if p[0][0] == "ref"} | {p[1][1][0] for p in series if p[1][0] == "ref"}
    if len(names) != 1:
        return None, "系列引用了 %d 个不同的报表块(%s)" % (len(names), ",".join(sorted(names)) or "无")
    rep = ctx.named.get(next(iter(names)))
    if rep is None or rep["kind"] != "ElementCaseEditor":
        return None, "找不到供数的报表块「%s」" % next(iter(names))
    cm = _report_cell_map(rep["inner"])
    cellsql, dss, used_cols = _cell_resolver(cm)
    parts = []
    unnamed = 0
    try:
        for nm, vl in series:
            if nm[0] == "ref" and vl[0] == "ref" and (_col_idx(nm[1][1]), int(nm[1][2]) - 1) not in cm \
                    and (_col_idx(vl[1][1]), int(vl[1][2]) - 1) not in cm:
                continue                                       # 名字和值单元格都是空的系列(帆软不画)
            if nm[0] == "lit":
                label = nm[1]
            elif nm[0] == "ref":
                cc, rr = _col_idx(nm[1][1]), int(nm[1][2]) - 1
                v = cm.get((cc, rr))
                if v is None:                                  # 有值无名的系列:帆软画成无名柱
                    unnamed += 1
                    label = "系列%d" % (len(parts) + 1)
                elif v[0] != "t":
                    return None, "系列名单元格不是固定文字"
                else:
                    label = v[1]
            else:
                return None, "系列名是公式"
            if vl[0] != "ref":
                return None, "系列值不是单元格引用"
            parts.append((label, cellsql(_col_idx(vl[1][1]), int(vl[1][2]) - 1)))
    except (_ExprFail, IndexError) as e:
        return None, "值单元格公式无法改写成 SQL(%s)" % e
    if not parts:
        return None, "所有系列的单元格都是空的"
    if len(dss) != 1:
        return None, "值单元格来自 %d 个数据集" % len(dss)
    ds = next(iter(dss))
    if not ctx.need_ds(ds, where):
        return None, None
    src = ctx.src(ds)
    if src is None or not src.get("sql") or ds not in ctx.out_ds:
        return None, "数据集「%s」在服务器侧,无法改写" % ds
    for d, col in used_cols:
        ctx.ref(d, col, True)
    base = "%s_图表%d" % (ds, ctx.seq["c"] + 1)
    body = src["sql"].strip().rstrip(";")
    un = " union all\n".join("select '%s' as idx_name, (%s) as idx_value from (\n%s\n) t"
                             % (l.replace("'", "''"), e, body) for l, e in parts)
    ctx.out_ds[base] = {"sql": un, "conn": src.get("conn"), "orig": ds, "derived": True,
                        "fields": {"idx_name": ("String", "指标"), "idx_value": ("BigDecimal", "值")}}
    props = {"datasetName": base, "chartType": ctype, "dimensionField": "idx_name",
             "valueField": "idx_value", "aggregation": "sum"}
    props.update(extra)
    ctx.issues.append(C.Issue("info", where, "图表数据来自报表块「%s」的单元格,已把 %d 个系列的取值翻成 SQL,生成长表数据集「%s」"
                              % (rep["name"], len(parts), base)))
    if unnamed:
        ctx.issues.append(C.Issue("manual", where, "有 %d 个系列的名字单元格是空的,已命名为「系列N」,请核对" % unnamed))
    return {"id": ctx.bid("c"), "type": "chart", "title": title or "", "props": props, "it": it,
            "dsref": (base, "idx_value")}, None


def _expr_meter_kpi(ctx, it, where, title, unit, dsname, defn, value):
    """仪表盘取值是表达式(SUM(ZC) / SY/YZ / 带汇总函数的列)→ 单行数据集 + KPI。不认识的表达式返回 None。"""
    fn_map = {"SumFunction": "sum", "AverageFunction": "avg", "MaxFunction": "max", "MinFunction": "min", "CountFunction": "count"}
    text, fn = value, ""
    if defn is not None and C.local(defn.tag) == "MoreNameCDDefinition":
        sc = next((e for e in defn.iter() if C.local(e.tag) == "ChartSummaryColumn"), None)
        if sc is None:
            return None
        text, fn = sc.get("name") or "", fn_map.get((sc.get("function") or "").rsplit(".", 1)[-1], "")
    text = (text or "").strip()
    ident = r"[A-Za-z_]\w*"
    m1 = re.fullmatch(r"(?i)(sum|avg|max|min|count)\(\s*(%s)\s*\)" % ident, text)
    m2 = re.fullmatch(r"(%s)\s*/\s*(%s)" % (ident, ident), text)
    if m1:
        expr, ratio = "%s(t.%s)" % (m1.group(1).lower(), m1.group(2)), False
        cols = [m1.group(2)]
    elif m2:
        a, b = m2.group(1), m2.group(2)
        pre = lambda c: "%s(t.%s)" % (fn, c) if fn else "t.%s" % c
        expr, ratio = "%s / nullif(%s, 0)" % (pre(a), pre(b)), True
        cols = [a, b]
    elif re.fullmatch(ident, text) and fn:
        expr, ratio, cols = "%s(t.%s)" % (fn, text), False, [text]
    else:
        return None
    if not ctx.need_ds(dsname, where):
        return None
    src = ctx.src(dsname)
    if src is None or not src.get("sql") or dsname not in ctx.out_ds:
        return None
    for c in cols:
        ctx.ref(dsname, c, True)
    if ratio and not unit:
        expr, unit = "(%s) * 100" % expr, "%"
    base = "%s_指标卡%d" % (dsname, ctx.seq["k"] + 1)
    ctx.out_ds[base] = {"sql": "select (%s) as idx_value from (\n%s\n) t" % (expr, src["sql"].strip().rstrip(";")),
                        "conn": src.get("conn"), "orig": dsname, "derived": True,
                        "fields": {"idx_value": ("BigDecimal", title or "值")}}
    props = {"datasetName": base, "valueField": "idx_value", "precision": 1 if unit == "%" else 0}
    if unit:
        props["unit"] = unit
    ctx.issues.append(C.Issue("manual" if ratio else "info", where, "仪表盘取值「%s」是表达式,已翻成 SQL 单行数据集「%s」并转 KPI 指标卡%s"
                              % (text, base, "。取值是两数之比,已按 ×100 显示为百分比;若它其实是均值(如人均××)请去掉 % 单位并去掉 ×100" if ratio else "")))
    return {"id": ctx.bid("k"), "type": "kpi", "title": title or "指标", "props": props, "it": it,
            "dsref": (base, "idx_value")}


def _cell_meter_kpi(ctx, it, where, title, unit, defn):
    """仪表盘取值于报表块单元格(=report0~H3,H3 常是 =D3/C3 或 =sum(B4) 之类)→ 单行数据集 + KPI 指标卡。失败返回 None 走原有待人工。"""
    mv = next((e for e in defn.iter() if C.local(e.tag) == "meterDefinitionValue"), None)
    a = next((e for e in mv.iter() if C.local(e.tag) == "Attributes"), None) if mv is not None else None
    m = re.match(r"^=?\s*(\w+)~\$?([A-Za-z]{1,2})\$?(\d+)\s*$", _txt(a)) if a is not None else None
    rep = ctx.named.get(m.group(1)) if m else None
    if rep is None or rep["kind"] != "ElementCaseEditor":
        return None
    cm = _report_cell_map(rep["inner"])
    cellsql, dss, used = _cell_resolver(cm)
    try:
        expr = cellsql(_col_idx(m.group(2)), int(m.group(3)) - 1)
    except (_ExprFail, IndexError):
        return None
    if len(dss) != 1:
        return None
    ds = next(iter(dss))
    if not ctx.need_ds(ds, where):
        return None
    src = ctx.src(ds)
    if src is None or not src.get("sql") or ds not in ctx.out_ds:
        return None
    for d, col in used:
        ctx.ref(d, col, True)
    ratio = "/ nullif(" in expr
    if ratio and not unit:
        expr, unit = "(%s) * 100" % expr, "%"                  # 比率指标:帆软按百分比显示,指标卡按 ×100 的数 + %
    base = "%s_指标卡%d" % (ds, ctx.seq["k"] + 1)
    ctx.out_ds[base] = {"sql": "select (%s) as idx_value from (\n%s\n) t" % (expr, src["sql"].strip().rstrip(";")),
                        "conn": src.get("conn"), "orig": ds, "derived": True,
                        "fields": {"idx_value": ("BigDecimal", title or "值")}}
    props = {"datasetName": base, "valueField": "idx_value", "precision": 1 if unit == "%" else 0}
    if unit:
        props["unit"] = unit
    ctx.issues.append(C.Issue("manual" if ratio else "info", where, "仪表盘取值于报表块「%s」的单元格,已翻成 SQL 单行数据集「%s」并转 KPI 指标卡%s"
                              % (rep["name"], base, "。取值是两数之比,已按 ×100 显示为百分比;若它其实是均值(如人均××)请去掉 % 单位并去掉 ×100" if ratio else "")))
    return {"id": ctx.bid("k"), "type": "kpi", "title": title or "指标", "props": props, "it": it,
            "dsref": (base, "idx_value")}


def _chart_block(ctx, it):
    where = "图表:" + (it["title"] or _txt(_first(it["inner"], "WidgetName")) or "?")
    inner = it["inner"]
    pcls, dsname, defn, _t = C._chart_summary(inner)
    title, unit = _split_unit(it["title"])
    dn = C.local(defn.tag) if defn is not None else ""
    # ---- 组合图(Custom):取带数据的子定义当主图(其余子定义多为空壳,仅占位) ----
    if pcls == "VanChartCustomPlot" and dn == "CustomDefinition":
        _KEY = {"column": "VanChartColumnPlot", "bar": "VanChartBarPlot", "line": "VanChartLinePlot", "area": "VanChartAreaPlot"}
        withdata = []
        for dm in defn.iter():
            if C.local(dm.tag) == "DefinitionMap" and dm.get("key") in _KEY:
                sub = next(iter(dm), None)
                if sub is not None and any(C.local(e.tag) == "ChartSummaryColumn" for e in sub.iter()):
                    withdata.append((dm.get("key"), sub))
        if withdata:
            key0, sub = withdata[0]
            defn, dn, pcls = sub, C.local(sub.tag), _KEY[key0]
            dsname = C.defn_dataset_name(sub) or dsname
            ctx.issues.append(C.Issue("info", where, "组合图按其中带数据的「%s」系列转成单一图表,其余空系列忽略" % key0))
            if len(withdata) > 1:
                ctx.issues.append(C.Issue("manual", where, "组合图还有 %d 个带数据的系列(%s)未转,需在设计器里手工加指标"
                                          % (len(withdata) - 1, "、".join(k for k, _ in withdata[1:]))))
    # ---- 仪表盘 → KPI ----
    if pcls in ("VanChartGaugePlot", "MeterPlot"):
        value = None
        if dn == "MeterTableDefinition":
            mt = next((e for e in defn.iter() if C.local(e.tag) == "MeterTable201109"), None)
            value = mt.get("value") if mt is not None else None
        elif dn == "OneValueCDDefinition":
            value = defn.get("valueName")
        if dn == "MeterReportDefinition":
            blk = _cell_meter_kpi(ctx, it, where, title, unit, defn)
            if blk is not None:
                return blk
        if dsname and value and not re.fullmatch(r"\w+", value or "") or (
                dn == "MoreNameCDDefinition" and dsname):
            blk = _expr_meter_kpi(ctx, it, where, title, unit, dsname, defn, value)
            if blk is not None:
                return blk
        if not (dsname and value) or not ctx.need_ds(dsname, where):
            extra = ""
            if dn == "MeterReportDefinition":
                extra = "(取值来自报表块单元格 %s)" % next((_txt(a) for a in defn.iter() if C.local(a.tag) == "Attributes"), "?")
            ctx.issues.append(C.Issue("manual", where, "仪表盘数据定义(%s)%s无法自动转,需手工建指标卡" % (dn, extra)))
            return _text_block(ctx, it, "[待配置] " + it["title"])
        ctx.ref(dsname, value, True)
        props = {"datasetName": dsname, "valueField": ctx.field_name(dsname, value),
                 "precision": 1 if unit == "%" else 0}
        if unit:
            props["unit"] = unit
        ctx.issues.append(C.Issue("info", where,
                                  "仪表盘已转为 KPI 指标卡(仪表盘产品里占比类指标的惯用形态);原图的刻度区间/色带未带"))
        return {"id": ctx.bid("k"), "type": "kpi", "title": title or "指标", "props": props, "it": it,
                "dsref": (dsname, value)}
    # ---- 钻取地图 → map 区块(仅省级) ----
    if pcls in ("VanChartDrillMapPlot", "VanChartMapPlot") and defn is not None:
        ld = next((e for e in defn.iter() if C.local(e.tag) == "MoreNameCDDefinition"), None)
        mds = C.defn_dataset_name(ld) if ld is not None else ""
        cat = C._child_attr(ld, "CategoryName", "value") if ld is not None else ""
        sc = next((e for e in ld.iter() if C.local(e.tag) == "ChartSummaryColumn"), None) if ld is not None else None
        if mds and cat and sc is not None and ctx.need_ds(mds, where):
            AGGM = {"SumFunction": "sum", "AverageFunction": "avg", "MaxFunction": "max", "MinFunction": "min", "CountFunction": "count"}
            fn = (sc.get("function") or "").rsplit(".", 1)[-1]
            f0 = sc.get("name")
            ctx.ref(mds, cat)
            ctx.ref(mds, f0, True)
            props = {"datasetName": mds, "dimensionField": ctx.field_name(mds, cat),
                     "valueField": ctx.field_name(mds, f0), "aggregation": AGGM.get(fn, "sum")}
            ctx.issues.append(C.Issue("manual", where,
                                      "钻取地图已转为 map 区块(仅省级);请确认列「%s」的值是省份名(如「广东省」),市/区县层级不下钻" % cat))
            return {"id": ctx.bid("m"), "type": "map", "title": title or "", "props": props, "it": it,
                    "dsref": (mds, f0)}
    # ---- 数据取自报表块单元格的图表 ----
    if pcls in _PLOT_MAP and dn == "NormalReportDataDefinition":
        blk, why = _cell_report_chart(ctx, it, where, title, pcls, defn)
        if blk is not None:
            return blk
        if why:
            ctx.issues.append(C.Issue("manual", where, "图表数据取自报表块单元格,%s,无法自动转,已留占位,需手工建图表" % why))
        return _text_block(ctx, it, "[待配置图表] " + it["title"])
    # ---- 柱/线/面积/饼 ----
    if pcls in _PLOT_MAP and defn is not None and dsname:
        if not ctx.need_ds(dsname, where):                     # 原因已在 need_ds 里记过
            return _text_block(ctx, it, "[待配置图表] " + it["title"])
        ctype, extra = _PLOT_MAP[pcls]
        if pcls == "RangePlot":
            ctx.issues.append(C.Issue("info", where, "区间图(RangePlot)按面积图转,「上下界之间的区间」语义没带,请核对"))
        cat = C._child_attr(defn, "CategoryName", "value") or ""
        if cat == "无":
            cat = ""
        props = {"datasetName": dsname, "chartType": ctype}
        props.update(extra)
        AGG = {"SumFunction": "sum", "AverageFunction": "avg", "MaxFunction": "max",
               "MinFunction": "min", "CountFunction": "count"}
        measures = []                                          # [(field, label, fn)]
        series = ""
        if dn == "MoreNameCDDefinition":
            for c in _kids(defn, "ChartSummaryColumn"):
                measures.append((c.get("name"), c.get("customName") or c.get("name"),
                                 c.get("function", "").rsplit(".", 1)[-1]))
        elif dn == "OneValueCDDefinition":
            series = defn.get("seriesName") or ""
            measures.append((defn.get("valueName"), defn.get("valueName"), "SumFunction"))
            cat = cat or series
            if series and series == cat:
                series = ""
        if not measures:
            ctx.issues.append(C.Issue("manual", where, "图表数据定义(%s,%s)无指标,无法自动转,需手工建图表" % (pcls, dn)))
            return _text_block(ctx, it, "[待配置图表] " + it["title"])
        for _nm in [m[0] for m in measures] + [cat, series]:
            if _nm:
                ctx.alias_col(dsname, _nm)                         # 先给未命名表达式列补别名,后面的 SQL 才引用得到
        base = dsname
        src = ctx.src(dsname)
        local_sql = src is not None and bool(src.get("sql")) and dsname in ctx.out_ds
        qn = _qn
        if not cat:
            # 「宽表一行多指标」(每个指标一根柱/一块扇区):SQL 反透视成 (指标名, 值) 长表,区块才有分类轴
            if not local_sql:
                ctx.issues.append(C.Issue("manual", where,
                                          "图表是「单行多指标」宽表结构,数据集在服务器侧无法改写,需手工建图表(或把数据集改成长表)"))
                return _text_block(ctx, it, "[待配置图表] " + it["title"])
            base = "%s_指标" % dsname
            def _unp(f, fn):
                col = "t." + qn(ctx.field_name(dsname, f))
                a = AGG.get(fn)
                return "%s(%s)" % (a, col) if a in ("avg", "max", "min", "count") else col   # sum/缺省:原样,区块端再 sum
            un = " union all\n".join("select '%s' as idx_name, %s as idx_value from (\n%s\n) t"
                                      % (l.replace("'", "''"), _unp(f, _fn), src["sql"].strip().rstrip(";"))
                                      for f, l, _fn in measures)
            ctx.out_ds[base] = {"sql": un, "conn": src.get("conn"), "orig": dsname, "derived": True,
                                "fields": {"idx_name": ("String", "指标"), "idx_value": ("BigDecimal", "值")}}
            ctx.issues.append(C.Issue("info", where, "单行多指标宽表已反透视成长表数据集「%s」(%d 个指标)" % (base, len(measures))))
            props["datasetName"] = base
            props["dimensionField"], props["valueField"] = "idx_name", "idx_value"
            props["aggregation"] = "sum"
            measures = []
            cat = "idx_name"
        else:
            ctx.ref(dsname, cat)
        # 分类/系列的字典翻译(SeriesPresent/CategoryPresent):并进 SQL
        dic = None
        for pe in defn.iter():
            if C.local(pe.tag) in ("SeriesPresent", "CategoryPresent") and "DictPresent" in pe.get("class", ""):
                d = _first(pe, "Dictionary")
                fa = _first(d, "FormulaDictAttr") if d is not None else None
                tn = next((_txt(e) for e in d.iter() if C.local(e.tag) == "Name"), "") if d is not None else ""
                if fa is not None and tn:
                    dic = {"ki": fa.get("kiName"), "vi": fa.get("viName"), "ds": tn,
                           "on_series": C.local(pe.tag) == "SeriesPresent"}
                break
        tgt = (series if (dic and dic["on_series"] and series) else cat)
        if dic and measures is not None and tgt and tgt != "idx_name":
            dd = ctx.src(dic["ds"])
            if local_sql and dd is not None and dd.get("sql"):
                nb = "%s_字典" % base
                ncol = _safe_alias(tgt) + "_mc"
                k = 1
                while nb in ctx.out_ds and ctx.out_ds[nb].get("tgt") != (tgt, dic["ds"]):
                    k += 1                                   # 同一数据集上翻译不同列/用不同字典 → 另起一个数据集
                    nb = "%s_字典%d" % (base, k)
                if nb not in ctx.out_ds:
                    flds = {f: ("BigDecimal" if f.lower() in ctx.num.get(dsname, set()) or f.lower() in {m[0].lower() for m in measures} else "String", f)
                            for f in C.fields_from_sql(src["sql"])}
                    for f, _l, _fn in measures:
                        flds.setdefault(ctx.field_name(dsname, f), ("BigDecimal", f))
                    flds[tgt] = flds.get(tgt, ("String", tgt))
                    flds[ncol] = ("String", tgt)
                    ctx.out_ds[nb] = {"sql": "select t.*, d.%s as %s\nfrom (\n%s\n) t\nleft join (\n%s\n) d on t.%s = d.%s"
                                      % (dic["vi"], ncol, src["sql"].strip().rstrip(";"), dd["sql"].strip().rstrip(";"), tgt, dic["ki"]),
                                      "conn": src.get("conn"), "orig": dsname, "derived": True, "fields": flds,
                                      "tgt": (tgt, dic["ds"])}
                base = nb
                props["datasetName"] = nb
                if tgt == cat:
                    cat = ncol
                else:
                    series = ncol
                ctx.issues.append(C.Issue("info", where, "类别字典翻译已并入 SQL,生成数据集「%s」(「%s」显示名称而非代码)" % (nb, tgt)))
            else:
                ctx.issues.append(C.Issue("degraded", where, "类别带字典翻译(%s),字典数据集在服务器侧无法并入,图例将显示代码" % dic["ds"]))
        for f, _l, _fn in measures:
            ctx.ref(dsname, f, True)
        if measures:
            props["dimensionField"] = cat if cat.endswith("_mc") else ctx.field_name(dsname, cat)
            f0, l0, fn0 = measures[0]
            props["valueField"] = ctx.field_name(dsname, f0)
            if l0 and l0 != f0:
                props["valueLabel"] = l0
            props["aggregation"] = AGG.get(fn0, "sum")
            if len(measures) > 1 and ctype in ("bar", "line", "area"):
                props["extraMeasures"] = [{"field": ctx.field_name(dsname, f), "label": l or f,
                                           "agg": AGG.get(fn, "sum")} for f, l, fn in measures[1:]]
            elif len(measures) > 1:
                ctx.issues.append(C.Issue("degraded", where, "饼图只取第一个指标,其余指标丢弃"))
        else:
            props["dimensionField"] = props["dimensionField"]
            f0 = props["valueField"]
        if series and ctype in ("bar", "line", "area"):
            ctx.ref(dsname, series)
            props["colorField"] = series if series.endswith("_mc") else ctx.field_name(dsname, series)
        if unit:
            props["unit"] = unit
        dflds = (ctx.out_ds.get(props["datasetName"]) or {}).get("fields")
        if dflds is not None and ctx.out_ds[props["datasetName"]].get("derived"):
            # 派生数据集(字典并表)的 SQL 常是 select *,字段列表推不全:补上区块用到的字段,否则设计器里选不到
            for fk, num in (("dimensionField", False), ("valueField", True), ("colorField", False)):
                if props.get(fk):
                    dflds.setdefault(props[fk], ("BigDecimal" if num else "String", props[fk]))
            for em in props.get("extraMeasures") or []:
                dflds.setdefault(em["field"], ("BigDecimal", em["field"]))
        if ctype == "pie":
            props.setdefault("pieRing", True)       # 仪表盘里环形饼是惯用形态
        ctx.issues.append(C.Issue("info", where,
                                  "图表(%s)已转为 chart 区块,颜色/标签样式走仪表盘主题,未逐项还原" % pcls))
        return {"id": ctx.bid("c"), "type": "chart", "title": title or "", "props": props, "it": it,
                "dsref": (dsname, f0)}
    ctx.issues.append(C.Issue("manual", where,
                              "图表类型 %s(数据定义 %s)暂不支持自动转,已留占位文本区块,需在设计器手工建图表"
                              % (pcls, dn or "?")))
    return _text_block(ctx, it, "[待配置图表:%s] %s" % (pcls, it["title"]))


def _text_block(ctx, it, text, **extra):
    props = {"content": text}
    props.update(extra)
    return {"id": ctx.bid("x"), "type": "text", "title": "", "props": props, "it": it}


# ---------------------------------------------------------------- 报表块 → table 区块
_REF = re.compile(r"^\$?([A-Za-z]{1,2})\$?(\d+)$", re.I)


def _col_idx(letters):
    n = 0
    for ch in letters:
        n = n * 26 + ord(ch.upper()) - 64
    return n - 1


class _ExprFail(Exception):
    pass


_TOK = re.compile(r'\s*("[^"]*"|\d+\.?\d*|[A-Za-z_]+\(|\$?(?![A-Za-z_]+\()[A-Za-z]{1,2}\$?\d+(?::\$?[A-Za-z]{1,2}\$?\d+)?|<>|>=|<=|[<>=+\-*/(),])')


def _tokenize(expr):
    toks, pos, expr = [], 0, expr.strip()
    while pos < len(expr):
        m = _TOK.match(expr, pos)
        if not m:
            raise _ExprFail(expr)
        toks.append(m.group(1))
        pos = m.end()
        while pos < len(expr) and expr[pos].isspace():
            pos += 1
    return toks


class _P:
    """公式 → SQL 表达式的小解析器(算术/比较/IF/聚合)。
    cell(col,row)->sql;agg(func, inner_sql)->sql。字符串字面量只允许出现在 IF 分支里(帆软常用 "/0" 占位),转 null。"""
    CMP = {"=": "=", "<>": "<>", ">": ">", "<": "<", ">=": ">=", "<=": "<="}

    def __init__(self, toks, cell, agg):
        self.t, self.i, self.cell, self.agg = toks, 0, cell, agg

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def eat(self):
        if self.i >= len(self.t):
            raise _ExprFail("eof")
        v = self.t[self.i]
        self.i += 1
        return v

    def expect(self, tok):
        if self.eat() != tok:
            raise _ExprFail(tok)

    def parse(self):
        v = self.cmp()
        if self.peek() is not None:
            raise _ExprFail("trailing")
        return v

    expr = parse

    def cmp(self):
        v = self.add()
        if self.peek() in self.CMP:
            op = self.eat()
            return "%s %s %s" % (v, self.CMP[op], self.add())
        return v

    def add(self):
        v = self.term()
        while self.peek() in ("+", "-"):
            op = self.eat()
            v = "%s %s %s" % (v, op, self.term())
        return v

    def term(self):
        v = self.factor()
        while self.peek() in ("*", "/"):
            op = self.eat()
            r = self.factor()
            v = "1.0 * %s / nullif(%s, 0)" % (v, r) if op == "/" else "%s * %s" % (v, r)   # 1.0*:整数列相除在 PG/SQL Server 会截断
        return v

    def branch(self):
        t = self.peek()
        if t is not None and t.startswith('"'):
            self.eat()
            return "null"
        return self.cmp()

    def factor(self):
        t = self.peek()
        if t is None:
            raise _ExprFail("eof")
        if t == "(":
            self.eat()
            v = self.cmp()
            self.expect(")")
            return "(%s)" % v
        if t == "-":
            self.eat()
            return "-" + self.factor()
        if re.fullmatch(r"\d+\.?\d*", t):
            return self.eat()
        if t.endswith("("):
            fn = self.eat()[:-1].lower()
            if fn == "if":
                c = self.cmp()
                self.expect(",")
                a = self.branch()
                self.expect(",")
                b = self.branch()
                self.expect(")")
                return "(case when %s then %s else %s end)" % (c, a, b)
            if fn in ("sum", "average", "avg", "max", "min", "count"):
                inner = self.cmp()
                self.expect(")")
                return self.agg({"average": "avg"}.get(fn, fn), inner)
            if fn == "proportion":                      # 占比 = 本行 / 该列合计
                v = self.cmp()
                self.expect(")")
                return "(%s) / nullif(sum(%s) over (), 0)" % (v, v)
            if fn == "round":
                v = self.cmp()
                n = "0"
                if self.peek() == ",":
                    self.eat()
                    n = self.eat()
                    if not re.fullmatch(r"\d+", n):
                        raise _ExprFail("round")
                self.expect(")")
                return "round(%s, %s)" % (v, n)
            raise _ExprFail(fn)
        m = _REF.match(t.split(":")[0])
        if m:
            self.eat()
            return self.cell(_col_idx(m.group(1)), int(m.group(2)) - 1)
        raise _ExprFail(t)


def _parse_sizes(el):
    return [int(x) for x in re.findall(r"-?\d+", _txt(el))] if el is not None else []


def _autoscroll_names(root):
    """整张 frm 里「定时滚动 + 悬停暂停」脚本(电视看板)所指的报表块名(小写)。脚本挂在容器上,按脚本里的 widgetname=REPORTn 对号入座。"""
    names = set()
    for e in root.iter():
        if C.local(e.tag) == "Content":
            t = "".join(e.itertext())
            if "setInterval" in t and "frozen-center" in t:
                names |= {m.lower() for m in re.findall(r"widgetname=(\w+)", t, re.I)}
    return names


def _kv_table(ctx, it, cells, data_cells, where, title):
    """竖排「名称 | 值」小块(如 dpsy 的 出院人数/昨日/入院人数…,每行一个数据集列):
    数据单元格落在同一列的多个不同行 → 逐行生成 (指标名, 值) 的 union all 长表,而不是只取第一行。
    值单元格可以是数据集列(取 max,单行数据集即该值)或引用同列其它行的公式(如 =sum(B1+B3));
    不是这种形状返回 None 走常规表格。"""
    rows = sorted({k[0] for k, _ in data_cells})
    cols = {k[1] for k, _ in data_cells}
    if len(rows) < 2 or len(cols) != 1:
        return None
    vc = next(iter(cols))
    scalar_ref = {}

    def label_of(r):
        for c in sorted(c for (rr, c) in cells if rr == r and c < vc):
            v = cells[(r, c)]
            if v["kind"] in ("text", "formula") and v["val"].strip():
                t = v["val"].strip()
                m = re.fullmatch(r'=\s*"(.*)"', t)
                return (m.group(1) if m else t).strip()
        return ""

    srcs = {}

    def src_of(ds):
        if not ctx.need_ds(ds, where):
            raise _ExprFail("src")
        d = ctx.src(ds)
        if d is None or not d.get("sql") or ds not in ctx.out_ds:
            raise _ExprFail("src")
        srcs[ds] = d
        return d["sql"].strip().rstrip(";")

    def scalar(cc, rr):
        v = cells.get((rr, cc))
        if v is None or v["kind"] == "empty":
            raise _ExprFail("empty")
        if v["kind"] == "ds":
            ctx.ref(v["ds"], v["col"], True)
            return "(select max(t.%s) from (\n%s\n) t)" % (_qn(v["col"]), src_of(v["ds"]))
        if v["kind"] == "formula":
            return _P(_tokenize(v["val"].lstrip("=")), scalar, lambda fn, inner: inner).parse()
        raise _ExprFail("text")
    parts = []
    first_src = None
    vrows = sorted(r for (r, c) in cells if c == vc and cells[(r, c)]["kind"] in ("ds", "formula"))
    raw = [label_of(r) for r in vrows]
    labels, last = [], ""
    for i, lb in enumerate(raw):                      # 重名标签(今日/昨日交替排列时的「昨日」)前缀上最近一个不重名的标签
        if lb and raw.count(lb) > 1 and last:
            lb = "%s·%s" % (last, lb)
        elif lb:
            last = lb
        labels.append(lb or "项%d" % (i + 1))
    try:
        for r, lb in zip(vrows, labels):
            v = cells[(r, vc)]
            lb = lb.replace("'", "''")
            if v["kind"] == "ds":
                src = src_of(v["ds"])
                ctx.ref(v["ds"], v["col"], True)
                first_src = first_src or src
                parts.append("select '%s' as idx_name, max(t.%s) as idx_value from (\n%s\n) t" % (lb, _qn(v["col"]), src))
            else:
                e = scalar(vc, r)
                if first_src is None:
                    first_src = next(iter(srcs.values()))["sql"].strip().rstrip(";")
                parts.append("select '%s' as idx_name, max(0) + %s as idx_value from (\n%s\n) t" % (lb, e, first_src))
    except (_ExprFail, IndexError):
        return None
    conns = {d.get("conn") for d in srcs.values()}
    if len(conns) > 1 or not parts:
        ctx.issues.append(C.Issue("manual", where, "竖排取值块的数据来自不同数据连接,无法合成一个数据集,需手工转"))
        return _text_block(ctx, it, "[待配置报表块] " + title)
    base = "%s_键值%d" % (data_cells[0][1]["ds"], ctx.seq["t"] + 1)
    ctx.out_ds[base] = {"sql": " union all\n".join(parts), "conn": next(iter(conns)), "orig": data_cells[0][1]["ds"],
                        "derived": True, "fields": {"idx_name": ("String", "指标"), "idx_value": ("BigDecimal", "值")}}
    ctx.issues.append(C.Issue("info", where, "竖排「名称|值」取值块已转成 (指标, 值) 长表数据集「%s」(%d 行);原块里的行内公式(如总人数=门诊+急诊)已并入" % (base, len(parts))))
    props = {"datasetName": base, "columnSetting": {"columns": {
        "idx_name": {"label": "指标"}, "idx_value": {"label": "值", "align": "right"}}}}
    _apply_autoscroll(ctx, it, props)
    return {"id": ctx.bid("t"), "type": "table", "title": title, "props": props, "it": it}


def _apply_autoscroll(ctx, it, props):
    return None


def _table_block(ctx, it):
    inner = it["inner"]
    title, _u = _split_unit(it["title"])
    title = it["title"].strip()
    where = "报表块:" + (title or "?")
    if (it.get("name") or "").lower() in ctx.scroll_names:
        ctx.issues.append(C.Issue("info", where, "报表块带「自动滚动、悬停暂停」脚本(电视看板),表格区块不做自动滚动,已忽略"))
    fec = _first(inner, "FormElementCase")
    cl = _first(fec, "CellElementList") if fec is not None else None
    if cl is None:
        return _text_block(ctx, it, "[待配置报表块] " + title)
    widths = _parse_sizes(_first(fec, "ColumnWidth"))
    styles = []
    sl = next((e for e in inner.iter() if C.local(e.tag) == "StyleList"), None)
    for st in (sl if sl is not None else []):
        styles.append(C._parse_style(st))
    cells = {}
    for c in _kids(cl, "C"):
        r, ci = int(c.get("r")), int(c.get("c"))
        o = _first(c, "O")
        a = _first(o, "Attributes") if o is not None else None
        kind, val, ds, col = "empty", "", None, None
        if o is not None:
            t = o.get("t")
            if t == "DSColumn" and a is not None:
                kind, ds, col = "ds", a.get("dsName"), a.get("columnName")
            elif t == "Formula":
                kind, val = "formula", _txt(a)
            else:
                kind, val = "text", _txt(o)
        pres = _first(c, "Present")
        dic = None
        if pres is not None and "DictPresent" in pres.get("class", ""):
            d = _first(pres, "Dictionary")
            if d is not None and "TableDataDictionary" in d.get("class", ""):
                fa = _first(d, "FormulaDictAttr")
                tn = next((_txt(e) for e in d.iter() if C.local(e.tag) == "Name"), "")
                if fa is not None and tn:
                    dic = {"ki": fa.get("kiName"), "vi": fa.get("viName"), "ds": tn}
        s = styles[int(c.get("s"))] if c.get("s") is not None and int(c.get("s")) < len(styles) else None
        hl = _first(c, "HighlightList")
        rg = _first(o, "RG") if o is not None else None
        summ = rg is not None and "SummaryGrouper" in (rg.get("class") or "")
        cells[(r, ci)] = {"kind": kind, "val": val, "ds": ds, "col": col, "dic": dic, "style": s,
                          "hl": hl, "cs": int(c.get("cs") or 1), "summary": summ}
    # 汇总(SummaryGrouper)单元格是「单值汇总」,不是明细行:不能拿它定数据行(病区动态:表上方一行汇总会把明细列挤掉)
    sum_cells = [(k, v) for k, v in cells.items() if v["kind"] == "ds" and v["summary"]]
    data_cells = [(k, v) for k, v in cells.items() if v["kind"] == "ds" and not v["summary"]]
    if sum_cells and data_cells:
        ctx.issues.append(C.Issue("manual", where, "表上方有 %d 个「汇总」单元格(%s)未转;如要显示,请手工加 KPI 区块"
                                  % (len(sum_cells), "、".join(sorted({v["col"] for _, v in sum_cells})))))
        for k, _v in sum_cells:
            cells[k] = dict(cells[k], kind="empty")
    elif sum_cells:
        data_cells = sum_cells
    kv = _kv_table(ctx, it, cells, data_cells, where, title)
    if kv is not None:
        return kv
    if not data_cells:
        cc = next((o for o in inner.iter("O") if o.get("t") == "CC"), None)
        if cc is not None and any(C.local(e.tag) == "ChartDefinition" for e in cc.iter()):
            # 报表块里只有一个内嵌图表单元格(表盘/迷你图):把图表当独立图表区块转(表盘走既有 KPI/仪表逻辑)
            it2 = dict(it)
            it2["inner"] = cc
            blk = _chart_block(ctx, it2)
            if blk.get("type") != "text":
                ctx.issues.append(C.Issue("info", where, "报表块内嵌图表单元格已按独立图表区块转换"))
                return blk
        has_cc = cc is not None
        ctx.issues.append(C.Issue("manual", where,
                                  ("报表块里是内嵌图表单元格(表盘/迷你图等),需手工建 KPI/图表区块" if has_cc
                                   else "报表块里没有数据列(纯手工填写的表),需手工转")))
        return _text_block(ctx, it, "[待配置报表块] " + title)
    dr = min(k[0] for k, _ in data_cells)                     # 数据行
    from collections import Counter
    pri = Counter(v["ds"] for k, v in data_cells).most_common(1)[0][0]
    if len({v["ds"] for _, v in data_cells}) > 1:
        ctx.issues.append(C.Issue("degraded", where,
                                  "报表块混用多个数据集,只按主数据集「%s」转,其余列丢弃" % pri))
    if not ctx.need_ds(pri, where):
        return _text_block(ctx, it, "[待配置报表块] " + title)
    pub = pri not in ctx.out_ds                               # 公共数据集:拿不到 SQL,只能直连列
    ncols = max(c for _, c in cells) + 1
    hidden = {i for i in range(ncols) if i < len(widths) and widths[i] == 0}
    hdr_r = dr - 1
    while hdr_r >= 0 and not any(cells.get((hdr_r, c), {}).get("kind") == "text"
                                 and cells[(hdr_r, c)]["val"] for c in range(ncols)):
        hdr_r -= 1
    tot_r = None
    for r in range(dr + 1, dr + 4):
        if any(cells.get((r, c), {}).get("kind") in ("formula", "text") and cells[(r, c)]["val"]
               for c in range(ncols)):
            tot_r = r
            break
    # ---- 逐列:SQL 表达式 ----
    colexpr, colalias, collabel, colnum = {}, {}, {}, {}
    joins = []                                                  # (alias, dictsql, ki_col)
    dropped = []
    order = []

    def hdr(c):
        v = cells.get((hdr_r, c))
        return (v["val"] if v and v["kind"] == "text" else "") or ""

    # 先 DS 列
    for c in range(ncols):
        v = cells.get((dr, c))
        if not v or c in hidden:
            continue
        if v["kind"] == "ds" and v["ds"] == pri:
            ctx.ref(pri, v["col"])
            if v["dic"]:
                dd = ctx.src(v["dic"]["ds"])
                if pub or dd is None or not dd.get("sql"):
                    ctx.issues.append(C.Issue("degraded", where,
                                              "列「%s」的字典数据集「%s」找不到定义,该列将显示代码" % (hdr(c), v["dic"]["ds"])))
                    colexpr[c] = "t.%s" % v["col"]
                    colalias[c] = _safe_alias(v["col"])
                else:
                    a = "d%d" % (len(joins) + 1)
                    joins.append((a, dd["sql"], v["dic"]["ki"], v["col"]))
                    colexpr[c] = "%s.%s" % (a, v["dic"]["vi"])
                    colalias[c] = _safe_alias(v["col"]) + "_mc"
            else:
                colexpr[c] = "t.%s" % _qn(ctx.field_name(pri, v["col"]))   # 未命名表达式列已在 ctx.ref 里给源 SQL 补了别名
                colalias[c] = _safe_alias(v["col"])
                st0 = v["style"] or {}
                # 只有「明确是数值」才按数值列处理(有数字/百分比格式、或右对齐、或图表里当指标用过);
                # 否则按文本:避免工号 00123 被当成数字吃掉前导零
                colnum[c] = (st0.get("fmt_type") in ("number", "percent") or st0.get("halign") == "right"
                             or v["col"].lower() in ctx.num.get(pri, set()))
            collabel[c] = hdr(c) or v["col"]
            order.append(c)
    # 再公式列(可能引用别的列)
    def cellref(cc, rr, total=False):
        if rr == dr:
            if cc in colexpr:
                return colexpr[cc]
            raise _ExprFail("col%d" % cc)
        raise _ExprFail("row%d" % rr)

    for c in range(ncols):
        v = cells.get((dr, c))
        if not v or c in hidden or v["kind"] == "ds":
            continue
        if v["kind"] == "formula":
            if pub and not re.fullmatch(r"=\s*(seq\(\)|\"[^\"]*\")", v["val"].strip(), re.I):
                ctx.issues.append(C.Issue("degraded", where, "公式列「%s」(%s)依赖公共数据集 SQL,无法改写,已丢弃" % (hdr(c), v["val"])))
                continue
            if re.fullmatch(r"=\s*seq\(\)", v["val"], re.I):
                dropped.append("序号列「%s」" % hdr(c))
                continue
            try:
                if re.fullmatch(r'=\s*"[^"]*"', v["val"].strip()):
                    continue                              # 纯文字常量公式(标签/占位),不是数据列
                sql = _P(_tokenize(v["val"].lstrip("=")),
                         lambda cc, rr: cellref(cc, rr), lambda fn, inner: (_ for _ in ()).throw(_ExprFail("agg"))).parse()
            except (_ExprFail, IndexError):
                ctx.issues.append(C.Issue("degraded", where, "公式列「%s」(%s)无法改写成 SQL,已丢弃该列" % (hdr(c), v["val"])))
                continue
            colexpr[c] = "(%s)" % sql
            colalias[c] = "calc_%s" % chr(97 + c) if c < 26 else "calc_%d" % c
            collabel[c] = hdr(c) or colalias[c]
            colnum[c] = True
            order.append(c)
    order.sort()
    if hidden:
        ctx.issues.append(C.Issue("info", where, "宽度为 0 的隐藏列 %d 个已去掉(帆软里看不见,多是复制遗留)" % len(hidden)))
    for d in dropped:
        ctx.issues.append(C.Issue("info", where, "%s已去掉(表格区块自带行号/不需要)" % d))
    if any(v["hl"] is not None for v in cells.values()):
        ctx.issues.append(C.Issue("info", where,
                                  "报表块的条件高亮(多为斑马纹)未转;如是值条件高亮,需在表格列的 rules 里手配"))
    if not order:
        return _text_block(ctx, it, "[待配置报表块] " + title)
    # ---- 数据集 SQL ----
    srcsql = (ctx.src(pri) or {}).get("sql") or ""
    outer_order = ""
    mo = re.search(r"(?is)\border\s+by\s+([\w.]+(?:\s+(?:asc|desc))?(?:\s*,\s*[\w.]+(?:\s+(?:asc|desc))?)*)\s*;?\s*$", srcsql)
    if mo:                                    # 内层 order by 经外包后不保序 → 提到外层
        srcsql = srcsql[:mo.start()]
        outer_order = "\norder by " + re.sub(r"(?<![\w.])([A-Za-z_]\w*)(?=\s*(?:,|$|\s+(?:asc|desc)))",
                                              lambda m: m.group(1) if m.group(1).lower() in ("asc", "desc") else "t." + m.group(1),
                                              mo.group(1))
    need_wrap = (not pub) and (bool(joins) or any(cells[(dr, c)]["kind"] != "ds" for c in order))
    base = pri
    if need_wrap:
        sel = ["%s as %s" % (colexpr[c], colalias[c]) for c in order]
        sql = "select %s\nfrom (\n%s\n) t" % (",\n       ".join(sel), srcsql.strip().rstrip(";"))
        for a, dsql, ki, col in joins:
            sql += "\nleft join (\n%s\n) %s on t.%s = %s.%s" % (dsql.strip().rstrip(";"), a, col, a, ki)
        sql += outer_order
        base = "%s_表格%d" % (pri, ctx.seq["t"] + 1)
        ctx.out_ds[base] = {"sql": sql, "conn": ctx.src(pri).get("conn"), "orig": pri,
                            "fields": {colalias[c]: ("BigDecimal" if colnum.get(c) else "String", collabel[c])
                                       for c in order}, "derived": True}
        ctx.issues.append(C.Issue("info", where, "字典翻译/公式列已并入 SQL,生成数据集「%s」(含 %d 列)" % (base, len(order))))
    else:
        for c in order:
            colalias[c] = ctx.field_name(pri, cells[(dr, c)]["col"])
            if pub:
                continue
            ctx.out_ds[pri]["fields"][colalias[c]] = ("BigDecimal" if colnum.get(c) else "String", collabel[c])
    # ---- 列设置 ----
    cols = {}
    for c in order:
        al = colalias[c]
        cfgc = {"label": collabel[c]}
        v = cells[(dr, c)]
        st = v["style"] or {}
        if colnum.get(c):
            cfgc["align"] = "right"
            pat = st.get("fmt_pattern") if st else None
            if pat:
                ip, dot, fp = pat.partition(".")
                p = pat if "%" in pat else (("0,0" if "," in ip else "0") + dot + fp.replace("#", "0"))
                cfgc.update({"formatType": "percent" if st.get("fmt_type") == "percent" else "number", "format": p})
            # 没有显式数字格式:不配 formatType(原样显示),免得把整数人次硬格式化成 1,234.00
        cols[al] = cfgc
    cs = {"columns": cols}
    props = {"datasetName": base, "columnSetting": cs}
    # ---- 合计行 → 合计数据集 ----
    if tot_r is not None and not pub:
        label = next((cells[(tot_r, c)]["val"] for c in range(ncols)
                      if cells.get((tot_r, c), {}).get("kind") == "text" and cells[(tot_r, c)]["val"]), "合计")
        memo = {}

        def tcell(cc, rr):
            if rr == tot_r:
                if cc in memo:
                    return memo[cc]
                v = cells.get((tot_r, cc))
                if not v or v["kind"] != "formula":
                    raise _ExprFail("tot")
                p = _P(_tokenize(v["val"].lstrip("=")), tcell, tagg)
                e = p.parse()
                dv = cells.get((dr, cc))
                if (v["style"] or {}).get("fmt_type") == "percent" and not ((dv or {}).get("style") or {}).get("fmt_type") == "percent":
                    e = "(%s) * 100" % e          # 合计行是百分比格式(0.35→35%),数据行是已×100 的数
                memo[cc] = "(%s)" % e
                return memo[cc]
            if rr == dr and cc in colexpr:                 # 只会出现在 sum()/avg() 等聚合参数里
                return colexpr[cc]
            raise _ExprFail("tr")

        def tagg(fn, inner):
            return "%s(%s)" % (fn, inner)
        tsel, tfields = [], {}
        for c in order:
            v = cells.get((tot_r, c))
            if not v or v["kind"] != "formula":
                continue
            try:
                e = tcell(c, tot_r)
            except (_ExprFail, IndexError):
                ctx.issues.append(C.Issue("degraded", where, "合计行「%s」公式(%s)无法改写,该列合计留空" % (collabel[c], v["val"])))
                continue
            tsel.append("%s as %s" % (e, colalias[c]))
            tfields[colalias[c]] = ("BigDecimal", collabel[c])
        for c in order:                                       # 合计行里的文本常量(如「100%」),原样带入合计数据集
            v = cells.get((tot_r, c))
            if v and v["kind"] == "text" and v["val"] and v["val"] != label and colalias[c] not in tfields:
                tsel.append("'%s' as %s" % (v["val"].replace("'", "''"), colalias[c]))
                tfields[colalias[c]] = ("String", collabel[c])
        if tsel:
            tsql = "select %s\nfrom (\n%s\n) t" % (",\n       ".join(tsel), srcsql.strip().rstrip(";"))
            for a, dsql, ki, col in joins:
                tsql += "\nleft join (\n%s\n) %s on t.%s = %s.%s" % (dsql.strip().rstrip(";"), a, col, a, ki)
            tname = "%s_合计" % base
            ctx.out_ds[tname] = {"sql": tsql, "conn": ctx.src(pri).get("conn"), "orig": pri,
                                 "fields": tfields, "derived": True}
            cs["summary"] = {"text": label, "source": "dataset", "datasetName": tname}
            ctx.issues.append(C.Issue("info", where,
                                      "合计行改为合计数据集「%s」(占比列按合计值重算,不是列求和)" % tname))
    _apply_autoscroll(ctx, it, props)
    return {"id": ctx.bid("t"), "type": "table", "title": title, "props": props, "it": it}


# ---------------------------------------------------------------- 版面推断
def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _item_h(b):
    t = b["type"]
    h = b["it"]["h"]
    if t == "text":
        return 64
    if t == "table":
        return _clamp(h, 300, 420)
    return _clamp(h, 240, 380)


def _bands(blocks):
    bands = []
    for b in sorted(blocks, key=lambda b: (b["it"]["y"], b["it"]["x"])):
        it = b["it"]
        for bd in bands:
            top, bot = bd["top"], bd["bot"]
            ov = min(it["y"] + it["h"], bot) - max(it["y"], top)
            if ov > 0.5 * min(it["h"], bot - top):
                bd["items"].append(b)
                bd["top"], bd["bot"] = min(top, it["y"]), max(bot, it["y"] + it["h"])
                break
        else:
            bands.append({"items": [b], "top": it["y"], "bot": it["y"] + it["h"]})
    return bands


def _sz(w, total):
    return max(1, int(round(12.0 * w / max(total, 1))))


def _ref(b, size=None):
    s = '<block ref="%s"' % b["id"]
    if size and size != 1:
        s += ' size="%d"' % size
    return s + "/>"


def _band_xml(bd):
    items = bd["items"]
    kpis = sorted([b for b in items if b["type"] == "kpi"], key=lambda b: b["it"]["x"])
    others = sorted([b for b in items if b["type"] != "kpi"], key=lambda b: b["it"]["x"])
    if not others:
        out = []
        n = len(kpis)
        per = n if n <= 6 else (4 if n % 4 == 0 or n <= 8 else 5)
        for i in range(0, n, per):
            out.append('<row height="%d">%s</row>' % (KPI_H, "".join(_ref(b) for b in kpis[i:i + per])))
        return out
    if kpis and len(kpis) <= 2:
        # 只有 1~2 张 KPI 与图表同带:放进网格会被拉成 240 高的「大空卡」(KPI 行实测 108),
        # 按仪表盘惯例把 KPI 提到图表行之前单独成行
        head = '<row height="%d">%s</row>' % (KPI_H, "".join(_ref(b) for b in kpis))
        rest = dict(bd)
        rest["items"] = others
        return [head] + _band_xml(rest)
    # 簇:x 重叠的非 KPI 区块叠成一列
    clusters = []
    for b in others:
        it = b["it"]
        for cl in clusters:
            x0, x1 = cl["x0"], cl["x1"]
            ov = min(x1, it["x"] + it["w"]) - max(x0, it["x"])
            if ov > 0.5 * min(it["w"], x1 - x0):
                cl["items"].append(b)
                cl["x0"], cl["x1"] = min(x0, it["x"]), max(x1, it["x"] + it["w"])
                break
        else:
            clusters.append({"items": [b], "x0": it["x"], "x1": it["x"] + it["w"]})
    nodes = []                                           # (x, w, kind, payload, height)
    for cl in clusters:
        hs = [_item_h(b) for b in cl["items"]]
        nodes.append((cl["x0"], cl["x1"] - cl["x0"], "cl", cl["items"], sum(hs) + GAP * (len(hs) - 1)))
    if kpis:
        rows = (len(kpis) + 1) // 2
        nodes.append((kpis[0]["it"]["x"], sum(b["it"]["w"] for b in kpis), "kpi", kpis,
                      rows * KPI_H + GAP * (rows - 1)))
    nodes.sort(key=lambda n: n[0])
    total = sum(n[1] for n in nodes)
    H = max(n[4] for n in nodes)
    only_table = all(b["type"] == "table" for b in others) and not kpis
    parts = []
    for x, w, kind, payload, h in nodes:
        size = _sz(w, total)
        if kind == "cl" and len(payload) == 1:
            parts.append(_ref(payload[0], size))
        elif kind == "cl":
            hs = [_item_h(b) for b in payload]
            parts.append('<column size="%d">%s</column>' % (size, "".join(
                '<row size="%d">%s</row>' % (max(1, int(round(hh / 40.0))), _ref(b))
                for b, hh in zip(payload, hs))))
        else:
            rws = ["".join(_ref(b) for b in payload[i:i + 2]) for i in range(0, len(payload), 2)]
            parts.append('<column size="%d">%s</column>' % (size, "".join(
                '<row size="1">%s</row>' % r for r in rws)))
    if only_table:
        return ['<row heightMode="auto">%s</row>' % "".join(parts)]
    return ['<row height="%d">%s</row>' % (H, "".join(parts))]


# ---------------------------------------------------------------- 查询面板 → 过滤栏
def _filters(ctx, region_elems):
    fake = ET.Element("root")
    rpa = ET.SubElement(fake, "ReportParameterAttr")
    for e in region_elems:
        rpa.append(e)
    q = C._parse_query_panel(fake, ctx.ds)
    if not q:
        return [], {}
    for i in q.get("issues", []):
        ctx.issues.append(i)
    comps, keep = [], []
    for cm in q["components"]:
        if cm.get("type") in ("query", "text", "reset"):
            continue
        if cm.get("label"):
            cm["label"] = cm["label"].strip().rstrip("：: ").strip()
        pos = cm.get("position") or {}
        w = _clamp(int(pos.get("width") or 170), 140, 260)
        cm["position"] = {"x": 0, "y": 0, "width": w, "height": 32}
        if cm.get("type") == "date":
            pr = cm.setdefault("props", {})
            if not pr.get("datePickerType"):
                pr["datePickerType"] = "date"
            fm = {"date": "yyyy-MM-dd", "datetime": "yyyy-MM-dd HH:mm:ss", "year": "yyyy",
                  "month": "yyyy-MM"}.get(pr["datePickerType"], "yyyy-MM-dd")
            pr["format"] = fm
            pr["valueFormat"] = fm
        comps.append(cm)
    return comps, q.get("meta", {})


# ---------------------------------------------------------------- 数据集/XML 输出
def _emit_datasets(ctx, used, qmeta, comps):
    out = []
    conn_map = ctx.cfg.get("connection_map") or {}
    date_p = {c.get("parameterName") for c in comps if c.get("type") == "date"}
    multi_p = {c.get("parameterName") for c in comps if c.get("type") in ("multiselect", "checkbox")}
    n = 0
    params = {}
    for name, d in ctx.out_ds.items():
        if name not in used:
            continue
        n += 1
        conn = d.get("conn") or ""
        if conn in conn_map:
            mv = conn_map[conn]
            conn = (mv.get("name") if isinstance(mv, dict) else mv) or conn
        if conn and not any(i.where == "连接:" + conn for i in ctx.issues):
            ctx.issues.append(C.Issue("info", "连接:" + conn, "数据集使用数据连接「%s」(沿用帆软连接名,如目标系统不同请在 connection_map 映射)" % conn))
        sql, unk = C.translate_sql(d["sql"], None, None, date_p, multi_p, set())
        for sev, pr in C.sql_lint(d["sql"]):
            ctx.issues.append(C.Issue(sev, "数据集:" + name, "原 SQL " + pr))
        if unk:
            ctx.issues.append(C.Issue("degraded", "数据集:" + name, "SQL 动态条件含未映射函数 %s,需复核" % "、".join(sorted(unk))))
        for pn in C.extract_sql_params(d["sql"]):
            params.setdefault(pn, None)
        a = 'xmlns="" id="ds%02d" name="%s" type="sql"' % (n, html.escape(name, quote=True))
        if conn:
            a += ' dataSourceName="%s"' % html.escape(conn, quote=True)
        out.append("<dataset %s><sql>%s</sql>" % (a, C.cdata(sql)))
        flds = {}
        if d.get("derived"):
            for k, (t, l) in d["fields"].items():
                flds[k] = (t, l)
        else:
            for f in C.fields_from_sql(d["sql"]):
                flds.setdefault(f, ("String", f))
            for lc, orig in ctx.refs.get(d["orig"], {}).items():
                if not any(k.lower() == lc for k in flds):
                    flds[orig] = ("String", orig)
            for k, v in d["fields"].items():
                for kk in [x for x in flds if x.lower() == k.lower()]:
                    del flds[kk]
                flds[k] = v
            nums = ctx.num.get(d["orig"], set())
            for k in list(flds):
                if k.lower() in nums:
                    flds[k] = ("BigDecimal", flds[k][1])
        if not flds:
            ctx.issues.append(C.Issue("degraded", "数据集:" + name, "字段列表为空(SELECT * 或动态列),需在设计器补字段"))
        for k, (t, l) in flds.items():
            out.append('<field name="%s" type="%s" label="%s"/>' % (
                html.escape(k, quote=True), t, html.escape(l, quote=True)))
        out.append("</dataset>")
    return "".join(out), params


def _emit_params(params, qmeta):
    out = []
    allp = dict(params)
    for pn in qmeta:
        allp.setdefault(pn, None)
    for i, pn in enumerate(allp, 1):
        m = qmeta.get(pn, {})
        dt = m.get("datatype") or "String"
        dv = m["default"] if m.get("default") is not None else ""
        dv = str(dv).replace("\\'", "'").replace('\\"', '"')
        a = 'xmlns="" id="pm%02d" name="%s" datatype="%s" required="%s"' % (
            i, html.escape(pn, quote=True), dt, "true" if m.get("required") else "false")
        if m.get("default_expr"):
            a += ' defaultValueMode="expression" defaultValueIsExpression="true"'
        else:
            a += ' defaultValueMode="value" defaultValueIsExpression="false"'
        a += ' defaultValue="%s"' % html.escape(dv, quote=True)
        out.append("<parameter %s/>" % a)
    return "".join(out)


def _block_xml(b):
    a = 'id="%s" type="%s"' % (b["id"], b["type"])
    if b.get("title"):
        a += ' title="%s"' % html.escape(b["title"], quote=True)
    return "<block %s><propsJson>%s</propsJson></block>" % (
        a, C.cdata(json.dumps(b["props"], ensure_ascii=False)))


# ---------------------------------------------------------------- 入口
def convert_frm(path, outdir, cfg, subdir="", overwrite="overwrite"):
    name = os.path.splitext(os.path.basename(path))[0]
    rel = os.path.join(subdir, name) if subdir else name
    C._PUBLIC["on"] = cfg.get("assume_public_datasets", True)
    C._PUBLIC["report"] = rel
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        return [{"name": rel, "ok": False, "error": "XML 解析失败:%s" % e}]
    issues = []
    ctx = Ctx(root, cfg, issues, name)
    items, qelems = [], []
    for tag, el, is_param in _find_layouts(root):
        if is_param:
            qelems.append(el)
            continue
        _collect(el, 0, 0, items)
    # 查询面板控件也可能直接散落在 Center 里(无 WParameterLayout):按类型收
    qkinds = ("ComboBox", "DateEditor", "Year", "TextEditor", "FormSubmitButton", "ComboCheckBox",
              "TreeComboBoxEditor", "NumberEditor", "CheckBox", "CheckBoxGroup", "RadioGroup", "FreeButton")
    blocks = []
    ctx.named = {it["name"]: it for it in items if it.get("name")}
    hidden_n = 0
    for it in sorted(items, key=lambda i: (i["y"], i["x"])):
        k = it["kind"]
        if it.get("invisible") and k in ("ChartEditor", "ElementCaseEditor"):
            hidden_n += 1                    # 帆软里不可见的控件:多为给图表供数的隐藏报表块
            continue
        if k == "ChartEditor":
            blocks.append(_chart_block(ctx, it))
        elif k == "ElementCaseEditor":
            blocks.append(_table_block(ctx, it))
        elif k == "Label":
            t = _strip_q(_txt(_first(_first(it["inner"], "widgetValue"), "O")
                              if _first(it["inner"], "widgetValue") is not None else None))
            if t and not it["param"]:
                blocks.append(_text_block(ctx, it, t, bold=True, tone="primary"))
        elif k in qkinds or it["param"]:
            pass
        else:
            issues.append(C.Issue("manual", "控件:" + k, "控件类型 %s 暂不支持,已忽略" % k))
    if hidden_n:
        issues.append(C.Issue("info", "控件", "不可见的图表/报表块 %d 个已略过(帆软里看不见;若它给别的图表供数,已并入那张图表的数据集)" % hidden_n))
    comps, qmeta = _filters(ctx, qelems) if qelems else ([], {})
    used = {b["props"]["datasetName"] for b in blocks if b["props"].get("datasetName")}
    for b in blocks:
        cs = b["props"].get("columnSetting", {}).get("summary")
        if cs:
            used.add(cs["datasetName"])
    ds_xml, sql_params = _emit_datasets(ctx, used, qmeta, comps)
    # 仅在用的数据集里引用的参数才声明;控件参数始终声明
    par_xml = _emit_params(sql_params, qmeta)
    lay = "".join("".join(_band_xml(bd)) for bd in _bands(blocks))
    rid = hashlib.md5(rel.encode("utf-8")).hexdigest()[:24]
    theme = cfg.get("dashboard_theme", "medical")
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n'
           '<report xmlns="http://sightdata.top/schema/report-template" fileType="dashboard" reportId="%s">'
           '<meta xmlns="" schemaVersion="1" theme="%s" aggregationMode="pushdownFirst"/>%s%s'
           '<queryFormSetting xmlns="">%s</queryFormSetting><filterBar xmlns="">%s</filterBar>'
           '<layout xmlns=""><tabs><tab id="tab_1" name="%s">%s</tab></tabs></layout>'
           '<blocks xmlns="">%s</blocks></report>'
           % (rid, theme, ds_xml, par_xml,
              C.cdata(json.dumps({"components": comps}, ensure_ascii=False)),
              "".join('<item componentId="%s"/>' % html.escape(c["id"], quote=True) for c in comps),
              html.escape(name, quote=True), lay, "".join(_block_xml(b) for b in blocks)))
    dest = os.path.join(outdir, subdir) if subdir else outdir
    os.makedirs(dest, exist_ok=True)
    mrs = os.path.join(dest, name + ".mrs")
    if os.path.exists(mrs) and overwrite == "skip":
        return [{"name": rel, "ok": True, "skipped": True, "cells": 0, "manual": 0, "degraded": 0}]
    if os.path.exists(mrs) and overwrite == "rename":
        k = 1
        while os.path.exists(os.path.join(dest, "%s_%d.mrs" % (name, k))):
            k += 1
        name = "%s_%d" % (name, k)
        rel = os.path.join(subdir, name) if subdir else name
        mrs = os.path.join(dest, name + ".mrs")
    with open(mrs, "w", encoding="utf-8") as f:
        f.write(xml)
    iss, _ = C._issue_rows(issues)
    lines = ["# %s —— 决策报表 → 仪表盘转换说明" % name, "",
             "区块 %d 个、数据集 %d 个、过滤控件 %d 个。" % (len(blocks), len([1 for n in ctx.out_ds if n in used]), len(comps)), ""]
    for lv, title in (("manual", "待人工"), ("degraded", "降级/需复核"), ("info", "已自动优化/说明")):
        rows = [i for i in issues if i.level == lv]
        if rows:
            lines += ["## %s" % title, ""] + ["- [%s] %s" % (i.where, i.msg) for i in rows] + [""]
    with open(os.path.join(dest, name + ".report.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return [{"name": rel, "ok": True, "skipped": False, "cells": len(blocks),
             "manual": len([i for i in iss if i["level"] == "manual"]),
             "degraded": len([i for i in iss if i["level"] == "degraded"]),
             "issues": iss, "assumed_hl": 0}]
