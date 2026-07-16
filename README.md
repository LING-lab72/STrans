# STrans 云边端协同智慧交通视觉感知系统

STrans 面向学院智慧交通沙盘，使用手机、RTSP 摄像头或本地视频作为边端采集源，在电脑端完成车辆检测、ByteTrack 跟踪、车牌识别、白名单判断、道路异常分析、拥堵热力图和禁停告警，并通过 React 监控大屏展示结果。

## 主要功能

- 登录、注册、图片验证码和管理员/普通用户权限
- 多路沙盘 RTSP、手机 IP Webcam、本地图片与视频接入
- YOLO11s / VisDrone 车辆检测、ByteTrack 跟踪和 HyperLPR3 车牌识别
- 白名单车辆管理与放行/拦截判断
- 车辆监控和道路异常两种独立任务模式
- 拥堵热力图、禁停告警、速度估算和道路建模
- 功能中心：历史记录、告警处置、账号安全、摄像头、白名单、模型、用户和审计日志
- DeepSeek 检测成果智能分析报告
- CPU、GPU、显存、内存和推理耗时监控
- Web Speech API 前端语音控制

## 目录

```text
backend/        FastAPI、SQLite、视频接入和本地模型服务
frontend/       React + Vite 监控大屏
algorithms/     算法模型与说明
docs/           接口和架构资料
交付文档/       需求、设计和答辩材料
一键启动项目.bat
```

## 结题仓库与开发基线

本仓库是项目唯一的后续开发主线和结题交付仓库。算法调优、功能迁移、自动化测试、结题文档和演示版本均以本仓库为准。

- [架构决策：以 fork 作为结题与后续开发仓库](docs/decisions/ADR-001-fork-as-final-repository.md)
- [迁移与结题开发指南](docs/migration/fork-convergence-plan.md)

从旧工作区迁移功能时，应保留本仓库的识别算法、ByteTrack 参数和数据趋势仪表盘，按指南逐项迁移测试、持久化、部署和文档，禁止使用旧文件整体覆盖。

## 环境准备

建议使用 Python 3.11 或 3.12、Node.js 20 及 NVIDIA CUDA 环境。

```powershell
cd backend
python -m pip install -r requirements.txt

cd ..\frontend
pnpm install --frozen-lockfile
```

首次创建数据库前必须通过环境变量设置至少 12 位的管理员初始密码：

```powershell
$env:STRANS_ADMIN_PASSWORD="请设置至少12位强密码"
```

## 启动

双击根目录的 `一键启动项目.bat`，或分别启动：

```powershell
cd backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

```powershell
cd frontend
pnpm dev -- --host 0.0.0.0
```

访问 `http://localhost:5173`。后端健康检查地址为 `http://127.0.0.1:8000/api/health`。

## 数据持久化

SQLite 数据库位于 `backend/data/traffic_analysis.db`，保存用户、会话、检测历史、白名单、告警处置、摄像头配置、智能报告和审计日志。交付前应备份该文件。

## 演示建议

1. 登录后启动一路沙盘摄像头。
2. 展示车辆检测、跟踪、车牌和白名单结果。
3. 打开拥堵图和禁停告警。
4. 切换道路异常模式，演示异物或行人检测。
5. 在功能中心展示历史、告警处置、设备和用户权限。
6. 展示系统资源监控与智能分析报告。

## 注意事项

- 校园网环境下确认电脑能够访问沙盘 RTSP 地址。
- 同时开启过多摄像头会增加解码和显存压力，系统默认限制活跃视频流数量。
- Web Speech API 需要新版 Edge 或 Chrome，并允许网页使用麦克风。
- 首次建库未设置 `STRANS_ADMIN_PASSWORD` 时，后端会拒绝启动；已有数据库升级不受影响。

## 手机摄像头云端转发

Ubuntu 云服务器上的 MediaMTX 转发、鉴权、手机推流和项目接入说明见：

```text
deploy/mediamtx/README.md
```
