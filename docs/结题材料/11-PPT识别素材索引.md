# STrans PPT 识别素材索引

## 1. 推荐主素材

| 素材 | 文件 | 建议用途 | 使用说明 |
|---|---|---|---|
| 前端实时识别全景 | `output/ppt-assets/images/frontend_realtime_live12.png` | “系统运行效果”主图 | 展示 CUDA 已连接、真实视频、3 辆车、检测框、拥堵和事件 |
| 多车辆识别短片 | `output/ppt-assets/videos/live12_multi_vehicle_6s.mp4` | 车辆检测/跟踪页 | 6 秒、1920×1080、H.264；连续 24 帧稳定 3 辆车 |
| 车牌识别短片 | `output/ppt-assets/videos/live3_plate_recognition_6s.mp4` | 车牌与白名单页 | 6 秒、1920×1080、H.264；显示 OCR 框与车牌文本，须注明结果待真值复核 |
| 12 路机位总览 | `output/dataset-evaluation/inventory/contact-sheet.jpg` | 数据集与场景覆盖页 | 展示 12 路沙盘机位及综合演示场景 |
| 代表识别结果拼图 | `output/dataset-evaluation/run-2026-07-14-gpu/selected-contact-sheet.jpg` | 算法效果与案例页 | 包含多车、车牌、停车场、桥梁和隧道等代表帧 |
| 道路建模工具全景 | `output/playwright/road-modeler/road-modeler-page.png` | 道路空间建模/系统工具页 | 展示节点组、车道、建筑物、摄像头标定、Canvas 和 JSON 输出区域 |
| 软件工程图谱总览 | `output/ppt-assets/diagrams/contact-sheet.png` | 架构与算法素材选型 | 11 张可编辑 UML/工程图的缩略索引，不建议直接作为答辩主图 |
| 系统组件架构图 | `output/ppt-assets/diagrams/component-architecture.svg` | “系统总体架构”主图 | SVG 无损缩放；PNG 版本可兼容旧版 PowerPoint |
| 答辩版用例概览 | `output/ppt-assets/diagrams/use-case-overview.svg` | “功能模块与用例”主图 | 完整用例图另存为 `use-case.svg`，建议仅用于报告附图 |
| 算法演进路线图 | `output/ppt-assets/diagrams/algorithm-evolution-flow.svg` | “算法迭代路线”主图 | 七阶段节点内包含 Git 提交号证据 |

## 2. 可作为正向案例的单图

路径：`output/dataset-evaluation/run-2026-07-14-gpu/selected/`

- `live12_030.00s_d3.jpg`：三车检测，推荐作为车辆检测主例图；
- `live3_090.08s_d3.jpg`：近景车辆与车牌文本，推荐作为 OCR 示例；
- `live10_030.03s_d2.jpg`：双车道路场景；
- `live7_090.09s_d2.jpg`：高位道路双车场景；
- `live9_090.00s_d2.jpg`：隧道入口双车场景；
- `live5_030.03s_d1.jpg`：桥出口单车场景。

## 3. 建议同时展示的失败案例

- 前端实时全景图中的两个 `road_obstacle_candidate` 位于道路箭头区域，可作为“真实测试驱动算法迭代”的案例；
- 综合演示代表帧中的远景疑似误检，可用于说明通用模型在沙盘尺度下的域差异；
- live3 的车牌文本数量与稳定车辆数不完全一致，可用于说明车牌—轨迹关联和时序投票的迭代方向。

## 4. PPT 放置建议

1. 项目总体效果页：使用前端实时识别全景图；
2. 车辆检测算法页：嵌入 `live12_multi_vehicle_6s.mp4`，旁边标注“连续 24 帧稳定识别 3 辆车”；
3. 车牌识别页：嵌入 `live3_plate_recognition_6s.mp4`，标注“真实沙盘 OCR 示例，准确率待真值评测”；
4. 数据集与测试页：使用 12 路机位总览和 65 帧 CUDA 指标；
5. 算法迭代页：并列放置正确车辆框和道路箭头误报，说明下一轮道路标线抑制与事件去重方案。
6. 道路空间建模页：使用道路建模工具全景，配三步说明“可视化建模 → `road_logic_modeler.v1` → RoadLogicService 实时映射”。
7. 系统设计与算法页：按 `13-软件工程图谱与PPT素材.md` 的页码映射选择 SVG，避免直接截取代码或把完整用例图压缩到一页。

## 5. 素材技术信息

两个 MP4 均已经 FFprobe 验证：

- 编码：H.264；
- 分辨率：1920×1080；
- 帧率：4 FPS；
- 时长：6 秒；
- 大小：约 2.2–2.4 MB；
- 无音轨，适合答辩时自动循环播放。

所有素材均来自 F 盘真实沙盘视频或真实前端运行页面，不使用合成识别结果。
