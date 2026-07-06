# STrans

智慧交通沙盘数字孪生实训项目资料与测试脚本。

当前阶段聚焦 ESP32-CAM 单摄像头接入：

- ESP32-CAM 组网与 CameraWebServer 测试；
- 浏览器访问 MJPEG 视频流；
- Python/OpenCV 拉取实时视频流并统计分辨率、帧率和截图；
- 为后续 ArUco 标定、沙盘坐标映射和数字孪生展示做准备。

## 目录

```text
智能交通沙盘数字孪生项目方案.md
ESP32-CAM阶段测试方案.md
esp32_cam_test/
  requirements.txt
  stream_test.py
  probe_esp32_cam.ps1
```

## 快速测试

安装 Python 依赖：

```powershell
cd D:\codeproject\STrans\esp32_cam_test
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

探测串口和局域网候选地址：

```powershell
.\probe_esp32_cam.ps1 -Port COM3
```

拉取 ESP32-CAM 视频流：

```powershell
python .\stream_test.py --url http://ESP32_CAM_IP:81/stream --seconds 10 --out esp32_cam_snapshot.jpg
```

## 参考资料

- Espressif Arduino ESP32 官方仓库 CameraWebServer 示例：<https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/CameraWebServer.ino>
- Espressif ESP32 Camera Driver：<https://github.com/espressif/esp32-camera>
- ESP32-CAM 智慧交通违章检测参考项目：<https://github.com/gremlinflat/ESP32-CAM---Smart-Traffic-Violation-System>
