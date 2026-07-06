# 模型权重目录

本目录用于放置本地推理测试所需的模型权重。

当前本机已下载：

```text
algorithms/models/yolov8n.pt
```

该文件用于 YOLOv8 nano 车辆/行人/障碍物检测测试。权重文件体积较大，已通过 `.gitignore` 忽略，不提交到仓库。

最小加载验证：

```powershell
python - <<'PY'
from ultralytics import YOLO

model = YOLO("algorithms/models/yolov8n.pt")
print(model.names)
PY
```
