# 视觉程序结构

```text
VISION/
├─ runtime/
│  ├─ main.py          唯一调度、生命周期和功能组装
│  ├─ config.py        部署配置与资源路径
│  ├─ perception.py    YOLO、鱼尾跟踪、场地标定和单帧感知
│  ├─ navigation.py    速度估计、路径引导和转圈标定
│  ├─ control.py       控制状态机与机器鱼HTTP通信
│  ├─ interface.py     相机、平板、MJPEG和录像适配器
│  └─ ui.py            输入、状态、工具栏、渲染和遥测
├─ models/
│  └─ best.pt          运行时 YOLO 模型
├─ configs/            本地标定配置
├─ training/fish_v15/  数据集元数据和训练/评估脚本
├─ data/               原始视频与结构化结果
└─ requirements.txt
```

只有 `runtime/main.py` 组装功能对象。其他模块不创建跨功能服务，也不反向导入
`main.py`。感知管线需要的速度估计器和延迟补偿函数由 `main.py` 注入。

运行数据流：

```text
runtime/interface.CameraStream
        ↓ frame snapshot
runtime/perception.VisionPipeline
        ↓ metric observation
runtime/navigation.PathGuidance + runtime/control.VisionControlSession
        ↓ data-only decision
runtime/main.VisionApplication
        ├─ runtime/control.RoboFishComm
        ├─ runtime/interface.TabletTCPServer / MJPEGServer / AsyncVideoRecorder
        └─ runtime/ui.VisionPresentation
```

安全约束：相机超过0.35秒没有新帧，或发生丢目标、标定失效、路径失效、
到达、清路径、退出和异常时，调度层统一STOP。每次启动创建新控制会话，
STOP使旧PID命令失效；STOP与PID请求串行，避免旧请求晚到覆盖停止状态。

录像和截图写入项目根目录 `output/vision/`；Ultralytics和Matplotlib缓存写入
Windows的 `%LOCALAPPDATA%/RoboFishVision/`，不会污染 `VISION` 源码目录。
