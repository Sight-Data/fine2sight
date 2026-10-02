# 帆软 → sight-report 函数映射对照表

> 转换器公式翻译层(`convert.py` 的 `translate_expression`)的**源于真实数据的映射依据**。
> 每个映射都经过「参数顺序 / 基准 / 语义 / 上下文」核对,而非仅对函数名。
> 扩充映射时改这里 + 同步 `convert.py` 的 `FR_SAFE` / `FR_RENAME` / 专项重写。

**覆盖率(早期一次全库统计,3364 张 .cpt、72,055 条公式):确定性翻译干净 99.2%,标红 0.8%。**
该数字是 2026-07 的快照,之后新增了 §2.5b 的映射(干净率只会更高),但**没有重跑**;本库当前只有 240 张 .cpt 可测。

> 📌 **核对状态(2026-10-02)**:本文已对照 `convert.py` 当前行为与 `sight-data-code` 的
> `ai-docs/expression-syntax-guide.md`(最后改动 2026-08-23,仅「子报表不可嵌套」,与函数语义无关)逐条核过;
> 一并修了 `FORMAT(x,"yyyy-MM-dd")` 误走 `formatNumber` 的 bug(§2.6,已加回归用例)。

magic 端函数语义以 `ai-docs/expression-syntax-guide.md`(MagicScript 引擎)为准。

---

## 1. 翻译策略分四层

| 层 | 含义 | 是否标红 |
|---|---|---|
| **直接** | 帆软与 magic 同名、参数顺序/语义一致,仅归一大小写 | 否(干净) |
| **改名** | 参数语义一致,仅函数名不同 | 否(干净) |
| **上下文/参数重写** | 需按参数值或上下文改写结构 | 否(干净) |
| **标红** | 参数不兼容 / 无 magic 对应 → 交人工或 AI | 是 |

> 采用**白名单制**:只有进入下表「直接/改名/重写」的函数才算干净;
> 函数名偶然与 magic 相同但语义不同的(如 `FIND`),一律标红,**绝不静默映射**。

---

## 2. 完整对照表

频次 = 全库该函数出现次数(用于排优先级)。

### 2.1 聚合函数

| 帆软 | 频次 | 帆软语义 | magic 对应 | 决策 | 参数核对 |
|---|---|---|---|---|---|
| `SUM(...)` | 30838 | 求和(参数/单元格/区域)| `sum(...)` | 直接 | ✅ 一致;`sum(A1)` 对扩展值求和,同 magic |
| `COUNT(...)` | 808 | 计数 | `count(...)` | 直接 | ⚠️ magic `count` 计参数个数(含 null);单元格扩展计数依赖 magic 扩展求值,**建议首张抽查** |
| `AVERAGE(...)` | 430 | 平均 | `avg(...)` | 改名 | ✅ 一致 |
| `MAX/MIN(...)` | 6+ | 极值 | `max/min(...)` | 直接 | ✅ 一致 |

### 2.2 数学函数

| 帆软 | 频次 | 帆软语义 | magic 对应 | 决策 | 参数核对 |
|---|---|---|---|---|---|
| `ROUND(n,d)` | 684 | 四舍五入到 d 位 | `round(n,d)` | 直接 | ✅ 参数顺序一致 |
| `ROUNDUP(x)` | 18 | 向上取整(单参)| `ceil(x)` | 重写 | ✅ 仅单参时;`ROUNDUP(x,d)` 带位数 → 标红 |
| `ABS(n)` | — | 绝对值 | `abs(n)` | 直接 | ✅ |

### 2.3 字符串函数

| 帆软 | 频次 | 帆软语义 | magic 对应 | 决策 | 参数核对 |
|---|---|---|---|---|---|
| `CONCATENATE(...)` | 8648 | 拼接 | `concat(...)` | 改名 | ✅ 均忽略 null,一致 |
| `LEN(s)` | 17 | 长度 | `length(s)` | 改名 | ✅ |
| `LEFT/RIGHT(s,n)` | — | 左/右截取 | `left/right(s,n)` | 直接 | ✅ 参数一致 |
| `REPLACE(s,old,new)` | 12 | (本库)查找替换 | `replace(s,old,new)` | 直接 | ⚠️ magic `old` 按**正则**解释;含正则元字符 `. * ? [ ]` 时需复核。注:帆软标准 REPLACE 为按位置 4 参替换,本库未出现 |

### 2.4 日期函数

| 帆软 | 频次 | 帆软语义 | magic 对应 | 决策 | 参数核对 |
|---|---|---|---|---|---|
| `TODAY()` | 14748 | 当天(纯日期,无时间)| `date()` 或 `now()` | **上下文重写** | ⚠️ 见 §3.1。字符串场景→`date()`;日期运算场景→`now()` |
| `NOW()` | 523 | 当前日期时间 | `now()` | 直接 | ✅ |
| `DATEDELTA(d,n)` | 588 | d 加 n 天 | `addDays(d,n)` | 改名 | ✅ 参数顺序一致 |
| `MONTHDELTA(d,n)` | 248 | d 加 n 月 | `addMonths(d,n)` | 改名 | ✅ |
| `DATEINMONTH(d,1)` | ~4242 | 当月第 1 天 | `monthStart(d)` | 重写 | ✅ |
| `DATEINMONTH(d,-1)` | (同上) | 当月最后一天 | `monthEnd(d)` | 重写 | ⚠️ magic `monthEnd` 含 23:59:59.999,帆软为当天 00:00:00;作 BETWEEN 上界时 magic 更合理 |
| `DATEINMONTH(d,n)` n≠±1 | 492 | 当月第 n 天 | `addDays(monthStart(d), n-1)` | 近似重写 | ⚠️ 2026-10 起不再标红;首参为复合表达式时见 §3.1b 已知缺口 |
| `DATEINQUARTER(d,1/-1)` | 4–6 | 当季第一天/最后一天 | `quarterStart/quarterEnd(d)` | 重写 | ✅ |
| `year()/month()/day()` 无参 | — | 当前年/月/日 | `year(now())` 等 | 重写 | ✅ magic 同名函数必须带日期参数 |
| `YEAR/MONTH/DAY(d)` | 38+ | 年/月/日分量 | `year/month/day(d)` | 直接 | ✅ MONTH 均 1–12 |
| `日期 ± 整数` | — | 加减天数 | `addDays(d,±n)` | 重写 | ✅ 帆软 `today()-1` → `addDays(now(),-1)` |

### 2.5 逻辑 / 报表 / 自引用

| 帆软 | 频次 | 帆软语义 | magic 对应 | 决策 | 参数核对 |
|---|---|---|---|---|---|
| `if(c,a,b)` | 1204 | 条件 | `if(c,a,b)` | 直接 | ✅ 三参一致 |
| `SEQ()` | 1718 | 自增序号 | `seq()` | 直接 | ⚠️ 语义假定为自增序号,**建议抽查**;`SEQ(1,...)` 带参/含数据字典访问 → 标红 |
| `$$$` | — | 当前格自身值 | `$$value` | 重写 | ✅ |
| `$参数` | 16805 条含 | 报表参数 | `$参数` | 直通 | ✅ 两端均单 `$` 前缀 |
| 单元格名 `B4` / 区域 `A1:A10` | 36708 条含 | 单元格引用 | 同写法 | 直通 | ✅ 帆软格名与 magic 格名一致(见转换器坐标说明) |

### 2.5b 2026-08 以后新增映射(原「未映射」清单已收窄,见 §4)

| 帆软 | magic 对应 | 决策 | 说明 |
|---|---|---|---|
| `FIND(子串,母串)` | `(find(母串,子串) + 1)` | 重写 | 参数顺序交换 + 基准 0→1;`find(...)>0` 判断因此保持正确(详见 §3.2) |
| `TRUNC(x[,n])` | `trunc(...)` | 改名 | 向零截断(后端 sight-platform 新增同义函数) |
| `DATETONUMBER(d)` | `dateToNumber(d)` | 改名 | 日期转毫秒 |
| `SWITCH(e,k1,v1,…[,def])` | `((e)==k1 ? v1 : (… : def))` | 重写 | magic 无 switch,展开成嵌套三元 |
| `SPLIT(s,sep)` | `(s == null ? "" : s).split(sep)` | 重写 | |
| `INDEXOFARRAY(a,n)` | `arrayGet(a, n-1)` | 重写 | 1 基→0 基 |
| `CNMONEY(x)` | `numberToRMB(x)` | 改名 | |
| `SUBSTITUTE` | `replace` | 改名 | 同 §3.5 的正则注意事项 |
| `{J4}` / `{J4:K5}` | `J4` / `J4:K5` | 重写 | 帆软花括号单元格引用,magic 不认花括号(真机会整张报表解析失败) |

### 2.6 格式化(按格式串判定)

| 帆软 | 频次 | 帆软语义 | magic 对应 | 决策 | 参数核对 |
|---|---|---|---|---|---|
| `FORMAT(x,"0.00%")` | 126 | 数字/日期格式化 | `formatNumber(x,...)` | 重写 | ✅ 含 `# 0 % ,` → formatNumber |
| `FORMAT(x,"yyyy-MM-dd")` | (同上) | 日期格式化 | `formatDate(x,...)` | 重写 | ✅ 含 `y M d H s` 且无 `# %` → formatDate。⚠️ 2026-10-02 前此分支实际失效(字符串字面量已被占位符保护,格式串没还原就做判断,日期格式也走成 formatNumber),现已修复 |

---

## 3. 参数级差异详解(重点坑)

### 3.1 TODAY:日期 vs 日期时间,按上下文分

帆软 `TODAY()` 返回**纯日期**(无时间)。若一律映射成 magic `now()`(带当前时间),在字符串拼接里会出错:

```
帆软  CONCATENATE(TODAY()," 23:59:59")            期望 "2024-03-15 23:59:59"
错误  concat(now()," 23:59:59")        → "2024-03-15 14:30:00 23:59:59"  ✗ 时间戳被污染
正确  concat(date()," 23:59:59")       → "2024-03-15 23:59:59"            ✓
```

规则:
- 在字符串拼接(`CONCATENATE` / `+`)中 → `date()`(返回 `yyyy-MM-dd` 字符串)
- 作为日期对象传入日期函数(`DATEINMONTH/DATEDELTA`)或参与日期加减 → `now()` / `addDays(now(),…)`

### 3.1b DATEINMONTH/DATEINQUARTER 等包裹结果同理:字符串拼接里要显式格式化

上面这条规则不仅对裸 `TODAY()` 成立,对**它被 `DATEINMONTH`/`DATEINQUARTER`/`DATEDELTA`/
`MONTHDELTA` 包裹后的翻译结果**(`monthStart(now())`/`monthEnd(now())`/`quarterStart(now())`/
`quarterEnd(now())`/`addDays(now(),n)`/`addMonths(now(),n)`,均返回 `Date` 对象)同样成立:

```
帆软  CONCATENATE(DATEINMONTH(TODAY(),1)," 00:00:00")   期望 "2026-07-01 00:00:00"
错误  concat(monthStart(now())," 00:00:00")   → Java Date.toString() 默认格式 + 时间串  ✗
正确  concat(formatDate(monthStart(now()), "yyyy-MM-dd")," 00:00:00")                  ✓
```

`concat()` 脚本函数是 `StringBuilder.append`,不会应用 magic `+` 运算符那套隐式日期格式化
(`ArithmeticHandle` 默认 `yyyy-MM-dd HH:mm:ss`);`+` 号拼接虽有隐式格式化但也不是帆软期望的
纯日期 `yyyy-MM-dd`。两条路径都不对,故统一显式包 `formatDate(expr,"yyyy-MM-dd")`。

`translate_expression` 里由 `_stringify_date_results_in_concat`(`CONCATENATE(...)` 顶层实参)
+ `_stringify_date_results_near_plus`(紧邻字符串字面量的 `+` 拼接)两个专项重写覆盖,只在
**整段恰好是**上述几个函数调用时才包裹,不影响作为日期对象继续参与运算的场景(如
`DATEDELTA(DATEINMONTH(TODAY(),1), 5)` → `addDays(monthStart(now()), 5)`,不包裹)。

> ⚠️ 已知残留缺口:`DATEINMONTH(x, n)` 当 `x` 不是裸 `TODAY()`(如复合表达式 `today()-day(today())`
> 或 n≠±1 走"月初+(n-1)天"近似,见 §4)时,内层若含 `TODAY()`,当前实现可能被末尾"其余 TODAY→
> `date()`"兜底规则误转成字符串(日期对象上下文本该是 `now()`)。此为独立于本节的既有缺口,
> 出现概率低(需要复合首参 + 非 ±1 的 n),未在本轮修复范围内。

### 3.2 FIND:参数顺序 + 基准都不同 → 重写(不是直接改名)

```
帆软  find(子串, 母串)   1-based,未找到返回 0,惯用 find(...)>0 判断
magic find(母串, 子串)   0-based,未找到返回 -1
```

两处不一致(顺序反、基准差)。早期版本故意标红;现在改为**同时交换参数并 +1**:
`find("a",B1)` → `(find(B1, "a") + 1)`,未找到 -1+1=0、首位匹配 0+1=1,`>0` 判断语义保持。

### 3.3 COUNT / 聚合的单元格扩展

magic `count(v1,v2,...)` 文档定义为「参数个数(含 null)」。对 `count(B4)`(B4 为扩展格)是否按扩展行数计数,取决于 magic 对单元格引用的扩展求值(与 `sum(B4)` 同族)。已映射,但**建议首张导入后抽查一个汇总/计数值**确认。

### 3.4 条件高亮的条件表达式

帆软 `Highlight` 的 `FormulaCondition`(公式条件)走同一套表达式翻译,额外两条规则:

- `$$$`(当前格自身值)→ magic `$$value`
- 帆软用**单 `=`** 作比较 → magic `==`(`>= <= != ==` 不动)

例:`$$$ = A2` → `$$value == A2`;`row()%2==0` → 原样(`row()` 已在白名单)。

> 结构化条件(`ObjectCondition`/`CommonCondition`,`<Compare op="N">` 按 op 码比较)**不翻译**:
> op 码语义不确定,猜错会静默配错条件 → 标红交人工(见 README)。

### 3.5 REPLACE:本库三参 vs 帆软标准四参

帆软标准 `REPLACE(text,start,num,new)` 是**按位置**替换(Excel 风格)。但本库实际全是 `replace(text,old,new)` 三参**查找替换**,与 magic `replace(str,old,new)` 兼容。仅需注意 magic 的 `old` 按正则解释。

---

## 3.6 SQL 参数语法(两边规则不同,必译)

帆软 `${}` 是**文本内联**(值直接拼进 SQL,故参数都写在引号内);magic(报表与仪表盘数据集同一套)有三种写法:
`$p` / `${$p}` 是**预编译 `?` 绑定**(放进引号会变 `'?'`),`#{表达式}` 是**表达式字面量拼接**(过注入校验)。
早期版本统一译成 `#{$p}` 内联;现已改成**按上下文选写法**(`translate_sql`):

| 帆软 | magic | 说明 |
|---|---|---|
| `x = '${kw}'`(引号内裸参数) | `x = #{isEmpty($kw) \|\| $kw == '' ? "null" : "'" + $kw + "'"}` | 引号交给表达式生成;**空值变 `null`**,不再是 `''` |
| `like '%${kw}%'` | `like ${'%' + $kw + '%'}` | 拼好值后走预编译绑定 |
| `x = ${num}` | `x = $num` | 裸参数 → 预编译绑定 |
| `in (${ids})` | `in (#{isEmpty($ids) \|\| $ids == '' ? "null" : $ids})` | 帆软此处的值本身是「SQL 列表文本」(如 `1,2`),不能再包引号 |
| `${if(len(k)==0,"","and c in('"+k+"')")}` | `#{if((isEmpty($k) \|\| $k == ''),"","and c in ('" + $k + "')")}` | 动态片段:换 `#{}` + 函数翻译(`len→length`)+ 参数加 `$`,字符串内 SQL 列名不动 |

分流依据(转换时按参数/控件类型判定):日期型参数(`datatype` 为 Date/DateTime,或绑日期控件)不可内联成字符串;
多选参数(`ComboCheckBox`/`CheckBoxGroup`,声明 `List`)走 `.join`;布尔参数(单个 `CheckBox`→`switch`)既不内联也不 `join`。
参数同时登记进 `<parameter>`(含只在 `if()` 里出现的)。

> **注入风险**:`#{}` 直接拼接,与帆软原状一致(非本工具引入);只走预编译 `$p` 的写法不受影响。
> 仪表盘的数据集 SQL 用同一套语法(`${$p}` 等价于 `$p`),每个被引用的参数都要有同名 `<parameter>`。

## 4. 未映射清单(标红 → P2 / AI 兜底)

2026-10-02 现状(`translate_expression` 实测;括号内为早期全库频次):

| 帆软函数 | 频次 | 原因 |
|---|---|---|
| `VALUE(ds,field)` | 14 | 数据字典取值,需改 `dataset()` 语义 |
| `SELECT(...)` | 4–6 | 数据集取值专有 |
| `UNIQUEARRAY / ARRAY` | 6/8 | 数组类,无 1:1 |
| `ROUNDUP(x,d)` 带位数 | — | 仅单参 `ROUNDUP(x)`→`ceil` |
| `DATEINMONTH(复合表达式,n)` | 少 | 内层 `TODAY()` 可能被误转 `date()`,见 §3.1b |

已从本清单移出(见 §2.5b):`DATEINMONTH n≠±1`(近似)、`DATETONUMBER`、`TRUNC`、`SWITCH`、`INDEXOFARRAY`、`CNMONEY`、`SPLIT`、`FIND`、`DATEINQUARTER`。

> 剩余项占总公式远低于 0.8%。P2 可建「AI 兜底」:把标红表达式连同本表上下文交 LLM 产出 magic 等价式,再人工确认。

---

## 5. 如何扩充映射

1. **同名兼容** → 加进 `convert.py` 的 `FR_SAFE`(键为小写帆软名,值为 magic 规范名)。
2. **改名兼容** → 加进 `FR_RENAME`。
3. **需按参数/上下文改写** → 在 `translate_expression` 的专项重写段加正则(参考 `FORMAT` / `DATEINMONTH` / `TODAY` 写法)。
4. **确认不兼容** → 不加(自动落入标红),在本文档 §4 登记原因。
5. 改完跑全库覆盖率自测:
   ```bash
   python3 test_expression.py     # 表达式回归(12 条)
   # 全库覆盖率统计见 README「质量保障」
   ```
6. **务必同步更新本表**,保持「代码映射 ↔ 文档依据」一致。
