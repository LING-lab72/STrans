# STrans 软件工程图谱与 PPT 素材

## 1. 图谱设计原则

本图谱以当前仓库实现、CodeGraph 模块关系、系统测试证据和 Git 提交历史为事实基线。图中实线表示当前实现或当前主流程；注释中的“后续”“改进项”表示尚未完成的演进方向，答辩时不得表述为已交付功能。

- 统一使用 PlantUML 可编辑图源，字体、色板、线条和分辨率由 `diagrams/theme.iuml` 管理；
- 系统边界使用 UML 用例图、组件图、部署图、活动图、时序图和状态图表达；
- 算法演进和道路建模链路属于工程流程图，不冒充 UML 行为模型；
- 完整图用于报告附图，精简图用于 16:9 答辩页；
- 系统视频源统一表述为固定摄像头、RTSP/MJPEG、手机/USB 和本地文件，不包含已经退出方案的旧设备。

## 2. 图源与成品索引

PNG 可直接插入 PPT，SVG 用于无损缩放和后续编辑。渲染成品位于 `output/ppt-assets/diagrams/`。

| 图 | 软件工程视图 | 主要说明 | PPT 建议 |
|---|---|---|---|
| `use-case-overview` | UML 用例图（精简） | 普通用户、管理员、视频源、报告服务与六类核心用例 | 第 5 页主图 |
| `use-case` | UML 用例图（完整） | 用户功能、管理配置、识别与数据闭环的完整系统边界 | 报告附图或拆分讲解 |
| `component-architecture` | UML 组件图 | CameraHub、识别服务、道路逻辑、业务存储、API、React 和道路建模工具 | 第 4 页主图 |
| `deployment-architecture` | UML 部署图 | 浏览器、Windows 应用主机、NVIDIA GPU、摄像头、外部服务和本地桥接的部署关系 | 系统架构页右侧或附图 |
| `realtime-analysis-sequence` | UML 时序图 | 启动摄像头、取帧、调度、车辆/异常分析、持久化和 MJPEG 返回 | 系统运行机制页 |
| `vehicle-recognition-activity` | UML 活动图/泳道 | 预处理、检测跟踪、车牌稳定、白名单、速度和拥堵输出 | 第 6 页左图，右侧写三点优化 |
| `road-anomaly-activity` | UML 活动图 | 道路 ROI、帧差/光流、合法目标解释、外观过滤、多帧确认 | 第 8 页左图，右侧放误报案例 |
| `road-model-pipeline` | 工程流程/组件流水线 | 可视化建模、JSON 校验审核、单应映射和道路状态分析 | 第 9 页或道路建模专项页 |
| `adaptive-scheduler-state` | UML 状态图 | quality、balanced、realtime、protect、anomaly 与 manual 的切换条件 | 第 10 页主图 |
| `data-closed-loop-sequence` | UML 时序图 | 分析记录、告警证据、SHA-256 清单、处置和智能报告归档 | 第 11 页主图 |
| `algorithm-evolution-flow` | 工程演进路线图 | 从可行性验证到结题集成的七阶段提交证据 | 第 12 页主图 |

总览图：`output/ppt-assets/diagrams/contact-sheet.png`。

## 3. 统一视觉语义

| 颜色 | 语义 |
|---|---|
| 蓝色 | 系统边界、核心组件、正常状态和主调用链 |
| 绿色 | 数据存储、产物、完成后的有效输出 |
| 橙色 | 外部依赖、告警、审核点或需要答辩强调的风险 |
| 灰色 | 基础设施、辅助服务和上下文信息 |
| 紫色/红色浅底 | 算法阶段差异、资源保护或异常优化阶段 |

PPT 中不要重新绘制或改变同一颜色的含义。图标题建议放在幻灯片标题栏，插图时可裁掉图内标题以减少重复。

## 4. 16:9 页面排版建议

1. 组件图、状态图、数据闭环时序图：宽度占页面 75%–90%，下方用一句话给结论；
2. 部署图、道路建模、车辆/异常活动图：左侧图占 48%–58%，右侧放“输入—核心方法—输出/限制”；
3. 算法演进图：横向通栏展示，提交号保留在节点内，页脚注明“依据 Git 历史归纳”；
4. 完整用例图信息密度高，报告中使用；答辩优先使用 `use-case-overview`；
5. PNG 用于稳定交付，若 PPT 支持 SVG，优先插入 SVG 以避免缩放模糊。

## 5. 可复现渲染

项目本地工具为 `output/tooling/plantuml/plantuml-1.2026.6.jar`。在仓库根目录执行：

```powershell
$jar = (Resolve-Path 'output\tooling\plantuml\plantuml-1.2026.6.jar').Path
$src = (Resolve-Path 'docs\结题材料\diagrams').Path
$out = (Resolve-Path 'output\ppt-assets\diagrams').Path
java -DPLANTUML_LIMIT_SIZE=8192 -jar $jar -charset UTF-8 -checkonly "$src\*.puml"
java -DPLANTUML_LIMIT_SIZE=8192 -jar $jar -charset UTF-8 -tsvg -o $out "$src\*.puml"
java -DPLANTUML_LIMIT_SIZE=8192 -jar $jar -charset UTF-8 -tpng -o $out "$src\*.puml"
```

当前图谱均可由 PlantUML 内置的 Graphviz 渲染链路生成，因此未使用生成式图片（0/3）。这样可以保留可审查的结构、准确的模块名称和后续可编辑性；若后续需要封面概念图或极复杂的跨层鸟瞰图，再单独使用生图额度。

## 6. 答辩证据边界

- “已实现”：必须能由代码入口、调用关系、测试、真实页面或真实视频素材支撑；
- “真实识别效果”：与 `11-PPT识别素材索引.md` 中的 F 盘数据和实时前端素材配套使用；
- “精度”：当前无完整真值时使用“样例统计/演示结果”，不得写成严格 Precision、Recall；
- “道路建模”：当前是项目内置可视化工具、JSON 导出和 RoadLogicService 消费链路，发布审核仍以人工流程为主；
- “道路异常”：道路箭头等高对比标线仍可能形成候选事件，应把该失败案例作为下一轮标线抑制和事件去重依据。
