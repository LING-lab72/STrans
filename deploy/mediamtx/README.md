# 手机摄像头云端转发（MediaMTX）

本目录提供一套适合 Ubuntu 云服务器的最小部署：

- 手机通过 HTTPS/WHIP、SRT 或 RTMP 推流；
- 前端通过 HTTPS/WHEP 低延迟播放；
- STrans 后端通过 RTSP 拉取同一路流做 OpenCV/YOLO 分析；
- 发布账号与读取账号分离，仅允许访问指定流路径；
- Caddy 自动申请和续期 TLS 证书；
- 明文凭据只生成在被 Git 忽略的 `generated/credentials.env`。

## 1. 推荐架构

```text
手机摄像头 -- WHIP/SRT --> Ubuntu + MediaMTX
                                |-- WHEP --> 浏览器前端（低延迟展示）
                                `-- RTSP --> FastAPI/OpenCV（识别分析）
```

不要让每个浏览器都经 FastAPI 转成 MJPEG。现有 MJPEG 链路可继续用于检测框叠加或兼容演示，但它会重复解码和 JPEG 编码，带宽、CPU 和延迟都更高。

## 2. 云服务器准备

前置条件：

1. 准备域名，例如 `stream.example.com`，A/AAAA 记录指向云服务器。
2. 云厂商安全组放行 `80/tcp`、`443/tcp`、`443/udp`、`8189/udp`、`8189/tcp`、`8890/udp`。
3. 如果使用 RTSP/RTMP 手机 App，再按需放行 `8554/tcp` 或 `1935/tcp`。不使用时不要开放。

安装 Docker 和 UFW 规则：

```bash
cd deploy/mediamtx
chmod +x install-ubuntu.sh generate-config.sh
chmod +x encrypt-credentials.sh
./install-ubuntu.sh
```

重新登录 SSH 后生成配置：

```bash
cd deploy/mediamtx
./generate-config.sh stream.example.com
docker compose config
docker compose up -d
docker compose logs -f mediamtx caddy
```

如果域名和 WebRTC 可达地址不同，可指定公网 IP：

```bash
./generate-config.sh stream.example.com 203.0.113.10 mobile-camera
```

查看客户端地址与随机凭据：

```bash
sudo cat generated/credentials.env
```

不要把该文件发送到聊天、提交到 Git 或写进前端源码。

### 加密复制到本地

使用 `age` 公钥加密：本机保管私钥，服务器只保存公钥。生成本机密钥一次即可：

```powershell
age-keygen -o secret/camera-connection.key
```

将命令输出中的 `age1...` 公钥写入服务器的 `/opt/strans-mediamtx/age-recipient.txt`，然后执行：

```bash
cd /opt/strans-mediamtx
./encrypt-credentials.sh
```

把 `generated/camera-connection.age` 复制到本地 `secret/`。只获取 Larix 的 Stream ID：

```powershell
.\scripts\decrypt-camera-connection.ps1 -Field STREAM_ID
```

也可把 `STREAM_ID` 替换为 `SRT_URL`、`RTSP_URL`、`RTMP_URL`、`WHIP_URL` 或 `WHEP_URL`。使用 `HTTP_STREAM_URL`（或 `HLS_URL`）会输出可供 VLC / ffplay 使用的 HLS 地址；该地址含读取凭据，不能分享或写入前端。`ALL` 会输出整份明文，除非必要不应使用。

### 暂无域名时的手机联调

可以先用服务器公网 IP 生成配置，并只启动 MediaMTX：

```bash
./generate-config.sh 203.0.113.10 203.0.113.10 mobile-camera
docker compose up -d mediamtx
```

此时使用 `generated/credentials.env` 中的 `SRT_URL` 或 `RTMP_URL` 从手机推流，浏览器可通过以下地址查看（会要求输入读取账号）：

```text
http://203.0.113.10:8889/mobile-camera/
```

公网 HTTP 页面通常不能获得手机摄像头权限，因此无域名模式适合“原生 App 推流 + 浏览器观看”。要直接从手机浏览器采集摄像头，仍应配置域名并启动 Caddy，以 HTTPS/WHIP 推流。

## 3. 验证鉴权

匿名发布应返回 `401`：

```bash
curl -i -X POST "https://stream.example.com/mobile-camera/whip" \
  -H "Content-Type: application/sdp" \
  --data-binary 'invalid-test-offer'
```

使用发布账号后，错误应从鉴权失败变成 SDP 校验失败，证明账号已被接受：

```bash
set -a
. generated/credentials.env
set +a
curl -i -u "${PUBLISH_USER}:${PUBLISH_PASSWORD}" \
  -X POST "${WHIP_URL}" \
  -H "Content-Type: application/sdp" \
  --data-binary 'invalid-test-offer'
```

读取账号不能发布；发布账号也没有读取权限。MediaMTX 配置中保存的是用户名和密码的 SHA-256 摘要，客户端明文只保留在服务器本地的凭据文件中。

## 4. 手机端方案

### 方案 A：手机浏览器 + WHIP（首选原型）

手机访问：

```text
https://stream.example.com/mobile-camera/publish
```

浏览器会请求摄像头和麦克风权限，并弹出账号密码对话框。使用 `PUBLISH_USER` 和 `PUBLISH_PASSWORD`。优点是不安装 App、延迟低、HTTPS 传输；缺点是浏览器切到后台或锁屏后通常会暂停采集。

### 方案 B：原生推流 App + SRT（首选长期运行）

从 `generated/credentials.env` 读取 `SRT_URL`，在支持自定义 SRT 地址的手机推流 App 中配置。建议视频使用 H.264、无 B 帧、720p、15–25 FPS、1–2.5 Mbps，关键帧间隔 1–2 秒。SRT 对移动网络抖动更稳，也更适合前后台切换。

### 方案 C：RTMP（兼容兜底）

多数推流 App 支持 RTMP，但普通 RTMP 不加密，凭据和内容可能被窃听。只建议在 VPN 内使用；公网应优先 WHIP/HTTPS 或 SRT，确需 RTMP 时再配置 RTMPS。

## 5. 接入当前 STrans 项目

### 后端分析

把 `RTSP_URL` 填入当前页面的“流地址或摄像头编号”，FastAPI 会通过 OpenCV 拉取 MediaMTX 中的流，再通过现有 `/api/video/mjpeg` 输出检测画面。

### 前端低延迟直播

展示原始直播时应使用 `WHEP_URL`，并由项目后端签发短时读取令牌，前端通过 `Authorization: Bearer <token>` 发起 WHEP 请求。不要把 `READ_PASSWORD` 编译进 Vite 环境变量，因为浏览器用户可以读取构建产物。

原型阶段也可直接访问：

```text
https://stream.example.com/mobile-camera
```

并在浏览器对话框中输入读取账号。正式集成时建议切换 MediaMTX 的 JWT/JWKS 鉴权，JWT 仅包含短时、单路径 `read` 权限。

## 6. 运维命令

```bash
docker compose ps
docker compose logs --tail=200 mediamtx
docker compose restart mediamtx
docker compose pull
docker compose up -d
docker compose down
```

轮换凭据会覆盖当前生成配置：

```bash
cp generated/credentials.env "generated/credentials.$(date +%F-%H%M%S).bak"
./generate-config.sh stream.example.com
docker compose up -d --force-recreate mediamtx
```

备份文件仍含旧明文凭据，完成客户端迁移后应安全删除。

## 7. 后续生产化

- 由现有用户系统签发 5–15 分钟短时 JWT，并通过 JWKS 让 MediaMTX 校验；
- JWT 中限制 `publish/read` 动作和单个流路径；
- 对推流创建、停止、失败和鉴权拒绝记录审计日志；
- 监控在线流数、带宽、丢包、WebRTC 会话和服务器磁盘；
- 如企业网或运营商网络阻断 UDP，再增加 Coturn/TURN TCP 中继；
- 云端入站规则和 UFW 必须同时配置，不能只改其中一层。
