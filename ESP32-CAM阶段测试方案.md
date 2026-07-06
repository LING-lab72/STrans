# ESP32-CAM 阶段测试方案

## 1. 本阶段目标

对应项目方案中的“阶段 1：单摄像头视频与标定验证”，先完成以下闭环：

```text
ESP32-CAM 接入 Wi-Fi
  -> 浏览器访问摄像头页面
  -> 获取 MJPEG 视频流地址
  -> Python/OpenCV 拉流测试
  -> 保存截图、记录分辨率和 FPS
  -> 后续接入 ArUco 标定
```

本阶段交付物建议包含：

- ESP32-CAM 烧录成功截图；
- 串口监视器中输出的 IP 地址截图；
- 浏览器视频流页面截图；
- Python 拉流测试输出；
- `esp32_cam_snapshot.jpg` 实拍效果图；
- 简短测试结论。

## 2. 需要安装的软件和插件

### Arduino 侧

1. Arduino IDE 2.x。
2. ESP32 开发板支持包：`esp32 by Espressif Systems`。
3. 若 Arduino IDE 无法搜索到 ESP32，在 `File -> Preferences -> Additional boards manager URLs` 添加：

```text
https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json
```

国内网络如果下载失败，可优先换网络、开代理，或按 Espressif 文档选择带 `-cn` 后缀的包版本。

### Python 侧

建议使用 Python 3.10 或 3.11。

```powershell
cd D:\codeproject\STrans\esp32_cam_test
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 3. 硬件连接

如果 ESP32-CAM 自带 USB 下载底板，直接插 USB 即可。

如果使用 USB-TTL 下载器，常见连接如下：

| USB-TTL | ESP32-CAM |
|---|---|
| 5V | 5V |
| GND | GND |
| TX | U0R |
| RX | U0T |
| GND | IO0 |

注意：

- 烧录时 `IO0` 接 `GND`；
- 烧录完成后断开 `IO0-GND`，按复位键重新启动；
- 供电尽量使用稳定 5V，摄像头启动瞬间电流不足会导致反复重启；
- 只在 3.3V 串口电平下接 TX/RX，避免损坏模块。

## 4. Arduino 烧录步骤

1. 打开 Arduino IDE。
2. 安装 ESP32 开发板支持包。
3. 打开示例：

```text
File -> Examples -> ESP32 -> Camera -> CameraWebServer
```

4. 修改 Wi-Fi：

```cpp
const char *ssid = "你的WiFi名称";
const char *password = "你的WiFi密码";
```

5. 选择摄像头型号，常见 ESP32-CAM 选择：

```cpp
#define CAMERA_MODEL_AI_THINKER
```

确保其他 `CAMERA_MODEL_...` 被注释掉。

6. 推荐 Arduino 工具设置：

| 设置项 | 建议值 |
|---|---|
| Board | AI Thinker ESP32-CAM |
| Upload Speed | 115200 或 921600 |
| Flash Frequency | 40MHz |
| Partition Scheme | Huge APP |
| Port | 实际串口 |

7. 烧录完成后，断开 `IO0-GND` 并复位。
8. 打开串口监视器，波特率 `115200`，记录输出的 IP 地址。

## 5. 浏览器功能测试

假设串口输出 IP 为：

```text
192.168.1.88
```

浏览器访问：

```text
http://192.168.1.88
```

点击页面中的 `Start Stream`，确认画面能连续刷新。

常见视频流地址：

```text
http://192.168.1.88:81/stream
```

常见单张图片地址：

```text
http://192.168.1.88/capture
```

## 6. Python/OpenCV 拉流测试

进入测试目录：

```powershell
cd D:\codeproject\STrans\esp32_cam_test
.\.venv\Scripts\Activate.ps1
```

执行 10 秒拉流测试：

```powershell
python .\stream_test.py --url http://192.168.1.88:81/stream --seconds 10 --out esp32_cam_snapshot.jpg
```

如果需要显示实时预览：

```powershell
python .\stream_test.py --url http://192.168.1.88:81/stream --seconds 10 --show
```

成功输出示例：

```text
OK: received 124 frames in 10.03s
Resolution: 640x480
Approx FPS: 12.36
Snapshot: D:\codeproject\STrans\esp32_cam_test\esp32_cam_snapshot.jpg
```

## 7. 测试记录表

| 测试项 | 预期结果 | 实际结果 | 结论 |
|---|---|---|---|
| ESP32-CAM 烧录 | Arduino IDE 显示上传成功 |  |  |
| Wi-Fi 连接 | 串口输出局域网 IP |  |  |
| 浏览器访问 | 能打开控制页面 |  |  |
| 视频流 | `Start Stream` 后画面连续刷新 |  |  |
| OpenCV 拉流 | 能读取帧并输出 FPS |  |  |
| 截图保存 | 生成 `esp32_cam_snapshot.jpg` |  |  |

## 8. 效果结论模板

```text
本阶段完成 ESP32-CAM 单摄像头接入测试。设备成功连接至局域网，浏览器可访问摄像头控制页面并获取实时 MJPEG 视频流。使用 Python/OpenCV 对视频流进行 10 秒拉流测试，共接收 ___ 帧，画面分辨率为 ___x___，平均帧率约 ___ FPS，并成功保存实拍截图。测试结果表明 ESP32-CAM 可作为智慧交通沙盘固定视觉采集节点，满足后续 ArUco 标定、车辆/障碍物识别和数字孪生映射的数据输入要求。
```

## 9. 常见问题

### 上传失败或一直等待连接

- 确认烧录时 `IO0` 已接 `GND`；
- 按住复位键后点击上传，出现 `Connecting...` 时松开；
- 降低上传速度到 `115200`；
- 检查 TX/RX 是否交叉连接。

### 串口反复重启

- 优先怀疑供电不足；
- 使用 5V 稳定供电；
- 避免只从弱电流 USB-TTL 的 3.3V 给摄像头供电。

### 浏览器打不开 IP

- 电脑和 ESP32-CAM 必须在同一局域网；
- Wi-Fi 名称和密码不要填错；
- 尽量使用 2.4GHz Wi-Fi，ESP32-CAM 不支持 5GHz Wi-Fi；
- 检查串口输出是否有 `WiFi connected`。

### OpenCV 无法拉流

- 先确认浏览器可以打开 `http://IP:81/stream`；
- 检查 URL 是否带端口 `:81`；
- 防火墙或校园网隔离可能会阻断局域网互访；
- 尝试让电脑连接手机热点，ESP32-CAM 也连接同一个热点。

## 10. 下一步：ArUco 标定

ESP32-CAM 拉流稳定后，下一阶段建议：

1. 打印 4 个 ArUco 标记，贴在沙盘四角或路口关键点；
2. 使用 OpenCV 从 ESP32-CAM 视频流中检测标记；
3. 计算图像坐标到沙盘坐标的 Homography；
4. 输出俯视映射图，为车辆、障碍物和路口数字孪生展示做准备。

## 11. 参考资料与公开仓库

- Espressif Arduino ESP32 官方 CameraWebServer 示例：<https://github.com/espressif/arduino-esp32/blob/master/libraries/ESP32/examples/Camera/CameraWebServer/CameraWebServer.ino>
- Espressif ESP32 Camera Driver：<https://github.com/espressif/esp32-camera>
- ESP32-CAM 智慧交通违章检测参考项目：<https://github.com/gremlinflat/ESP32-CAM---Smart-Traffic-Violation-System>
- CameraWebServer 独立参考仓库：<https://github.com/RuiSantosdotme/arduino-esp32-CameraWebServer>
