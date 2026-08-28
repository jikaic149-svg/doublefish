# 实时检测与视觉跟踪

仅在任务包含图片/视频推理、摄像头检测、ROI 跟踪、多目标关联、视觉结果融合或可视化时读取本文件。本文件只处理视觉输入、视觉状态和视觉输出。

## 职责分层

```text
FrameSource   获取图像并记录采集时间戳
Detector      产生类别、边界框、置信度及可选掩码/关键点
Tracker       维护 ROI、轨迹 ID、位置、速度和生命周期
Predictor     在检测间隔或短时遮挡期间预测视觉位置
Fusion        融合检测、跟踪和预测，拒绝过期或异常结果
Renderer      绘制框、轨迹、标签和调试信息
Diagnostics   记录质量、耗时、状态变化和失败证据
```

保持模块输入输出清晰。检测器回答“当前帧看见了什么”，跟踪器回答“跨帧是否为同一目标”，融合层回答“当前视觉结果是否可信”。

## 视觉状态机

```text
DETECT      全帧检测并产生候选
INIT_TRACK  选择候选并初始化视觉跟踪器
TRACK       ROI 或多目标跟踪为主
VERIFY      低频检测，核对类别、位置和尺寸一致性
RECOVER     跟踪失败，在预测附近扩大视觉搜索区域
LOST        连续失败，标记轨迹无效并等待重新检测
```

为每个状态定义进入条件、退出条件、超时和最大失败帧数。避免把隐式状态判断散落在帧循环中。

## 数据契约

```text
Detection:
  class_id
  bbox
  confidence
  optional_mask_or_keypoints

TrackResult:
  track_id
  class_id
  bbox
  center
  velocity
  confidence
  source
  timestamp_ms
  age_ms
  lost_ms
  valid

VisionFrameResult:
  timestamp_ms
  detections
  tracks
  optional_selected_track_id
  processing_ms
```

让视觉输出保持结构化、可记录、可回放。不要在该层定义非视觉业务命令或外部设备协议。

## 坐标与时间

- 选择一个规范图像坐标系，并明确像素中心、原点和边界框格式。
- 把 letterbox、缩放、裁剪、ROI、旋转和数字变焦结果正确映射回规范坐标系。
- 对掩码和关键点使用与边界框相同的变换链。
- 使用图像采集时间戳，不用处理完成时间替代观测时间。
- 为异步结果设置最大年龄；过期检测不得覆盖较新的轨迹状态。

## 检测与跟踪循环

```text
frame = source.read()
prediction = tracker.predict(frame.timestamp)
roi = build_roi(prediction, previous_size, margin)
track = tracker.update(frame, roi)
detections = detector.detect(frame) at the required cadence
result = fusion.combine(track, detections, prediction)
preview = renderer.draw(frame, result)
```

检测频率、跟踪频率和渲染频率可以不同。优先测量端到端延迟，再决定是否降频检测或缩小 ROI。

## 结果融合

- 综合空间距离、IoU、类别、尺寸变化、时间新鲜度和连续帧证据。
- 拒绝不符合可观测运动范围的中心跳变和面积突变。
- 短时遮挡可以保留预测轨迹，但超过可信时间后必须设置 `valid=false`。
- 重新检测到目标时要求连续证据，避免单帧误检替换现有轨迹。
- 保留 `source=DETECTOR|TRACKER|PREDICTION`，便于回放时解释结果来源。

## 多目标与异步结果

- 使用不会在会话内复用的 `track_id` 维护多目标生命周期。
- 目标交叉或严重重叠时标记歧义，暂停容易被污染的外观特征更新。
- 关联不要只依赖 IoU；结合运动预测、中心距离、尺寸变化、时间新鲜度，必要时加入外观特征。
- 采集队列积压时优先保留最新帧，避免延迟持续增长。
- 异步检测携带原始采集时间戳；迟到结果应前推到当前时刻或直接丢弃。
- 对外观相同目标的完全遮挡，不承诺绝对身份连续；需要严格身份时使用可区分标记或额外视觉线索。

## 日志与性能

默认记录视觉事件而非逐帧刷屏：

```text
track initialized
TRACK -> RECOVER
RECOVER -> LOST
source: TRACKER -> DETECTOR
jump rejected
track reacquired
late detection dropped
```

分别统计采集、预处理、检测、跟踪、融合和渲染耗时。报告 FPS、端到端延迟、P95 延迟、抖动、丢帧率和过期结果比例。

## 验证

至少覆盖：

- 静止、移动、远近变化和小目标。
- 多个同类目标交叉、靠近和分离。
- 短时遮挡、离开画面和重新进入。
- 相机移动、数字变焦、分辨率变化和运动模糊。
- 错误类别、高置信度干扰物和空场景。
- 处理速度不足、异步结果迟到和帧丢失。

根据任务报告检测 Precision/Recall/mAP、跟踪 HOTA/IDF1/ID Switch、轨迹保持率、重捕获时间、FPS 和端到端延迟。保存带时间戳的预测视频或结构化结果，确保问题可回放。
