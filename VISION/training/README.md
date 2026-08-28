# 视觉数据与训练产物

本目录把视觉数据处理工具和本地实验产物集中在一起，避免它们散落在
`VISION/` 源码目录中。

```text
VISION/training/
└─ fish_v15/
   ├─ scripts/                 可复用的数据集与评估脚本（源码）
   ├─ dataset_v15_reviewed_large/
   │  ├─ *.csv、*.json、*.yaml  数据集清单、报告和配置（小型元数据）
   │  └─ images/               抽帧图片（本地产物，忽略）
   └─ runs/                    训练结果和权重（本地产物，忽略）
```

最终运行时使用的模型是 `VISION/models/best.pt`。训练运行目录下的检查点仅用于
实验对比，不要让主程序直接依赖它们。需要复现数据处理时，从
`fish_v15/scripts/` 运行脚本，并将生成结果留在已忽略的 `images/` 或 `runs/` 目录。
