# 参数 & 查询组件:帆软 ↔ sight-report 实证对比与兼容方案

> 基于全库 3364 张 `.cpt` 的真实分布,把帆软「查询面板 + 报表参数」逐项对照 magic 的
> `queryFormSetting`(`ReportQueryComponent`,见 `.../types/report-query-types.ts`)
> 与 `<parameter>` / `<setting>`,标出可确定性映射的部分,以及 magic 接不住、需「兼容(近似/降级)」
> 或「扩充(magic 加能力)」的部分。

---

> **状态:§2 / §4「应实现」部分已编码完成**(convert.py 的 `_parse_query_panel`):
> 全库 3290 面板 / 30,950 组件转换、XSD 通过、随机样本 JSON 全合法。§3 的 gap 按方案标红交人工。

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
| `DateEditor` | `date` | 由 `DateAttr format` 推 `datePickerType`:含 `HH`→`datetime`,`yyyy-MM`→`month`,否则 `date`;`format`/`valueFormat` 原样带 |
| `TextEditor` | `input` | |
| `NumberEditor` | `number` | |
| `ComboBox` | `select` | |
| `ComboCheckBox` | `multiselect` | |
| `RadioGroup` | `radio` | |
| `CheckBoxGroup` | `checkbox` | |
| `FormSubmitButton` | `query` | 查询按钮 |

### 2.2 下拉选项来源

| 帆软 | magic | 映射 |
|---|---|---|
| `CustomDictionary`(`<Dict key value>`) | `props.options`(`optionsBindingType="custom"`) | key→value、value→label |
| `TableDataDictionary` | `props.datasetBinding{datasetName,labelField,valueField}`(`optionsBindingType="dataset"`) | 取字典绑定的数据集与显示/实际列 |

### 2.3 通用字段

| 帆软 | magic |
|---|---|
| `WidgetName name` | `parameterName`(同时是参数名) |
| `LabelName` | `label` |
| `BoundsAttr x/y/width/height` | `position{x,y,width,height}` |
| `widgetValue`(常为公式) | 参数 `defaultValue`(公式经表达式翻译,`defaultValueIsExpression=true`) |
| `allowBlank=false` | `props.required=true` |
| 面板 `delayPlaying=true` | `<setting fetchDataWhenOpen="false">`(取反) |

### 2.4 参数类型(改为从控件推断,比从默认值猜准)

`DateEditor`→`Date`/`DateTime`(看 format)、`NumberEditor`→`Number`、其余→`String`。
当前实现是从默认值字符串猜,应改为优先用控件类型。

---

## 3. 差异 / magic 接不住的项 + 兼容或扩充建议

| # | 帆软特性 | 频次 | magic 现状 | 建议 |
|---|---|---|---|---|
| 1 | **自定义 JS 监听**(`afteredit` 等,做级联下拉/自定义校验) | 831 | 查询组件无 JS 钩子 | **兼容**:省→市这类**级联下拉**可尝试映射 magic `tree-select` 或「数据集随上级参数过滤」近似;任意业务 JS → **标红交人工**。**扩充**(加 JS 钩子)成本高、属产品决策,暂不建议 |
| 2 | **单个 `CheckBox`**(布尔勾选) | 172 | magic `checkbox` 是复选框**组** | **兼容**:降级为单选项 checkbox 组,或布尔 `select`(是/否)。语义损失小 |
| 3 | **`FreeButton` 自定义按钮** | 389 | 仅 `query`/`reset` | **兼容**:文案/动作是标准查询、重置 → `query`/`reset`;带自定义 JS 动作 → 标红 |
| 4 | **`EditorHolder` 容器控件** | 18 | 无对应 | **标红**(极少,人工处理) |
| 5 | **控件级装饰样式**(每控件字体/边框/背景) | 多 | `component.style` 仅 `labelWidth/width/showLabel/labelPosition` | **兼容**:丢弃装饰样式,保留标签/位置/尺寸。查询面板美观损失很小 |
| 6 | **面板标题 / 窗口位置 / 对齐**(`PWTitle`/`windowPosition`/`align`) | 全量 | `queryFormSetting` 无面板级元数据 | **兼容**:丢弃(magic 面板自带样式)。如需保留面板标题 → 可**扩充** `ReportQuerySetting` 加 `title` 字段(小改) |

> 仅 #1(自定义 JS 联动)是有规模的硬 gap;#2–#6 都能确定性映射或低成本近似/降级。

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
