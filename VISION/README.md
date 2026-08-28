# RoboFish 视觉代码交接说明

## 边界

视觉工程按 `vision` skill 的职责拆分为实时视觉、训练数据和模型配置三层；
机器鱼 HTTP 协议仍由实时层的设备适配器调用，ESP32 固件本身保持在
`RoboFishPartnerDriverSDK/`，不与视觉算法混编。

```text
VISION/
├─ runtime/              实时采集、检测、跟踪、导航、控制和界面
│  ├─ main.py            唯一入口与生命周期调度
│  ├─ config.py          运行时路径、阈值和物理配置
│  ├─ perception.py      YOLO、鱼尾跟踪、ArUco和坐标转换
│  ├─ navigation.py      速度、航向、路径引导和转圈标定
│  ├─ control.py         视觉控制会话与机器鱼 HTTP 适配
│  ├─ interface.py       相机、平板 TCP、MJPEG 和录像适配
│  └─ ui.py              输入、工具栏、HUD 和遥测渲染
├─ models/               运行时模型与历史候选模型
│  └─ best.pt            当前程序实际加载的 YOLO 模型
├─ configs/              本地标定配置（不入库）
├─ training/fish_v15/    数据集元数据、脚本和评估记录
├─ data/raw/             原始视频（只读、本地产物）
├─ data/results/         结构化识别结果和预览（本地产物）
└─ requirements.txt      Python 依赖
```

实时层遵循 `FrameSource → Detector/Tracker → Fusion → Renderer/Diagnostics`
的数据流；设备控制只接收结构化的视觉决策，不把网络协议反向带入检测和跟踪
算法。嵌入式侧遵循 `BSP/Device → APP/Algorithm → Task` 的既有工程边界，
本次只调整目录和路径，不改变 FreeRTOS 任务、Topic、协议或硬件配置。

## 准备环境

当前验证环境为 Python 3.13、OpenCV 5.0、Ultralytics 8.4.118、
PyTorch 2.11.0+cu128，使用 NVIDIA GPU：

```powershell
python -m pip install -r requirements.txt
```

当前 `models/best.pt` 的输入尺寸为 640，类别顺序为
`0: "red_fish"`、`1: "blue_fish"`。

## 启动程序

从仓库根目录启动实时入口：

```powershell
cd VISION/runtime
python main.py
```

VS Code 的启动配置已经指向同一个入口。默认相机索引为 `1`，如需修改，在命令
行入口处调整 `VisionApplication(camera_index=1)`。

操作顺序：启动程序 → 检查相机和 YOLO → 场地标定 → 鱼尾标定 → 点击鱼头方向
→ 从机器鱼附近绘制轨迹 → 启动循迹。`Enter` 启动，`Space` 停止，`Q` 安全退出。

默认连接：机器鱼 `192.168.4.1:80`、平板 TCP `9998`、电脑端 MJPEG
`http://<电脑IP>:8090/video.mjpg`。相机或目标恢复后不会自动恢复推进，需要
人工重新启动。

## 训练与数据

数据集脚本位于 `training/fish_v15/scripts/`，标签、划分清单和评估报告位于
`training/fish_v15/dataset_v15_reviewed_large/`。原始视频放在 `data/raw/`，
生成视频和 JSON 结果放在 `data/results/`；大文件已由根 `.gitignore` 排除。
训练运行目录中的候选权重不会被实时程序自动加载，运行时只读取
`models/best.pt`。

运行时 YOLO 调用使用相对于 `VISION/runtime/` 的 `../models/best.pt`，入口启动时
会先切换到该目录，因此不依赖个人电脑的绝对路径。

## 后续验证

需要在真实相机、机器鱼和平板上完成整机回归，覆盖丢帧、丢目标、标定失效、路径
失效、到达终点和退出等 STOP 场景；离线测试和模型加载不能替代水下执行器验证。
