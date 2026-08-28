# Fish YOLO V15（最终保留版）

本目录只保留最终 V15 数据真源、可复查训练痕迹、核心评估和必要工具；V1–V14、审核工作区、逐轮权重、融合候选、缓存与临时预览已清理。

## 最终模型

- 模型：`runs/v15-reviewed-large-v7-yolo11n-640/weights/best.pt`
- 运行时副本：`../../models/best.pt`（由 `VISION/runtime/config.py` 加载）
- SHA256：`1031453E3E40F0CBA28810117A7CFCB1D4BBBBBDCA1596F1926ED30D2BA8EC19`
- 类别：`0 red_fish`、`1 blue_fish`
- 输入：`imgsz=640`
- 选型：V15 第 0 轮，按蓝鱼紧框优先门禁选择；不是训练器按旧宽框验证集选出的默认 checkpoint。

## 最终数据

- 数据集：`dataset_v15_reviewed_large/`
- train / val / close-test / tight-test：498 / 19 / 4 / 12
- train 实例：红鱼 350、蓝鱼 280
- 498 张均经过人工审核，其中 103 张发生人工修改
- 质量门禁：0 空标签、0 非法框、0 split 路径重叠、0 跨 split 精确重复
- 训练与保护集最小时间间隔：5016 ms

## 核心效果（V7 → V15）

- 人工紧框蓝鱼 mAP50-95：0.146 → 0.378
- 人工紧框蓝鱼召回：0.417 → 0.870
- 蓝框平均 IoU：0.529 → 0.660
- 蓝框平均面积比：2.094 → 0.990
- 近距离双鱼蓝鱼 mAP50：0.995 → 0.995
- 62 张确认蓝鱼在 `conf=0.05` 下：62/62 → 62/62 检出

旧常规验证集保留旧宽蓝框，V15 的旧 mAP50-95 会因标注尺度冲突明显降低；详细解释和数值见 `runs/v15-reviewed-large-v7-yolo11n-640/selection_report.json` 与 `manifest.yaml`。

## 最终视频识别

`VISION/data/` 下的媒体文件仅作为本地复核输入或输出，不纳入版本控制：

- `VISION/data/results/355164e09d66d38ad5410b0ccd4a6b8c_v15_best.mp4`
- `VISION/data/results/355164e09d66d38ad5410b0ccd4a6b8c_v15_best.json`

识别规则：同类候选去重后只保留最高置信框；红蓝 ROI 重合时两个框都保留。

## 保留工具

- `render_yolo_video.py`：最终模型视频识别与可视化
- `filter_yolo_predictions.py`：同类去重、每类最高置信候选
- `extract_frames.py`：视频抽帧
- `analyze_source_videos.py`：视频光照、反光、清晰度分析
- `finalize_temporal_review_batch.py` / `validate_temporal_review_package.py`：审核固化与门禁
- `build_v15_reviewed_large_dataset.py`：最终数据版本构建
- `validate_yolo_dataset.py`：YOLO 数据质量校验
- `evaluate_yolo_checkpoints.py` / `assess_yolo_box_bias.py`：模型与框面积评估

最终数据校验记录：`runs/v15-reviewed-large-v7-yolo11n-640/eval/dataset-validation.json`。

仅保留 PyTorch `.pt`，未生成 ONNX、量化或其他格式。
