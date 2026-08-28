# codeFish RoboFish Partner

本仓库包含原始 `CameraTest.ino.bin`、可复现的静态逆向资料，以及依据这些证据重建的纯 ESP-IDF 5.3.2 完整功能工程。

> “还原”指功能等价重建。原镜像没有 ELF 符号和作者源码，因此不能声称逐行源码恢复或生成二进制一致镜像。

## 目录

```text
codeFish/
├─ CameraTest.ino.bin                 原始 ESP32-S3 应用镜像
├─ reverse_analysis/                  镜像结构、字符串、网页、反汇编和伪代码
├─ PARTNER_USER_GUIDE.md              网页与 Partner 脚本使用说明
├─ VISION/                            视觉程序、模型配置和数据处理工具
├─ tests/                             Python 自动化测试（按功能域归类）
├─ docs/                              架构和交接文档
├─ assets/                            项目级图标等静态资源
├─ .vscode/                           编译、连接鱼 AP 和无线 OTA 工作流
└─ RoboFishPartnerDriverSDK/          纯 ESP-IDF 功能等价重建工程
```

视觉程序的入口是 `VISION/runtime/main.py`，测试位于 `tests/vision/`。训练脚本和
数据集元数据位于 `VISION/training/fish_v15/`；原始视频、抽帧图片、训练运行目录
和压缩归档属于本地产物，已由 `.gitignore` 排除。运行输出统一写入
`output/vision/`，不会混入源码目录。

原镜像 SHA-256：

```text
bc55582a37e8cc3abce227b09bf2bc9f66d6d93fda4782f00bc25daecdb79009
```

## 当前重建范围

- XIAO ESP32-S3 Sense 摄像头、抓拍、BMP、MJPEG；
- 原 `/gpio` 驾驶页与 `/partner` 脚本页；
- BIONIC、PROP、HYBRID，前后左右、停止、俯仰、水泵和 Demo；
- Partner JSON/NVS/非阻塞脚本引擎；
- NVS 驱动方向配置与隐藏 `tail_reverse` 协议；
- AP/可选 STA、captive portal、失联上浮保护；
- GPIO7 八像素 RGB 状态灯；
- 原网页兼容 OTA 与带 Basic Auth 的 VS Code OTA；
- 8 MB 双 OTA 分区和 rollback。

具体硬件、任务、路由和验证边界见 [工程说明](RoboFishPartnerDriverSDK/README.md) 与 [逆向报告](reverse_analysis/README.md)。

## 构建

本机工作流固定使用：

```text
ESP-IDF  D:\ESP32\ESP-IDF-v5.3.2
Tools    D:\ESP32\.espressif
Python   D:\ESP32\.espressif\python_env\idf5.3_py3.13_env\Scripts\python.exe
CMake    D:\CMAKE\bin\cmake.exe
Ninja    D:\Ninja\ninja.exe
```

在 VS Code 中打开本目录，运行“RoboFish: 生成 ESP-IDF Web OTA 固件”；或在已导出的 IDF 环境中：

```powershell
cd RoboFishPartnerDriverSDK
idf.py -B build\idf build
```

时间命名的 OTA 应用镜像输出到：

```text
RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-yyyyMMdd-HHmmss.bin
```

## 使用与 OTA

机器鱼创建 AP `RoboFish-ND1`，电脑作为 STA 连接后访问：

- `http://192.168.4.1/gpio`
- `http://192.168.4.1/partner`
- `http://192.168.4.1/update`

VS Code 的连接和上传任务会隐藏输入 AP/OTA 密码、校验 `/get_ip` 返回的 `4.0.0-partner` 与 `192.168.4.1`、要求输入 `UPLOAD`，并显示 HTTP 反馈。无线烧录只上传时间命名的应用 `.bin`。

## 安全与验证

当前已完成 ESP32-S3 目标编译和真实 `esp32-camera` 链接验证，尚未替用户连接或烧录硬件。涉及 ESC、螺旋桨、水泵和舵机的首次测试必须在安全无负载条件下进行，并逐项确认方向、限位、失联保护和 OTA 后回滚行为。
