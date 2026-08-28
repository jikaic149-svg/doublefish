# YOLO PT 数据与训练

仅在处理素材、标注、数据集、Ultralytics 训练/验证或 `.pt` 推理时读取本文件。

## 目标边界

- 默认交付 `best.pt` 和 `last.pt`，不执行模型格式转换。
- 优先使用现有 `.pt` 初始权重；需要下载权重或安装包时先说明外部影响。
- 不为未请求的导出格式安装 ONNX、TensorRT、OpenVINO 或其他后端。

## 已验证的本机环境

使用前先确认路径仍存在：

```text
YOLO      D:\python\venvs\yolo\ultralytics\8.4.118\Scripts\python.exe
YOLO CLI  D:\python\venvs\yolo\ultralytics\8.4.118\Scripts\yolo.exe
标注      D:\python\venvs\labeling\x-anylabeling\4.0.3\Scripts\xanylabeling.exe
OpenCV    D:\python\venvs\opencv\5.0\Scripts\python.exe
```

已知基线为 Python 3.13、Ultralytics 8.4.118、PyTorch CUDA 12.8、OpenCV 5.0 和 X-AnyLabeling 4.0.3。优先使用 YOLO 环境完成训练和常规数据脚本；OpenCV 独立环境只在需要轻量隔离时使用。

## 项目布局

```text
projects/<project>/
├─ README.md
├─ sources/                         原始素材，只读
│  ├─ videos/
│  └─ images/
├─ dataset/                         已审核的正式 YOLO 数据
│  ├─ dataset.yaml
│  ├─ images/<scene>/...
│  ├─ labels/<scene>/...
│  └─ splits/
│     ├─ train.txt
│     ├─ val.txt
│     └─ test.txt
├─ review/
│  ├─ pending/                      待复查候选
│  └─ rejected/                     模糊、错误或低质量样本
├─ scripts/                         仅属于本项目的脚本
└─ runs/
   └─ <experiment>/
      ├─ manifest.yaml              本次实验目的和数据版本
      ├─ train/                     Ultralytics 原生训练输出
      │  ├─ weights/
      │  │  ├─ best.pt
      │  │  └─ last.pt
      │  ├─ args.yaml
      │  └─ results.csv
      ├─ eval/
      └─ predictions/
```

让 `dataset/images/<scene>/x.jpg` 与 `dataset/labels/<scene>/x.txt` 保持相同相对路径。不要把不同场景扁平复制到同一目录。

## 数据流

```text
sources → review/pending → dataset/images + dataset/labels
        → dataset/splits → runs/<experiment>
```

1. 保留 `sources/` 原文件，不覆盖、不重命名后回写。
2. 从视频按时间或内容变化抽帧；避免保留大量几乎相同的连续帧。
3. 在 `review/pending/` 完成人工或辅助标注。
4. 将人工确认的数据加入正式 `dataset/`。
5. 按视频、场景、时间段或采集批次生成 split 清单，不按帧随机拆分。
6. 训练产物直接写入独立实验目录。

优先让完整视频或完整场景只属于一个 split。如果必须把同一条连续视频按时间切开，在边界两侧留出覆盖完整目标轨迹的隔离窗，避免近重复帧跨集合。

### 视频抽帧

- 用来源视频名、帧号或时间戳生成全局唯一文件名，并保存来源映射。
- 先按时间间隔抽取候选，再剔除近重复、严重模糊、曝光异常和无法判读的帧。
- 把同一连续片段视为一个 split group；不要让相邻帧跨越 train/val/test。
- 普通 MP4 优先使用已验证的 OpenCV 环境。只有 OpenCV 无法正确解码、需要转码或处理特殊编码时才引入 FFmpeg。
- 对小目标优先改善清晰度、场景覆盖和标注准确性，再尝试提高训练输入尺寸。

## 标注

- 把 `dataset.yaml` 中的 `names` 作为类别顺序的唯一真源。
- 如果标注工具需要其他类别文件，从 `dataset.yaml` 生成，不手工维护第二份顺序。
- X-AnyLabeling 的原生标注或模型建议先留在 `review/pending/`；显式转换为 YOLO `.txt` 并验证后再加入正式数据。
- 为相邻目标分别绘制紧致边界框；无法可靠识别的严重模糊帧放入 `review/rejected/`。
- 允许有意保留的负样本使用空标签文件，但必须在数据统计中单独计数。
- 自动标注不得默认覆盖可信人工标签；采用“生成候选 → 预览 → 明确应用”的流程。

辅助标注顺序：

```text
人工种子集 → 初始 YOLO → 批量预标注 → 人工复查 → 扩充正式数据 → 重新训练
```

## 质量门禁

在训练前检查：

- 图片能否解码，图片与标签是否正确配对。
- 类别 ID 是否位于 `names` 范围内。
- YOLO 坐标是否有限、归一化且宽高为正。
- 边界框是否越界、异常细小或明显偏离目标。
- 是否存在重复图片、近重复连续帧或不同 split 间的数据泄漏。
- 每类图片数、实例数、框尺寸和场景分布是否严重失衡。
- `review/`、预览图、缓存和合成中间产物是否误入正式数据。

模型-标签一致性只能用于候选样本筛查。不要使用固定的“3%”阈值代替真实评估，也不要让生成标签的同一模型成为唯一审核者。

## dataset.yaml

优先使用清单划分，避免复制六套 train/val/test 文件：

```yaml
train: splits/train.txt
val: splits/val.txt
test: splits/test.txt

names:
  0: class_a
  1: class_b
```

Ultralytics 按清单文件所在目录解析以 `./` 开头的条目。由于清单位于 `dataset/splits/`，使用以下可移植写法：

```text
./../images/scene_01/frame_000001.jpg
./../images/scene_02/frame_000041.jpg
```

## 训练与实验

在训练前记录模型、初始权重、`imgsz`、batch、epoch、seed、增强策略、数据版本和设备。使用有意义且不覆盖旧结果的实验名，例如：

```text
yolo11n-640-baseline
yolo11s-960-small-objects-v2
```

训练前创建 `runs/<experiment>/manifest.yaml`，记录实验目的、数据版本/哈希、split 版本和关键假设。Ultralytics 自身的参数与指标保留在 `runs/<experiment>/train/`。

典型 PowerShell 命令：

```powershell
$VisionYolo = 'D:\python\venvs\yolo\ultralytics\8.4.118\Scripts\yolo.exe'
& $VisionYolo detect train `
  model=yolo11n.pt `
  data=projects\<project>\dataset\dataset.yaml `
  imgsz=640 `
  project=projects\<project>\runs\<experiment> `
  name=train
```

根据显存和小目标需求调整模型、batch 和 `imgsz`，不要把较大输入尺寸当作必然更好。若原始视频来自同一连续场景，先修正数据划分，再调模型参数。

## 验证与交付

至少检查：

- 训练正常结束且 `best.pt`、`last.pt` 存在。
- `best.pt` 能被当前 Ultralytics 环境重新加载。
- Precision、Recall、mAP50、mAP50-95 和逐类别混淆情况。
- 独立验证/测试集以及未参与训练的真实视频预览。
- 小目标、遮挡、密集目标、背景干扰和负样本表现。
- 实际 `.pt` 推理速度、显存占用和输入预处理一致性。

交付时给出最佳权重路径、训练参数、数据版本、核心指标、代表性预测图以及已知失败场景。
