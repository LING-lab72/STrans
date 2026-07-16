# Road Logic Modeler

本目录保留道路建模算法、分析脚本与可复现测试；发布用静态页面位于
`frontend/public/road_logic_modeler/`。

运行工具回归测试：

```powershell
python -m pytest tools\road_logic_modeler\tests -q
$tests = Get-ChildItem tools\road_logic_modeler\tests\*.mjs | Select-Object -ExpandProperty FullName
node --test $tests
```

## 本机 RTSP 桥接

主建模页面已经随前端发布，普通离线建模不需要运行本目录脚本。

只有使用“截取 RTSP 帧”时才需要启动本机桥接：

```powershell
powershell -ExecutionPolicy Bypass -File tools\road_logic_modeler\start_server.ps1
```

默认只监听 `127.0.0.1:8765`，并从 `frontend/public/road_logic_modeler/` 提供静态页面。RTSP 抓帧需要 `ffmpeg` 已加入 `PATH`。可以通过 `STRANS_PYTHON` 环境变量指定 Python 可执行文件。

安全边界：不要将监听地址改为 `0.0.0.0`。该桥接仅供本机工具使用，没有用户认证。
