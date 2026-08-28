# 运行时模型

- `best.pt`：当前 `VISION/runtime` 程序默认加载的 YOLO 权重。
- `candidates/`：历史或候选权重，仅供离线比较，不会被运行时自动加载。

模型与类别顺序必须和 `VISION/runtime/config.py` 中的运行配置保持一致。
