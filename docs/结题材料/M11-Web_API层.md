# M11：Web API 层 — FastAPI 路由与流程整合

## 1. 模块定位

`backend/app/main.py` (877 行) 是整个系统的 API 入口和流程编排层。它将 14 个服务模块通过 FastAPI 路由连接为 RESTful API，并实现关键业务流程的端到端整合。

## 2. 路由分组 (按功能域)

| 路由前缀 | 功能域 | 接口数 | 核心入口 |
|---|---|---|---|
| `/api/auth/*` | 认证 | 6 | login, register, captcha |
| `/api/admin/*` | 管理 | 5 | users CRUD, audit |
| `/api/cameras/*` | 摄像头 | 12 | CRUD, mjpeg, model-mjpeg |
| `/api/video/*` | 旧版视频 | 4 | start, stop, mjpeg |
| `/api/algorithm/*` | 算法 | 3 | config, health, infer |
| `/api/analysis/*` | 分析 | 2 | latest, events |
| `/api/history/*` | 历史 | 3 | list, export, delete |
| `/api/incidents/*` | 告警 | 3 | list, update, evidence |
| `/api/whitelist/*` | 白名单 | 3 | CRUD, decision |
| `/api/intelligence/*` | 报告 | 4 | config, reports |
| `/api/road-anomaly/*` | 异常 | 3 | health, reset, analyze |
| `/api/road-model/*` | 道路 | 2 | model, heatmap |
| `/api/road-mask/*` | 分割 | 2 | health, camera mask |
| `/api/model-scheduler` | 调度 | 2 | state, configure |
| `/api/config/*` | 配置 | 2 | threshold |
| `/api/dashboard` | 仪表板 | 1 | 聚合快照 |
| `/api/models` | 模型 | 1 | 模型信息 |
| `/api/system/*` | 系统 | 2 | resources, weather |

**总计约 60 个端点**。

## 3. 关键流程整合

### 3.1 模型标注 MJPEG (`camera_model_mjpeg`)

这是系统最复杂的端点（main.py:388–513），整合了 6 个服务模块：

```
camera_model_mjpeg(camera_id, model_name="auto", task_mode="traffic|road_anomaly")
│
├── traffic 模式:
│   StreamingResponse(
│     local_model.annotated_mjpeg_frames(
│       camera_id,
│       frame_source = lambda: camera_hub.latest_jpeg(camera_id),
│       policy_provider = lambda: adaptive_scheduler.choose(...),
│       on_result = handle_traffic_result:
│         → road_logic_service.enrich(result)
│         → algorithm_client.push_result(result)
│         → analysis_store.save(result) # 每5秒
│     )
│   )
│
└── road_anomaly 模式:
    yield from anomaly_frames():
      while True:
        jpeg = camera_hub.latest_jpeg(camera_id)
        policy = adaptive_scheduler.choose(task_mode="road_anomaly")
        base, _ = local_model.infer_jpeg(include_people=True, policy=policy)
        anomaly = road_anomaly_service.analyze_jpeg(jpeg, base, static_scene=True)
        anomaly = _anomaly_only_result(anomaly)  # 过滤车辆检测
        → push_result, save, annotate, yield MJPEG frame
```

### 3.2 任务模式隔离 (`_anomaly_only_result`)

```python
def _anomaly_only_result(result):
    # 只保留异常相关检测
    filtered.detections = [
        d for d in result.detections
        if d.class_name == "pedestrian" (conf≥0.55)
        or d.class_name == "road_obstacle_candidate"
        or d.class_name.startswith("road_damage:")
    ]
    # 只保留异常事件
    filtered.events = [e for e in result.events
                       if e.type in {"road_pedestrian","road_obstacle","road_damage"}]
    # 清空交通统计
    filtered.traffic_stats = TrafficStats(congestion_level="unknown")
    return filtered
```

**关键设计**：异常模式的 YOLO 结果仅用于"解释合法道路使用者"，不输出车辆统计、不更新白名单、不影响拥堵图。

### 3.3 证据包下载 (`download_incident_evidence`)

```
1. 获取 incident 记录
2. 获取关联的 analysis_record → payload_json
3. 获取证据帧 → 标注渲染
4. 构建 manifest (package_version, generated_at, SHA-256)
5. ZIP打包:
   manifest.json + analysis-result.json + incident.json
   + evidence-frame-original.jpg + evidence-frame-annotated.jpg
   + README.txt
6. 审计日志
7. StreamingResponse (application/zip, Content-Disposition)
```

### 3.4 智能报告生成

```
POST /api/intelligence/reports
  → _report_context(camera_id): 构建数据快照
    - latest_result 的 traffic_stats + detections + events
    - road_logic.heatmap_snapshot().lane_stats
    - beijing_weather_service.snapshot()
    - analysis_store.list_records(limit=12)  # 最近12条历史
  → intelligence_report_service.generate(context, username)
    → DeepSeek API → 归档 → 返回报告
```

## 4. 权限依赖注入链

```python
current_user(authorization=Header(None))
  → auth_store.verify_token(token)
  → 401 if invalid

current_admin(user=Depends(current_user))
  → 403 if role != "admin"

# 使用模式:
@app.get("/api/history")              → Depends(current_user)
@app.post("/api/cameras")             → Depends(current_admin)
@app.get("/api/health")               → 无认证
@app.get("/api/cameras/{id}/mjpeg")   → 无认证 (img src无法带header)
```

## 5. CORS 配置

```python
app.add_middleware(CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

允许 localhost 和局域网 IP 的跨域请求，方便手机等设备访问。

## 6. API 设计模式

### 6.1 统一错误响应

```python
# 404: 资源不存在
raise HTTPException(404, detail="Camera not found: {id}")

# 400: 参数验证
raise HTTPException(400, detail="用户名已存在")

# 401/403: 权限
raise HTTPException(401, detail="Please login first.")
raise HTTPException(403, detail="Administrator permission required.")

# 503: 服务不可用
raise HTTPException(503, detail="Road mask model is unavailable.")
```

### 6.2 分页与筛选

```python
# 分页: limit参数 + min/max约束
@app.get("/api/history")
def history(limit: int = Query(30, ge=1, le=500), camera_id: str = None):
    return {"items": store.list_records(limit, camera_id),
            "total": store.count_records(camera_id)}
```

### 6.3 审计追踪

所有管理操作的 API 在完成后调用 `auth_store.add_audit(...)`，记录操作人、动作、目标和详情。

## 7. 服务单例

所有服务模块在导入时即初始化为模块级单例，main.py 中直接使用：

```python
from app.services.adaptive_scheduler import adaptive_model_scheduler
from app.services.auth_store import auth_store
from app.services.road_anomaly import road_anomaly_service
from app.services.road_logic import road_logic_service
from app.services.road_mask import road_mask_service
from app.services.whitelist import decide_plate, whitelist_store
# ...
```

`CameraHub`、`AlgorithmClient`、`AnalysisStore`、`LocalModelService` 在 main.py 中显式实例化。

## 8. 源码关键行号

| 功能 | 行号 |
|---|---|
| app 创建 + 中间件 | 53-69 |
| _annotate_evidence_image | 76 |
| _ensure_camera | 99 |
| _report_context | 104 |
| _anomaly_only_result | 143 |
| current_user / current_admin | 174/181 |
| camera_model_mjpeg (最复杂端点) | ~359-513 |
| traffic 模式 handle_traffic_result | 405-418 |
| anomaly_frames 生成器 | 420-481 |
| alert_incident evidence 下载 | 649-686 |
| 路由总表 | 187-877 |
