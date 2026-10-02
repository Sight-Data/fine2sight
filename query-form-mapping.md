# 参数 & 查询组件:帆软 ↔ sight-report 实证对比与兼容方案

> 基于全库 3364 张 `.cpt` 的真实分布,把帆软「查询面板 + 报表参数」逐项对照 magic 的
> `queryFormSetting`(`ReportQueryComponent`,见 `.../types/report-query-types.ts`)
> 与 `<parameter>` / `<setting>`,标出可确定性映射的部分,以及 magic 接不住、需「兼容(近似/降级)」
> 或「扩充(magic 加能力)」的部分。

---

> **状态:§2 / §4「应实现」部分已编码完成**(convert.py 的 `_parse_query_panel`):
> 全库 3290 面板 / 30,950 组件转换、XSD 通过、随机样本 JSON 全合法(2026-08 的一次全库统计)。§3 的 gap 按方案标红交人工。
>
> 📌 **核对状态(2026-10-02)**:已对照 `convert.py` 当前行为和 sight-data-code 的
> `report-query-types.ts`(最后改动 2026-09-24)核过,见文末「§5 2026-08 之后的变化」。
> 同一套查询面板转换现在也服务 **`.frm` 决策报表 → 仪表盘**(`convert_frm.py` 复用 `_parse_query_panel`,
> 把组件位置改成仪表盘过滤栏的流式占位)。

## 0. 结论

- **控件层 ~95% 可确定性映射**:3357 张报表共 31,358 个查询控件,绝大多数是
  Label / DateEditor / TextEditor / Combo / Button,与 magic 组件近乎一一对应,且两边都是
  绝对定位 → **连面板布局都能原样保留**。
- 真正的 gap 只有 **自定义 JS 联动**一项较多(831 张),其余都能映射或低成本近似。
- `delayPlaying`(不自动查询)**不是 gap**:对应 magic `<setting fetchDataWhenOpen>`。

---

## 1. 实证分布(全库)

含查询面板的报表 **3357**,查询控件总数 **31,358**。

**控件类型**

| 帆软控件 | 频次 | 含义 |
|---|---|---|
| `Label` | 11698 | 静态文字标签 |
| `DateEditor` | 6325 | 日期/时间选择 |
| `TextEditor` | 4565 | 文本输入 |
| `FormSubmitButton` | 3302 | 查询(提交)按钮 |
| `ComboCheckBox` | 2759 | 多选下拉 |
| `ComboBox` | 1953 | 单选下拉 |
| `FreeButton` | 389 | 自定义按钮 |
| `CheckBox` | 172 | 单个复选框 |
| `RadioGroup` | 154 | 单选框组 |
| `EditorHolder` | 18 | 容器控件 |
| `NumberEditor` | 13 | 数值输入 |
| `CheckBoxGroup` | 10 | 复选框组 |

**下拉字典**:`TableDataDictionary` 3533(数据集绑定)、`CustomDictionary` 1340(静态键值)。
**日期格式**:`yyyy-MM-dd HH:mm:ss` 5749、`yyyy-MM` 31、`yyyy-MM-dd HH:mm` 10、其余零星。
**面板属性**:`showWindow=true` 3357、`delayPlaying=true` 3329 / `false` 28;布局全是 `WParameterLayout`(绝对定位)。
**其他特征**:`allowBlank` 约束 1004、**自定义 JS 监听 831**、自定义按钮 386。

---

## 2. 可确定性映射(应实现)

### 2.1 控件 → magic 组件

| 帆软 | magic `type` | 备注 |
|---|---|---|
| `Label` | `text` | `content`=标签文字 |
| `DateEditor` / `Year` | `date` | 由 `DateAttr format` 推 `datePickerType`:含 `HH`→`datetime`,`yyyy-MM`→`month`,否则 `date`;`format`/`valueFormat` 原样带 |
| `TextEditor` | `input` | |
| `TextArea` | `input` | 多行文本降级为单行输入(2026-10 起,此前标「不支持」) |
| `NumberEditor` | `number` | |
| `ComboBox` | `select` | |
| `ComboCheckBox` | `multiselect` | |
| `RadioGroup` | `radio` | |
| `CheckBoxGroup` | `checkbox` | 复选框**组**，选项来自 `<Dictionary>`，值是数组 |
| `CheckBox` | `switch` | 单个布尔勾选。**不可与 `CheckBoxGroup` 合并映射**，见 §3 #2 |
| `FormSubmitButton` | `query` | 查询按钮(仪表盘过滤栏没有这个按钮概念,`.frm` 转换时丢弃,过滤栏用即时查询) |
| `TreeComboBoxEditor` | `tree-select` | 分层数据集树:单表自引用→UNION 扁平节点数据集;否则懒加载 `treeLevels`;层级信息不全→标红 |

### 2.2 下拉选项来源

| 帆软 | magic | 映射 |
|---|---|---|
| `CustomDictionary`(`<Dict key value>`) | `props.customBinding`(`optionsBindingType="custom"`) | key→value、value→label。⚠️ 运行时读的是 `customBinding`(早期文档写成 `props.options`,不准) |
| `TableDataDictionary` | `props.datasetBinding{datasetName,labelField,valueField}`(`optionsBindingType="dataset"`) | 取字典绑定的数据集与显示/实际列;**字典数据集本身被别的参数过滤时改走 `remote`**(否则选中后下拉只剩一项) |
| `DatabaseDictionary`(直连表字典) | 自动合成 `SELECT DISTINCT 显示[,值] FROM 表` 数据集 + `datasetBinding` | 不再标红 |
| 服务器数据集字典 | 按同名公共数据集引用(`assume_public_datasets`) | 清单见 `_public_datasets.txt` |

### 2.3 通用字段

| 帆软 | magic |
|---|---|
| `WidgetName name` | `parameterName`(同时是参数名) |
| **多值控件**(`ComboCheckBox`/`CheckBoxGroup`) | 参数 `datatype="List"`(**不是 String**,见下) |
| `LabelName` | `label` |
| `BoundsAttr x/y/width/height` | `position{x,y,width,height}` |
| `widgetValue`(常为公式) | 参数 `defaultValue`(公式经表达式翻译,`defaultValueIsExpression=true`) |
| `allowBlank=false` | `props.required=true` |
| 面板 `delayPlaying=true` | `<setting fetchDataWhenOpen="false">`(取反) |

### 2.4 参数类型(从控件推断,比从默认值猜准)

`DateEditor`→`Date`/`DateTime`(看 format)、`NumberEditor`→`Number`、
`CheckBox`→`Boolean`、**`ComboCheckBox`/`CheckBoxGroup`→`List`**、其余→`String`。

#### ⚠️ 多值参数为什么必须是 `List`(2026-08-13 真机 group_demo 实证)

声明成 `String` 时,后端 `Datatype.String.parse` 原样放行,**首屏**参数值是字符串 `"1"`;
而 SQL 侧的动态 IN 片段生成的是 `$p.join("','")` —— String 上没有 `join` 扩展方法,
会误命中 JDK 静态 `String.join(sep)`(变参为空)恒返 `""` → 空值守卫恒真 →
**整段 IN 条件从 SQL 里消失**,不报错、直接返回全量数据。

真机后端日志(修复前 / 修复后同一张报表首屏):

```sql
-- 修复前：病区默认值 "1" 完全没进 SQL
) t where 1=1
 and t.riqilx = ?

-- 修复后（datatype="List"）
) t where 1=1
 and t.bqid in ('1')
 and t.riqilx = ?
```

用户**手动勾一次**之后前端提交的是数组,`.join` 就正常了 —— 所以这个 bug 只在
「打开就查」的首屏出现,线上极难被发现。声明 `List` 后 `Datatype.List.parse` 走
`ListValueParser`(`"1"` → `["1"]`、`""` → 空集合),前端复选框/多选下拉也能正确回显默认勾选。

---

## 3. 差异 / magic 接不住的项 + 兼容或扩充建议

| # | 帆软特性 | 频次 | magic 现状 | 建议 |
|---|---|---|---|---|
| 1 | **自定义 JS 监听**(`afteredit` 等,做级联下拉/自定义校验) | 831 | 查询组件无 JS 钩子 | **兼容**:省→市这类**级联下拉**可尝试映射 magic `tree-select` 或「数据集随上级参数过滤」近似;任意业务 JS → **标红交人工**。**扩充**(加 JS 钩子)成本高、属产品决策,暂不建议 |
| 2 | ~~**单个 `CheckBox`**(布尔勾选)~~ | 172 | **已解决**(2026-08-13):magic 新增 `switch` 组件 | 见下方「#2 已解决」 |
| 3 | **`FreeButton` 自定义按钮** | 389 | `query`/`reset` | 现状:一律**标红交人工**(未按文案推断成 `query`/`reset`) |
| 4 | **`EditorHolder` 容器控件** | 18 | 无对应 | **标红**(极少,人工处理) |
| 5 | **控件级装饰样式**(每控件字体/边框/背景) | 多 | `component.style` 仅 `labelWidth/width/showLabel/labelPosition` | **兼容**:丢弃装饰样式,保留标签/位置/尺寸。查询面板美观损失很小 |
| 6 | **面板标题 / 窗口位置 / 对齐**(`PWTitle`/`windowPosition`/`align`) | 全量 | `queryFormSetting` 无面板级元数据 | **兼容**:丢弃(magic 面板自带样式)。如需保留面板标题 → 可**扩充** `ReportQuerySetting` 加 `title` 字段(小改) |

> 仅 #1(自定义 JS 联动)是有规模的硬 gap;#3–#6 都能确定性映射或低成本近似/降级。

### #2 已解决(2026-08-13)

这条 gap 在文档里挂了很久但**从没落进 `convert.py`** —— `WIDGET_TYPE` 把 `CheckBox` 和
`CheckBoxGroup` 一起写成了 `checkbox`。真机(住院病人信息查询「包含冲销」)的表现是:

- 单个 `CheckBox` 没有 `<Dictionary>` → `_fill_options` 直接 `return` → `props` 为空;
- 前端 `el-checkbox-group` 循环空选项数组 → **渲染出一个什么都看不见的空容器**;
- 转换报告一条提示都没有(info 级问题当时既不进 `_issues.txt` 也不进报告)。

现在的做法(sight-report 侧同步新增了 `switch` 组件类型):

| 项 | 取值 | 为什么 |
|---|---|---|
| `type` | `switch` | magic 2026-08-13 新增的布尔开关,不需要选项 |
| `label` | `<Text>` 的内容 | 勾选框旁那行字才是可见文案。`LabelName` 常是设计器残留(真机上是「不为0:」) |
| 参数 `datatype` | `Boolean` | 声明成 String 时后端 `Datatype.String` 原样放行 `"false"`,SQL 里的 `$p == true` 恒不成立**且不报错** |
| 参数 `defaultValue` | `widgetValue` 的 `<O t="B">` | `true`/`false` 二选一,绝不写空串(后端对 `""` 是旁路返回、不转 Boolean) |
| SQL | `$p == true` 原样保留 | 布尔参数已排除出「多选 `.join`」与「`'${p}'` 内联字面量」两条改写路径 |

外观从勾选框变成开关,这一点会在转换报告的「ℹ️ 自动处理说明」里逐条列出。
回归用例:`test_query_widgets.py`(单 `CheckBox` / `CheckBoxGroup` / `RadioGroup` 三者互不串味)。

---

## 4. 落地建议

**应实现(确定性,覆盖绝大多数)**
1. 解析 `ReportParameterAttr` 的 `WParameterLayout` 控件 → 按 §2.1/§2.2 生成 `queryFormSetting` 组件 JSON(保留位置)。
2. 参数类型改为**从控件推断**(§2.4),默认值取 `widgetValue`(公式走翻译器)。
3. `allowBlank=false`→`required`;`delayPlaying`→`setting fetchDataWhenOpen`(取反)。

**标红交人工**
- 含自定义 JS 监听的控件(级联/校验)、`FreeButton` 自定义动作、`EditorHolder`。
- 转换报告逐条列出:哪个参数的控件带 JS、降级成了什么。

**可选扩充(magic 侧小改,非必须)**
- `ReportQuerySetting` 增 `title`(面板标题)。
- 若需保留「不自动查询」之外的面板行为,再议;当前 `fetchDataWhenOpen` 已够。

> 自定义 JS 联动若量大且重要,后续可配 AI:把帆软 JS + 上下文交 LLM,产出 magic 的
> 「数据集按参数过滤」或 tree-select 配置,再人工确认。

---

## 5. 2026-08 之后的变化(与 sight-report 现状对照)

**转换器已落地(原文档未提或写法不准)**
- 成对「开始/结束」日期 → `queryFormSetting.validations` 的 `dateOrder` 跨字段校验(按参数名/标签关键词判定角色,数量不等不强加)。
- 极窄(<35px)文本/数值框视为 JS 驱动的隐藏辅助控件,跳过渲染、保留参数。
- 日期型参数不再内联成字符串,多选参数声明 `List`,布尔参数声明 `Boolean`(见 `function-mapping.md` §3.6)。

**sight-report 新增、转换器尚未利用**(可作为下一步)
- `date-range`(2026-09-16,「日期范围」):评估后**有意不合并**成对日期,仍转两个独立 `date` 控件 + `dateOrder`。理由:
  ① 日期范围只能绑**字符串**参数,而帆软日期参数转过来是 `Date`/`DateTime`,SQL 里按日期类型处理的写法(比较/formatDate)要连带改;
  ② 它的默认值只有固定 `defaultStart/defaultEnd` 和快捷项,表达不了帆软常见的 `=today()-100`、`=DATEINMONTH(today(),1)` 这类公式默认值,合并会丢默认区间;
  ③ 日期时间(`yyyy-MM-dd HH:mm:ss`,占全库 5749 个日期控件的绝大多数)不在它的粒度(日/月)内。
  只有「按月/按天、固定默认、字符串参数」的新建报表才适合直接用;转换器保持两个独立日期框以保证行为 1:1。
- 选项级联(2026-08-14):绑定数据集的下拉会跟随其他查询条件重新取数——可覆盖一部分「级联下拉」的自定义 JS(§3 #1),
  目前 JS 联动仍整体标红。
- `record-selector`(搜索选择)、`reset`(重置按钮):转换器未产出。
- 仪表盘过滤栏还有 `scope/exclude`(作用于哪些区块)、`field`(按列筛选)、`trigger`(即时/按钮),详见 `docs/dashboard-format-notes.md` §D。
