# 道路逻辑建模工具集成说明

本目录从仓库内 `tools/road_logic_modeler` 引入主建模页面的最小运行集，并随 Vite 前端构建发布。

包含文件：

- `index.html`
- `styles.css`
- `src/geometry.js`
- `src/model.js`
- `src/renderer.js`
- `src/app.js`

主页面支持道路、节点组、车道、建筑物和摄像头标定，以及 JSON 导入导出。RTSP 单帧抓取属于可选辅助能力，可运行项目内的 `tools/road_logic_modeler/start_server.ps1`，并要求本机 FFmpeg 可用；离线建模流程不依赖该服务。

同步外部源文件时，必须执行 `frontend/test/road-modeler.test.js` 和 `frontend/test/road-modeler-model.test.js`，确保静态资源完整且导出结构保持 `road_logic_modeler.v1`。
