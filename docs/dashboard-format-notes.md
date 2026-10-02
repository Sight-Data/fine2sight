# SightReport 仪表盘（fileType="dashboard"，.mrs）格式速查 —— 给 fine2sight 转换器用

> 来源均在 `$HOME/mnt/sight-data-code`（下文简称 `R/`）。下面第 A 节的完整示例已用
> `xmllint --noout --schema R/apps/backend/sight-platform/src/main/resources/ai-docs/report-template.xsd -` 实测 **validates**。
> 真实样本：`R/docs/dashboards/*.mrs`（5 张，xmllint 全部通过）与 `R/apps/backend/sight-report-boot/src/main/resources/demo/reports/仪表盘/*.mrs`。

## 0. 关键源文件（带行号）

| 内容 | 文件:行 |
|---|---|
| 根元素顺序、dashboard/mobile/datawall 命名陷阱 | `ai-docs/report-template.xsd:775-868`（meta 属性 1248-1360；根属性 ~907-934） |
| FilterBar / Layout / Row / Column / Tabs 容器 / Pane / BlockRef / Blocks / Block 的 XSD | `report-template.xsd:3065-3290` |
| 模型 TS 类型（权威，含默认值/常量） | `R/apps/web-report/src/views/report/design/dashboard/types/index.ts` |
| XML 生成器（属性顺序、默认值不写） | `.../dashboard/utils/xml/generator.ts`；解析器同目录 `parser.ts` |
| **IR 类型 = 各区块 props 的"人话版"契约** | `R/apps/web-report/src/views/report/design/ai/dashboard-ir/types.ts` |
| **IR → XML 编译器（Java，props 键名的最终真值，转换器最该照抄）** | `R/apps/backend/sight-report/src/main/java/com/sight/report/mcp/ir/dashboard/DashboardIrCompiler.java`：根装配 69-305、参数 315-392、过滤项选项 394-471、toBlock 473-713、图表指标 941-1121、KPI 1173-1250、交互 1270-1352、明细 1399-1448、表格点击 1458-1540、dataset XML 1544 |
| AI 用的 IR 提示词（版面惯例/选型惯例） | `R/apps/backend/sight-platform/src/main/java/com/sight/feature/ai/service/AiPromptService.java:466-619` |
| 设计文档 | `R/docs/report-仪表盘-设计.md`（§2.2 文件格式 88；§4.2 布局模型 215；§5.6 主题 331；§6 过滤栏 396；§7 取数/下推 442；§8 钻取联动 848） |
| mockup | `R/docs/report-仪表盘-mockup.html`、`R/docs/report-仪表盘-mockup-医院.html` |
| 表格列配置/条件格式 | `.../dashboard/utils/table.ts:46-160, 600-680` |
| 图表配置构建 | `.../dashboard/utils/chart-config.ts`（measuresOf 188、buildChartConfig 370、buildChartOption 597、legend/grid 724-760） |
| KPI 计算 | `.../dashboard/utils/kpi.ts` |
| 主题预设 | `.../dashboard/utils/theme.ts:117-165` |
| 布局 CSS 换算 | `.../dashboard/utils/layout-style.ts` |
| 过滤控件模型 | `R/apps/web-report/src/views/report/design/types/report-query-types.ts`（46-61 控件类型；119-345 props） |
| 结构校验器（后端） | `R/apps/backend/sight-report/src/main/java/com/sight/report/application/DashboardStructureValidator.java` |
| 过 XSD 的护栏测试 | `.../dashboard/utils/xml/__tests__/xsd-contract.test.ts`；`R/apps/backend/sight-report-boot/src/test/java/com/sight/apps/setup/DemoReportXsdTest.java` |

⚠️ ai-docs/*.md（report-design-guide、grid/document skill）里**没有**仪表盘专篇；仪表盘的"技能文档"就是 AiPromptService 里的 IR 提示词 + 设计文档。

---

## A. 根 XML 骨架 + 完整最小示例

### A.1 铁律
1. 根元素 `<report xmlns="http://sightdata.top/schema/report-template" fileType="dashboard" reportId="<24位hex>">`。
   样本只写这三个属性（`reportName`/`version` 样本里都没有，XSD 允许；`password`/`draft` 禁止写）。
   **`version` 不写 → 导入只存成草稿**（修改记录 2026-09 条：demo 的 .mrs 因此全是草稿，导入器随后自动 publish；重复导入同 reportId 只更新草稿）。reportId 缺省则每次导入新建一份，转换器最好生成稳定的 24 位 hex（样本是 md5(key)[:24]）。
2. **子元素顺序固定**：`meta → fonts? → dataset* → parameter* → queryFormSetting → filterBar → layout → blocks`（XSD:787-788）。
3. **除根外每个子元素都要带 `xmlns=""`**（XSD `elementFormDefault="unqualified"`；不带则 xmllint 校验失败）。示例里 `<meta xmlns="" …>`、`<dataset xmlns="" …>`、`<parameter xmlns="" …>`、`<queryFormSetting xmlns="">`、`<filterBar xmlns="">`、`<layout xmlns="">`、`<blocks xmlns="">` 都带；`dataset` 内部的 `<sql>/<field>/<data>`、`layout` 内部的 `tabs/tab/row/...`、`blocks` 内部的 `block/propsJson` 不用再写。
4. 区块内容放 `<blocks><block id type title><propsJson><![CDATA[{JSON}]]></propsJson></block></blocks>`，版面放 `<layout><tabs><tab id name><row>…`。**版面与内容靠 id/ref 关联**，每个 block id 必须被某个 `<block ref>` 引用一次且仅一次（重复引用打开时会被克隆并改名 `__dupN`；没被引用的永不显示；悬空 ref 显示空白——校验器告警）。
5. `meta` 必须写 `schemaVersion="1"`（恒写）。新建模板建议加 `aggregationMode="pushdownFirst"`（编译器就这么做）。**不要写** `viewMode` / `designWidth`（已废弃）。
6. 默认值一律不写（generator 约定）：row 默认 `heightMode=fixed`，`block/column size` 默认 1，`filterBar` 默认 `layout=inline labelPosition=inline trigger=instant debounceMs=300 overflow=drawer`，`item width=auto`。多写一般也能读，但设计器脏检查是 XML 全等比较，会"一打开就提示有未保存改动"。
7. CDATA 里是 JSON，键名区分大小写；propsJson 里**中文字段名直接写**即可。props 顶层空容器（`{}`/`[]`）不要写。
8. `meta@theme` 允许值：`default | medical | gold | custom`（custom 时加 `themePrimary="#rrggbb"`，可选 `themePalette="#a,#b,…"`）；`themeMode="auto|light|dark"`（auto 不写）；可选 `minWidth`(默认 960) `maxWidth`(默认 0=不限) `refreshIntervalSeconds`(秒) `cacheTtlSeconds`(秒，封顶 3600)。

### A.2 完整最小示例（已过 XSD）

```xml
<report xmlns="http://sightdata.top/schema/report-template" fileType="dashboard" reportId="0123456789abcdef01234567"><meta xmlns="" schemaVersion="1" theme="medical" aggregationMode="pushdownFirst"/><dataset xmlns="" id="ds01" name="运营KPI" type="sql" dataSourceId="" dataSourceName="demo"><sql><![CDATA[select 214836 as 门急诊人次, 201000 as 门急诊人次同期, 6.8 as 平均住院日, 7.2 as 平均住院日同期, 28.4 as 药占比]]></sql><field name="门急诊人次" type="Integer" label="门急诊人次"/><field name="门急诊人次同期" type="Integer" label="门急诊人次同期"/><field name="平均住院日" type="BigDecimal" label="平均住院日"/><field name="平均住院日同期" type="BigDecimal" label="平均住院日同期"/><field name="药占比" type="BigDecimal" label="药占比"/></dataset><dataset xmlns="" id="ds02" name="月度趋势" type="builtin"><field name="月份" type="String" label="月份"/><field name="门诊" type="Integer" label="门诊"/><field name="住院" type="Integer" label="住院"/><data><![CDATA[[["2026-05",20100,6100],["2026-06",21300,6400],["2026-07",21480,6842]]]]></data></dataset><dataset xmlns="" id="ds03" name="科室明细" type="sql" dataSourceId="" dataSourceName="demo"><sql><![CDATA[select dept_name as 科室, count(*) as 出院人次, round(avg(los_days),1) as 平均住院日 from demo_hosp_inpatient_case where discharge_date between cast(${$p_start} as date) and cast(${$p_end} as date) and (coalesce(cast(${$p_dept} as varchar),'') = '' or dept_group = ${$p_dept}) group by 1]]></sql><field name="科室" type="String" label="科室"/><field name="出院人次" type="Integer" label="出院人次"/><field name="平均住院日" type="BigDecimal" label="平均住院日"/></dataset><parameter xmlns="" id="pm01" name="p_start" datatype="Date" required="false" defaultValueMode="value" defaultValueIsExpression="false" defaultValue="2026-07-01"/><parameter xmlns="" id="pm02" name="p_end" datatype="Date" required="false" defaultValueMode="value" defaultValueIsExpression="false" defaultValue="2026-07-31"/><parameter xmlns="" id="pm03" name="p_dept" datatype="String" required="false" defaultValueMode="value" defaultValueIsExpression="false" defaultValue=""/><queryFormSetting xmlns=""><![CDATA[{"components": [{"id": "flt_start", "type": "date", "label": "统计起始", "parameterName": "p_start", "position": {"x": 0, "y": 0, "width": 190, "height": 32}, "props": {"placeholder": "选择日期", "clearable": true, "datePickerType": "date", "format": "yyyy-MM-dd", "valueFormat": "yyyy-MM-dd"}, "style": {}}, {"id": "flt_dept", "type": "select", "label": "科室", "parameterName": "p_dept", "position": {"x": 0, "y": 0, "width": 170, "height": 32}, "props": {"placeholder": "全部", "clearable": true, "optionsBindingType": "custom", "customBinding": [{"label": "内科", "value": "内科"}, {"label": "外科", "value": "外科"}]}, "style": {}}]}]]></queryFormSetting><filterBar xmlns=""><item componentId="flt_start"/><item componentId="flt_dept"/></filterBar><layout xmlns=""><tabs><tab id="tab_1" name="总览"><row height="108"><block ref="k1"/><block ref="k2"/><block ref="k3"/></row><row height="320"><block ref="c1" size="2"/><column size="1"><block ref="c2"/><block ref="c3"/></column></row><row height="280"><block ref="r1" size="1"/><block ref="er1" size="2"/></row><row heightMode="auto"><block ref="t1"/></row></tab></tabs></layout><blocks xmlns=""><block id="k1" type="kpi" title="门急诊人次"><propsJson><![CDATA[{"datasetName": "运营KPI", "valueField": "门急诊人次", "compareField": "门急诊人次同期", "compareLabel": "较去年同期", "unit": "人次"}]]></propsJson></block><block id="k2" type="kpi" title="平均住院日"><propsJson><![CDATA[{"datasetName": "运营KPI", "valueField": "平均住院日", "compareField": "平均住院日同期", "unit": "天", "direction": "negative", "precision": 1, "deltaMode": "absolute"}]]></propsJson></block><block id="k3" type="kpi" title="药占比"><propsJson><![CDATA[{"datasetName": "运营KPI", "valueField": "药占比", "unit": "%", "precision": 1, "direction": "negative", "threshold": {"value": 30, "bound": "max", "warnGap": 3, "label": "红线 30%"}}]]></propsJson></block><block id="c1" type="chart" title="门诊 / 住院趋势"><propsJson><![CDATA[{"datasetName": "月度趋势", "chartType": "bar", "dimensionField": "月份", "valueField": "门诊", "aggregation": "sum", "extraMeasures": [{"field": "住院", "agg": "sum", "type": "line", "axis": "right"}]}]]></propsJson></block><block id="c2" type="chart" title="住院人次走势"><propsJson><![CDATA[{"datasetName": "月度趋势", "chartType": "area", "dimensionField": "月份", "valueField": "住院", "aggregation": "sum"}]]></propsJson></block><block id="c3" type="chart" title="科室构成"><propsJson><![CDATA[{"datasetName": "科室明细", "chartType": "pie", "dimensionField": "科室", "valueField": "出院人次", "aggregation": "sum", "pieRing": true, "pieCenterText": "total", "pieCenterLabel": "出院人次"}]]></propsJson></block><block id="r1" type="rank" title="科室出院人次 TOP 8"><propsJson><![CDATA[{"datasetName": "科室明细", "dimensionField": "科室", "valueField": "出院人次", "aggregation": "sum", "topN": 8, "unit": "人次", "precision": 0}]]></propsJson></block><block id="er1" type="embeddedReport" title="科室运营月报" embeddedReportId="REPLACE_WITH_TARGET_REPORT_ID"/><block id="t1" type="table" title="科室明细"><propsJson><![CDATA[{"datasetName": "科室明细", "columnSetting": {"columns": {"科室": {"width": 120, "fixed": "left"}, "出院人次": {"align": "right", "formatType": "number", "format": "0,0"}, "平均住院日": {"align": "right", "formatType": "number", "format": "0.0", "label": "平均住院日（天）", "rules": [{"operator": "greatThen", "value": 9, "color": "#c23a3a", "bold": true}]}}, "summary": {"text": "合计", "columns": {"出院人次": "sum"}}}}]]></propsJson></block></blocks></report>
```

示例说明：
- 过滤栏 = `queryFormSetting`（CDATA JSON `{"components":[…]}`，与 grid 报表同一套控件模型）+ `filterBar/item@componentId` 指向 `components[].id`；控件的 `parameterName` 必须有同名 `<parameter>`，数据集 SQL 用 `${$p_start}` 引用。
- 示例用了 `builtin` 数据集（`<data>` 内 CDATA 紧凑 JSON 二维数组，列序与 `<field>` 同序）与 `sql` 数据集（`dataSourceName` 填已有数据连接名；`dataSourceId=""` 样本都这么写）。
- `embeddedReportId` 必须替换成真实的 grid/document 报表 id（**不能是仪表盘自己**；挂在 `<block>` 属性上，不在 propsJson 里）。
- 示例里没演示的版面形态：`<column>`（已演示）、行内页签容器 `<tabs><pane id name>…</pane></tabs>`（见 `docs/dashboards/门诊流量动态监测.mrs` 的 `row > tabs > pane > block`）、多个顶层 `<tab>`。

---

## B. 每种区块：type 与 propsJson

区块 type 全集：`chart | map | kpi | rank | table | text | richtext | image | embeddedReport`（`BlockElement@type` 在 XSD 里是 xs:string，不做枚举校验；编译器白名单见 `DashboardIrCompiler.java:40`）。
> 注意：仪表盘里**没有** `report` 类型——"嵌入报表"就是 `type="embeddedReport"` + 属性 `embeddedReportId`（`report` 只存在于移动页 .mrm 的 MobileBlockType）。
`block` 属性：`id`(必填) `type`(必填) `title` `embeddedReportId`；其余全部在 propsJson。

### B.0 通用：数据绑定与聚合
- `datasetName`：引用 `<dataset name>`（中文名直接写）；不存在则区块为空。字段名必须是该数据集 `<field name>`。
- 聚合枚举：`sum | avg | max | min | count | distinctCount`（count=行数，distinctCount=去重计数）。**聚合在后端做**（先试下推到 SQL GROUP BY，不行回内存），所以图表/排行的数据集可以是明细行，也可以是已汇总行（但对已汇总数据集配 count 恒为 1）。
- 数据集粒度坑（设计文档 §7.2 grain）：**明细数据集配给 KPI 不写 `valueAggregation` = 取第一行**，不是合计。SQL 已汇总成一行时才不写；返回多行要汇总就写 `valueAggregation`。
- 联动/明细/下钻/点击动作键（chart/map/rank 共用，见 B.8）。

### B.1 `kpi`（指标卡）
| key | 类型/枚举 | 说明 |
|---|---|---|
| datasetName | string | |
| valueField | string **必填** | 主数值列；不写 valueAggregation 时取数据集**第一行** |
| valueAggregation | sum/avg/max/min/count/distinctCount | 让数据库把整个结果汇总成一个数。（⚠️ 不是 `aggregation`，KPI 不读它） |
| unit | string | 数值后缀（人次/天/%/万） |
| precision | 0-4 | 小数位，默认 0；千分位自动 |
| compareField (+compareDatasetName, comparePick) | 同数据集列 | 对比值（同期/上期）。涨跌 = (value-compare)/compare，基期 0 退回绝对值。跨数据集时 `compareDatasetName` + `comparePick`(single/first/last/sum) 必填 |
| compareLabel | string | 如「较去年同期」 |
| deltaMode | `percent`(默认) \| `absolute` | 住院日用 absolute：「▼ 0.4 天」 |
| direction | `positive`(默认,涨好) \| `negative`(涨坏，药占比/住院日/次均费用) \| `neutral`(不判好坏) | 决定涨跌绿/红 |
| threshold | `{value:number, bound:"max"|"min", warnGap?:number, label?:string}` | 红线：max=不得超过(药占比≤30)，min=不得低于(床位使用率≥85)。越线「超红线 x」红；距离 ≤ warnGap(默认 阈值10%) 「距红线 x」警示 |
| targetValueField (+targetValueDatasetName, targetValuePick) | 列 | 目标/对标值（进度条+「完成x%」；逆向指标文案改为「低于/高于…」） |
| targetLabel | string | 「同级均值」「月度目标」，缺省「目标」 |
| subField (+subDatasetName, subPick) / subLabel / subPrecision | 列/文案/0-4 | 副指标小字（「日均 6,930」「手术 3,216」） |
| trendField (+trendDatasetName) / trendValueMode `last`(默认)\|`total` | 列 | 迷你趋势：取该列所有行画折线（数据集需按时间排序）。**配了趋势，主数值=趋势末点**（不再读第一行）；跨数据集时 trendValueMode 无意义 |
| accentColor | #hex | 卡片左侧强调色条 |
| crossFilterIgnore | bool | 不接受别人点出来的联动（如全院合计卡） |
| detailDatasetName / detailMapping / detailParameter | 见 B.8 | 「⋯ → 查看明细」只有 KPI 有 |
行高：KPI 行 `height="108"`（实测）。一行 3~6 张，每张 `<block ref>` 等宽。

> IR 里这些键名的对应：compareField→`compareField`，targetField→`targetValueField`，`targetDataset`→`targetValueDatasetName`，`targetPick`→`targetValuePick`，`compareDataset`→`compareDatasetName`，`subDataset`→`subDatasetName`，`agg`→`valueAggregation`（编译器 1133-1250）。

### B.2 `chart`
通用键：`datasetName`、`chartType`、`dimensionField`(必填，维度/类目；散点=X 轴字段)、`valueField`(必填；散点=Y 轴字段)、`aggregation`(缺省 sum)、`valueLabel`(图例名，缺省取字段 label)、`unit`(轴名+tooltip 后缀；饼图中心合计后缀)。

`chartType` 取值（前端 `DashboardChartType`）：`bar | line | area | pie | funnel | gauge | radar | scatter | effectScatter | sankey | map`。IR 允许集（生成器推荐）：`bar line area pie funnel gauge radar scatter sankey`（`map` 用独立 `map` 区块，`effectScatter` 不建议）。`area` = 带 areaStyle 的折线（ECharts 无独立 area）。**没有 smooth/平滑线的 prop**；样式微调只能走隐藏键 `chartOption`（B.2.4）。

#### B.2.1 多指标 / 双轴 / 柱+线（仅 bar/line/area）
存储非对称：**第一个指标在扁平键**，第 2 个起进 `extraMeasures`：
- 扁平（第一指标）：`valueField` `valueLabel` `aggregation` `valueAxis`(`"right"` 挂右轴) `valueChartType`(`bar|line`，柱+线组合时指定) `valueColor`(#hex) `valueLineType`(`solid|dashed|dotted`) `valueOpacity`(0-1)。
- `extraMeasures`: `[{field, label?, agg?(缺省 sum), axis?:"right", type?:"bar"|"line", color?, lineType?, opacity?, role?: "refLine"|"band"|"compare"}]`
  - `role:"refLine"` 不画系列，取第一个非空值画**横向参考线**（基准/目标线；label 当线名）；`role:"band"` 值为真的类目画**背景带**（周末/节假日）；`role:"compare"` 仍画系列但是虚线+透明度 0.6（「去年同期」）。第一个指标不能有 role。
  - 双轴典型：`valueChartType` 不写(柱) + extraMeasures `{"field":"完成率","agg":"avg","type":"line","axis":"right"}`。
- `stacked: true|false`（bar/line/area；右轴指标不参与；配了 colorField 的柱图缺省自动堆叠，`false` 关闭）。
- `colorField`：同一指标按该列的**值**分色/拆系列（图例项=值；此时 extraMeasures 不生效，只取第一个指标）。
- `horizontal: true`：横向条形（仅 bar；有指标挂右轴时不生效）。
- `showValueLabel: true`：柱/线上写数值（堆叠写合计）。
- `topN`(0-50, 仅 bar/line/area/pie)、`sortBy`(`value-desc|value-asc`)、`othersLabel`(topN 截掉的其余合并成此名称)。
- `dimensionGrain`: `day|week|month|quarter|year`（仅 bar/line/area/pie/funnel；维度是日期列时由后端按桶重聚合，免写 DATE_FORMAT；**配了粒度后点击联动/明细被禁用**）。
- 类目轴：`axisLabelMode:"all"`(全部显示，不隔一个) `axisLabelRotate`(0-90) `axisLabelWidth`(px，超出截断)。
- 面积图：`chartType:"area"`（可配 stacked）。
- 饼图（`chartType:"pie"`，维度=扇区名，单指标）：`pieRing:true`(环形，48%/72%) `pieCenterText:"total"`(中心显示合计) `pieCenterLabel`(合计标题) `pieRadius:["48%","72%"]` `pieCenter:["50%","50%"]`；所有饼图自动带占比标签。
- 漏斗 `funnel`、仪表盘 `gauge`：单维度单指标，同饼图的 fieldValue 模式。
- 雷达 `radar`：维度每个值=一根轴，整份数据一条轮廓。
- 散点 `scatter`：`dimensionField`=X、`valueField`=Y（原始点，不聚合；单位字段在 props 里没有 aggregation 语义）。
- 桑基 `sankey`：`dimensionField`=起点、`targetField`=终点（**必填**，缺则不出图）、`valueField`=流量。

#### B.2.2 颜色/主题/图例
- 颜色默认全跟主题色板（meta.theme），**不要在区块里写死颜色**；只有 `valueColor` / extraMeasures[].color 可覆盖单系列。
- 默认 option（前端 buildChartOption）：tooltip(类目图 axis / 分色或非直角 item)，legend `{show:true,type:"scroll",bottom:0,left:"center",itemWidth:18,itemHeight:10,itemGap:12,textStyle.fontSize:11}`（map/gauge 关闭），grid `{left:48,right:24,top:24,bottom:48(无图例24),containLabel:true}`，横向条形 y 轴 inverse。
- 隐藏逃生口 `chartOption`: **JSON 字符串**（不是对象），深合并到默认 option 上（顶层配置 tooltip/legend/visualMap/坐标轴/grid 保留，series 级配置会被后端数据覆盖）。仅在必要时用。

#### B.2.3 其它
- 区块级 `pushdown:"never"` 关闭该区块的聚合下推（数字不对时的现场退路）。

### B.3 `rank`（排行榜：名次+名称+条+数值，按数值降序）
`datasetName` `dimensionField`(名称) `valueField` `aggregation`(缺省 sum) `topN`(0-50，0/缺=全部；行高 280 约放 8 条) `unit` `precision`(0-4，默认 1) `abbreviate`(bool，默认 true：整列都到万级才缩写「x.x 万」，否则千分位；`false` 强制千分位)。交互键同 chart（B.8）。取数与柱状图同一路径。

### B.4 `table`（明细表：纯行集，虚拟滚动，不走 grid 引擎）
- `datasetName`；**可见列/顺序由数据集 `<field>` 顺序（SQL SELECT）决定**，`columnSetting` 只覆盖展示（覆盖式）：
```jsonc
"columnSetting": {
  "columns": { "<字段名>": {
      "label": "表头名(优先于字段label)", "width": 120, "align": "left|center|right",
      "fixed": "left|right", "formatType": "date|datetime|number|currency|percent", "format": "0,0.00 / YYYY-MM-DD",
      "rules": [ { "operator": "greatThen|EqualsGreatThen|lessThen|equalsLessThen|equals|contains",
                   "value": 30, "color": "#c23a3a", "background": "#c23a3a", "bold": true } ]   // 按序，第一条命中即停；数值比较不了=不命中
  } },
  "groups": [ { "label": "分组表头", "children": [ { "field": "列" } ] } ],   // 可选分组表头；未被引用的列追加末尾
  "summary": { "text": "合计", "columns": { "出院人次": "sum" } }          // sum|avg|count|max|min|distinctCount；或 {"text":"合计","source":"dataset","datasetName":"X"} 取另一数据集第一行
}
```
- 分页：SQL 数据集的 table 自动后端分页（默认 50/页，含全表合计下推）；非 SQL 数据集退回前 10000 行截断。**不需要也没有 pageSize prop**。
- 行高：`<row heightMode="auto">`（内容撑开，实际封顶 560px 内部滚动）或 `height="360/400"`。
- 点击：`rowAction:{type:"detail|link|event", reportId?}` 整行；`columnActions:[{field,type:"detail|link|event|none",reportId?}]` 列级（列级压过行级）；`detailDatasetName/detailMapping`、`links`、`pointAction.eventName`。未配=不可点。
- 另有 `crossFilterIgnore`。表格单元格没有右键菜单。

### B.5 `map`（仅省级地图，ECharts geo）
`datasetName` `dimensionField`(**必须是省份名**；下钻后为市/区县) `valueField` `aggregation` `valueLabel` `extraMeasures`(第 2 个起只进 tooltip/标签) `labelMode:"none|name|full"`(旧 `showLabel:true`=full) `adcode`(缺省 "100000" 全国；样本有 "330604" 区级) `displayMode:"region"(默认)|"bubble"` `drillEnabled`(默认 true) `drillPath`。交互键同 chart。

### B.6 `text` / `richtext` / `image` / `embeddedReport`
- text：`content`(string) `fontSize`(10-48) `align:left|center|right` `bold` `tone:default|secondary|primary|danger`（用主题色，不写颜色）。行高 64。
- richtext：`content`(HTML，白名单净化；IR 的 `text` 一行一段 + `**粗体**`/`__下划线__` 会被编译成 HTML)。不绑字段，`{{…}}` 不会换数。
- image：`src`(外链/`data:image`/站内路径；`javascript:`、`file:`、`data:text` 等会被拦) `alt` `fit:contain(默认)|cover|fill` `link`。行高 200。
- embeddedReport：无 propsJson；属性 `embeddedReportId=<被嵌 grid/document 报表 id>`。被嵌报表自动继承仪表盘当前**过滤栏参数**（同名参数透传），隐藏工具栏/查询表单。嵌自己=无限递归被拦。

### B.7 过滤栏的图表联动 / 下钻 / 明细 键（chart / map / rank 通用，table/kpi 部分适用）
| key | 说明 |
|---|---|
| crossFilterMode | `"auto"`(点数据点→其他组件按该列筛，免写 SQL 参数；设计器新建默认) \| `"parameter"`(写入参数 `crossFilterParameter`，要求受影响数据集 SQL 引用该参数) \| `"none"`。**缺省按"写入参数"**，没配参数则联动实际关闭（存量模板行为），所以转换器想要联动必须显式写 `auto` |
| crossFilterParameter | parameter 模式的目标参数名 |
| crossFilterScope | auto 模式筛谁：缺省(=`dataset`) 只筛**同数据集**组件；`"all"` 筛所有数据集里有同名列的 |
| crossFilterIgnore | true=不接受别人的联动 |
| drillPath | `[{ "field":"科室","label":"科室" },{ "field":"医生","label":"医生" }]`，**第一项=图上当前维度**，其后依次下钻（面包屑 + 「↑上层」）；右键菜单「下钻到…」 |
| detailDatasetName | 明细数据集（通常回原始表）。有同名维度列自动按点中值 `where 列=值`；否则用 `detailMapping:[{field,to}]` 把字段值送给明细 SQL 的 `${$to}`；旧样本用 `detailParameter:"p_drill_town"`（单键，兼容） |
| pointAction | 左键动作 `{type:"detail|crossFilter|link|event|none", reportId?, eventName?}`；缺省=配了 detailDatasetName 则 detail，否则 crossFilter；配了 dimensionGrain 时强制 none |
| links | `[{reportId,label,openMode:"dialog|dialogMax|tab"}]` 跳转报表（右键「跳转到…」；仅 grid/document 报表，不能是仪表盘） |
`eventName`：发给宿主页面的 postMessage 事件名，禁 `report:` 前缀。

---

## C. 版面树规则

- 结构：`layout > tabs > tab(id,name) > row*`。tab 的直接子元素只能是 `<row>`。**tab 要有唯一 id**（缺 id/重复会被自动改名）。顶层多 tab = 页签页（每页独立的一套版面，筛选栏与数据集全页共用，只有当前页签取数）。
- `row`：横向排列子节点，子节点宽度按 `size`(flex-grow，基准 0%)分配；高度由 row 决定：`height`(px，heightMode=fixed 默认) 或 `heightMode="auto"`。**高度不参与比例分配**。row 嵌在 column 内时，`row@size` = 纵向份额。
- `column`：纵向排列，可含 `block / row / tabs`；`size` 为在父 row 中的宽度份额，`minSize` 最小像素(默认 80)。
- `block ref size? minSize?`：`size` 缺省 1。
- 行内页签容器：`row|column|pane` 内 `<tabs size? minSize? activePaneId?><pane id name required>(block|row|column)*</pane>+</tabs>`（≥1 个 pane；隐藏页不取数）。注意与顶层 `layout/tabs` 同名不同义。
- **深度上限 4**（tab 内从 row 起：row(1)→column(2)→row(3)→block(4)；页签页本身不计）。超出校验器告警、设计器难编辑。
- 尺寸单位：宽 = 比例份额（无单位）；高 = px。没有栅格/断点：嵌套 flex，容器宽度自适应；`meta@minWidth`(默认 960)以下横向滚动，`maxWidth`(默认0=铺满)以上居中留白。PC 优先，窄屏无专门重排。
- 推荐行高（`defaultRowHeightFor`）：kpi 108、rank 280、text 64、image 200、其余 320；明细表 400 或 auto。
- 区块外框：头高 34px、区块间距 12px、卡片圆角 6px、KPI 主数 24px/600、辅助 11.5px；**区块头标题=`block@title`**（无 subtitle 字段）；头右侧统一「⋯」菜单（导出/全屏/刷新；「查看明细」仅 KPI）。区块五态 loading/ok/empty/error/timeout 自动处理。
- 单页看板常见 6~12 个区块；KPI 行放最前（3~6 个）。

---

## D. 过滤栏

### D.1 filterBar
`<filterBar [layout="inline"] [labelPosition="inline|top|none"] [trigger="instant|button"] [debounceMs="300"] [overflow="drawer|wrap"]><item componentId width? scope? exclude? field?/>…</filterBar>`
- `item@componentId` 必填，指向 queryFormSetting.components[].id；`width`: `auto|grow|<px>`。
- `scope="blockId1,blockId2"`：只作用这些区块；`exclude="…"`：除这些外全部；互斥，同时给以 scope 为准；缺省=全部区块。（只影响"该参数发不发给某区块"）
- `field="列名"`：**按字段筛选**——该控件值作为列条件直接作用在声明了这一列的数据集上（单选=、多选 in、日期区间=起止，日期时间列"止"含当天），不必在 SQL 里写 `$参数`；数据集 SQL 已引用该参数的按 SQL 走。缺省=按参数。
- 控件超出走「更多筛选」浮层（`overflow=drawer`）。`trigger=instant` 即时查询带 300ms 防抖；区块 >12 或有慢数据集建议 `button`。

### D.2 控件（queryFormSetting.components[]）
```jsonc
{ "id":"flt_x", "type":"select", "label":"科室", "parameterName":"p_dept",
  "position":{"x":0,"y":0,"width":170,"height":32}, "props":{ ... }, "style":{} }
```
`type`：`text | input | number | select | multiselect | tree-select | date | date-range | checkbox | radio | switch | record-selector | query | reset`（IR 只暴露 `select multiselect date input number`；仪表盘 position 只是占位，布局由 filterBar 流式排列，样本一律 `{x:0,y:0,width:170~260,height:32}`）。
- **日期**：`type:"date"`，`props.datePickerType` ∈ `date | datetime | year | month | time`；**精度、`format`、`valueFormat` 必须配套**：date→`yyyy-MM-dd`；datetime→`yyyy-MM-dd HH:mm:ss`；year→`yyyy`；month→`yyyy-MM`；time→`HH:mm:ss`。（真实样本写的是 `"subtype":"date"`，运行态实际只读 `datePickerType`，缺省按天——转换器请写 datePickerType+format+valueFormat。）参数声明 `datatype="Date"`（月/年粒度时参数声明 String 更稳：样本 p_m1 就是 String）。
- **日期范围**：`type:"date-range"`（新控件，左侧快捷项+双日历），`parameterName`=起，`props.endParameterName`=止（**需各自声明一个 `<parameter>`**），`props.granularity:"date"|"month"`，`shortcuts?`、`defaultShortcut?`、`defaultStart/defaultEnd`（月粒度 "2025-09"）、`maxSpan?:{value,unit:"day"|"month"}`、`grainParameterName?`。SQL 写 `between ${$起} and ${$止}`。例（`上虞区域…mrs`）：`{"type":"date-range","parameterName":"p_m1","props":{"granularity":"month","endParameterName":"p_m2","required":false,"defaultStart":"2025-09","defaultEnd":"2026-08"}}`。也可用两个独立 `date` 控件。
- **下拉 select/multiselect** 选项来源 `props.optionsBindingType`（缺省 custom）：
  - `custom`：`customBinding:[{"label","value"}]`
  - `dataset`：`datasetBinding:{datasetName,labelField,valueField,distinct:"true"}`（该数据集 SQL 若本身按此参数过滤，选中后下拉只剩一项→改用 sql 来源）
  - `sql`：`sqlBinding:{datasourceName,sql,labelField,valueField}`
  - `formula`：`formulaBinding:{expression,labelField?,valueField?}`；`remote`：大字典服务端搜索。
  - 常用 props：`placeholder`、`clearable:true`、`required`、`maxCollapseTags`、`optionsCascade`(缺省开：选项 SQL 引用了别的参数就级联重取)。
- 参数 `<parameter id name datatype required="false" defaultValueMode="value" defaultValueIsExpression="false" defaultValue="" [elementDatatype] [description]/>`；`datatype` ∈ `String|Number|Boolean|Date|DateTime|List`。**多选必须声明 `datatype="List"`**（否则 IN 条件整段消失；数值多选加 `elementDatatype="Number"`）；SQL：`coalesce(col in (${$p}), true)` 或 `col in (${$p})`。
- 数据集 SQL 参数语法：`${$p}` / 裸 `$p` → 预编译 `?` 绑定；`#{...}` → 表达式字面量拼接（过注入校验）；List 自动展开。参数缺省 `defaultValue` 在无值时生效。**每个被 SQL 引用的 `${$x}` 都要有同名 `<parameter>`**（否则按 String 自动补，且设计器告警）。
- 联动/下钻用的内部参数（样本里的 `p_dept`、`p_drill_town`…）也是普通 `<parameter>`，不需要控件。

### D.3 绑定与优先级（设计文档 §8.5）
过滤栏 > 联动 > 钻取路径（过滤栏与联动同写一个参数时过滤栏优先；联动默认排除源区块；「重置」清联动+钻取）。联动走**参数/列条件下推到后端**，不是前端行过滤（避免 TopN 之后再过滤的错误）。

---

## E. 视觉约定（设计文档原文要点 + 样本做法）

- 主题（`meta@theme`）三套内置，`id` 为跨端契约：
  - `default` 默认蓝：primary `#3d7eff`，palette `#3d7eff #7aa7ff #a8c5ff #d6e3ff #5b8def #2b5fd9`
  - `medical` 医疗青（**医院首选**）：primary `#1e88a8`，palette `#1e88a8 #4fa8c4 #7cc0d4 #8fcadb #cfe8f0 #14647c`，primaryLight `#e8f4f8`，border `#a8d5e2`
  - `gold` 金色：primary `#a16207`(浅)/`#e0b34d`(深)，palette `#a16207 #c08a2e #d3a961 #e0c391 #efe0c6 #7a4a05`
  - `custom`：`themePrimary` + 可选 `themePalette`（样本：`theme="custom" themePrimary="#1e88a8" themePalette="#1e88a8,#e08a33,#8a6fb0,#4c8c4a,#c94f5c,#3d6fa8"` 用于多系列需要区分色时）。
  - 中性：text `#303133/#606266/#c0c4cc`，border `#dcdfe6/#e4e7ed`，page `#f5f7fa`，卡片 `#fff`；**语义色不随主题**：success `#67c23a`、warning `#e6a23c`、danger `#f56c6c`。
- 设计文档规则：区块一律从主题令牌取色、**不硬编码颜色**；同一页图表共用一套色板；表格条件格式用 `#c23a3a` 红 / `#277a37` 绿（样本）。
- **KPI 卡**：主数 24px/600；副信息 11.5px；逆向指标（药占比/住院日/次均费用）必须写 `direction:"negative"`；红线指标写 `threshold`；有政策线/同级均值就用 `targetValueField`+`targetLabel`；「日均」「手术」这类写 `subField/subLabel`，别六张卡都写"较去年同期"（样本注释：后者六张卡说同一句话等于没说）。
- **版面惯例（AiPromptService IR 提示词）**：第一行 3~5(最多 6) 个 KPI（height 108）→ 每行 1~3 个区块（趋势折线 + 结构饼图互补）→ 明细表放最后（height 400 / auto）；一页总共 6~12 个区块；标题写业务语言（「本月出院人次」，不是 cnt）。
- **选型**：时间趋势→line/area；构成占比→pie(类别≤6)否则 bar；TOP N→`rank`（别用横向柱）；转化流程→funnel；达成率→gauge；A→B 流向→sankey（要 targetField）；省份分布→map（仅省级）；绩效四象限→scatter。
- **医院驾驶舱 mockup（`report-仪表盘-mockup-医院.html`，主色 `#1e88a8`，统计周期 2026-07，1500 床三甲量级）布局**：
  1. 标题条「某三甲医院 · 运营驾驶舱」+「数据截至…」+ 刷新/导出；页签：运营总览 / 科室分析 / 医疗质量 / 医保与费用。
  2. 过滤栏一行：统计期间 · 院区 · 科室 · 医保类型 · 更多筛选 · 重置（instant）。
  3. Row h=108：6 张 KPI——门急诊人次(▲6.8%+日均)、出院人次(▲4.2%+手术台次)、平均住院日(▼0.4天，逆向)、床位使用率(93.2%，合理区间 85~95%)、药占比(28.4%，红线30%，距红线1.6pp)、耗材占比(19.8%，目标≤20%)。
  4. Row h=280：左 size=2 门急诊人次趋势（今年 vs 去年同期 + 周末背景带 + 日均参考线）；右 column：医保结构环形饼(中心总收入)、门急诊时段分布柱图。
  5. Row h≈262-300：科室出院人次 TOP8（rank，可点击下钻）、手术分级构成（堆叠柱：四/三/二/一级）、次均费用（两张 KPI 上下：门诊 ¥428.6 vs 同级均值，住院 ¥16,842）。
  6. Row heightMode=auto：科室运营明细表（药占比>30%、耗材占比>40%、平均住院日>9 自动标红；状态列「超标/正常」红绿底；合计行）。
  7. 第二页签「科室分析」：CMI × 平均住院日四象限散点、科室费用结构堆叠柱、同级对比明细表。
  对应的可直接参考的真实 .mrs：`R/docs/dashboards/医院运营驾驶舱.mrs`（本文件 B 节示例键名都出自它）。

---

## F. 校验与坑

### F.1 怎么校验
1. **XSD（最直接）**：`xmllint --noout --schema R/apps/backend/sight-platform/src/main/resources/ai-docs/report-template.xsd your.mrs`（本机 `/usr/bin/xmllint` 可用；python lxml 也有）。官方护栏：`xsd-contract.test.ts`、`DemoReportXsdTest`（校验随包 40 张 demo）。XSD **不校验 propsJson 内容**（`BlockElement` 子元素为 `xs:any skip`），也不检查 id/ref 对应。
2. **后端结构校验器** `DashboardStructureValidator`（只产 warning，不是 error）：缺 layout/blocks、无 tab、block 无 id/id 重复、tab 无 id/重复、tab 内无区块、引用不存在的区块、区块定义了但无人引用、propsJson 非法 JSON、区块引用的数据集/对比/目标数据集不存在、queryFormSetting 非法 JSON、过滤栏引用不存在的控件、嵌套 >4、tabs 容器无 pane/pane 无 id/重复/默认页不存在、size 非正数。入口：HTTP `/api/ai/validate-xml`，或 MCP 工具 `validate_report_xml(xml, fileType="dashboard")`（`McpReportTools.java:99`，与设计器保存前同一套）。
3. 更多"悄悄不对"的运行期校验在前端 `dashboard/utils/*-check.ts`（联动参数 SQL 是否引用、明细映射、字段是否在数据集里…）——设计器保存前拦截。
4. 要看实际效果：把 .mrs 导入系统后用设计器打开，再看是否提示"未保存改动"（说明生成与设计器序列化有字节差异，不致命）。
5. 编译器路径是"已知正确"的参照：把转换结果想象成一份 Dashboard IR 的编译产物——属性顺序、`xmlns=""`、`propsJson` 编码、默认高度全部照 `DashboardIrCompiler.compile`（69-305）。

### F.2 坑（来自设计文档 / docs/sight-report-修改记录.md / 源码注释）
1. **子元素必须 `xmlns=""`**（不是继承根默认 ns），否则 XSD 失败（功能上解析器不区分，但是契约失败）。
2. **元素顺序**：`…parameter → queryFormSetting → filterBar → layout → blocks`；写反则脏检查假脏。dataset/parameter/queryFormSetting 在 XSD 里是 choice 可乱序，仍按上述顺序写。
3. 解析仪表盘**不能用 x2js/按标签归组**——row 里 `<block>`/`<column>`/`<tabs>` 交替出现，顺序即版面顺序（转换器若用 lxml 生成，保持 children 顺序即可）。
4. **KPI 取数**：不写 `valueAggregation`=第一行；配了 `trendField` 则大数=趋势末点。`aggregation`≠`valueAggregation`（KPI 只读后者）。
5. **联动缺省关闭**：chart/map/rank 不写 `crossFilterMode` 时等同"写入参数"模式且没配参数＝联动关；想要点击联动写 `"crossFilterMode":"auto"`。`crossFilterMode:"parameter"` 必须同时有 `crossFilterParameter`、该参数已声明、受影响数据集 SQL 引用了它，否则保存校验硬报错。
6. **明细**：`detailDatasetName` 的数据集既没有点中维度的同名列、SQL 也没引用同名参数、也没 `detailMapping` → 弹窗列出全量（静默）。**零配置没有明细**，必须配 detailDatasetName。
7. **多选参数必须 List 类型**；数值列 IN 用 `elementDatatype="Number"`。日期精度(`datePickerType`)与 `valueFormat` 要成套，否则 `= '2026-08'` 比较静默落空。
8. **map 的维度必须是省份名**（市/区县不支持，除非 adcode 下钻层）；**sankey 必须有 targetField**；**gauge/radar/scatter/sankey 各自 datasetConfig 形状不同**（前端自动处理，但字段含义不同：散点=X/Y 原始点）。
9. **`stacked`/`horizontal`/`showValueLabel`/`colorField`/`axis*` 只对 bar/line/area 生效**，用在饼图等会被忽略。`topN/sortBy/othersLabel` 仅 bar/line/area/pie。`dimensionGrain` 仅 bar/line/area/pie/funnel 且会禁用点击联动/明细。
10. **图表/排行取数是后端聚合**：数据集 SQL 带 `LIMIT`/TopN 会让联动/导出只对截断后的行聚合；排行榜需要先全量聚合再 topN（用 props.topN 而不是 SQL limit）。数据集有 `postScript`/存储过程/API 数据集不下推，只在内存聚合（行数上限默认 3 万，超限报错，API 数据集也受限）。
11. **下推方言白名单**：PostgreSQL / MySQL / MariaDB / H2 / SQLite 默认先试下推；SQL Server 点名拦下（派生表内 ORDER BY）。用户 SQL 以 `order by` 结尾的明细数据集在下推路径上类目轴顺序按维度升序，排行榜顺序由前端按数值降序，不依赖 SQL order by。
12. **分号**：SQL 末尾分号会被归一化抹掉，不是错误。
13. **embeddedReport** 不能嵌仪表盘；用 `embeddedReportId` 属性，不要在 propsJson 里写；不要给被嵌报表传 `embeddedReportId` 参数（会被当成宿主模板内子报表）。
14. **KPI 行高 108 是实测值**（区块头 34 + 内边距 20 + 边框 2 + 内容 52），不要给 KPI 行更大高度（会"字浮在中间一大块空"）；auto 行里表格封顶 560 内部滚动。
15. **block id 全局唯一；每个 id 恰好被引用一次**；同一区块摆两处会被克隆成 `__dupN`。
16. propsJson 损坏时设计器会保留原文，但**转换器输出必须是合法 JSON**；props 顶层空 `{}`/`[]` 请省略；`undefined` 值不能出现。
17. 主题 id 是跨端契约，只能写 `default/medical/gold/custom`；写别的会被当 default。
18. 版本字段：`schemaVersion` 固定 1；高版本引擎的模板在老引擎会明确报错。
19. 导入：**不写 `version` 属性只存草稿**，需发布才对查看端生效（demo 导入器会自动 publish）；reportId 相同且同目录=覆盖草稿。
20. 数据集字段 `type` 取值：`String Number Date DateTime Boolean Integer Long Double Float BigDecimal Short`；`<field label>` 缺省表头/图例名会退回字段名，转换时尽量写 label。
21. 过滤栏 `item@scope/exclude` 里写的是**区块 id**（不是标题；IR 层才用标题）。
22. 参数命名：`${$p_xxx}`；过滤栏日期区间的两个参数各自 `<parameter>`；转换帆软 `${param}` 时记得改成 `${$param}` 语法并声明参数。
23. 嵌套 `row > column > row`：内层 row 在 column 里时 `size` 才是纵向份额；顶层 row 的 `size` 无意义。
