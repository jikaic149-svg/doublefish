# MaixPy 真机开发闭环

仅在用户明确要求 MaixCAM、MaixCAM Pro、MaixCAM2、MaixPy 或 MaixCDK 真机工作时读取本文件。此分支不负责训练或转换 `.pt`。

## 范围与工具

- 先识别实际设备、固件/API 版本和运行目标，不默认使用 MaixCAM2。
- 优先使用已安装 `maixpy` skill 自带的 helper 完成环境检查、发现、配置、开发模式、运行和日志收集。
- 调用 helper 前完整读取已安装 `maixpy/SKILL.md`，并按任务读取它当前版本的设备工作流或应用代码规则；不要复制可能过时的命令。
- 从可用 skill 目录解析 helper，不把安装路径硬编码进用户项目；当前已知安装名为 `maixpy`。
- helper 不存在或 API 不确定时，查阅本地文件或官方 MaixPy/MaixCDK 文档。不要编造 API。
- `doctor` 只证明本地主机依赖可用；必须通过 `device check` 和一次真实运行才算真机验证。

## 首次连接

在当前项目目录运行 helper，使状态保存在项目本地 `.maixpy/`：

```text
doctor → device get → 必要时 device scan → 用户确认设备
       → device set → device check
```

即使只发现一台设备，也先让用户确认。可以提示用户在设备的 `设置 -> 设备信息` 查看名称或 IP。

只保存非敏感字段：host、user、name 和 device class。

## 凭据

只支持两条密码路径：

1. 当前项目的 `.maixpy/device_credentials.local.json`。
2. 让用户在自己的终端 SSH 提示中输入密码。

禁止把密码放入：

- 聊天消息。
- 命令行参数。
- `.maixpy/config.json`。
- 生成代码、日志、总结或最终回复。

如果 helper 支持环境变量传递凭据，只使用其既定安全机制，不打印包含秘密的环境变量。

## 应用代码规则

- 为长时间运行的应用提供显式退出路径。MaixPy 优先使用：

```python
from maix import app

while not app.need_exit():
    ...
```

- 不生成无法退出的 `while True`。如果设备按键被业务占用，增加屏幕退出按钮或其他明确退出方式。
- 使用 `display.Display()` 和 `disp.show(img)` 显示图像。
- 禁止直接写入、打开、映射或传递 `/dev/fb`、`/dev/fb0`、其他 `/dev/fb*`。
- 只在调试迭代保存当前帧或标注帧；用显式环境开关控制，最终版本默认关闭。
- 不在最终帧循环中逐帧打印大量检测结果。

## 运行闭环

使用 helper 的标准流程：

```text
检查设备连接
→ 每次运行前进入并验证开发模式
→ 停止并复查 /maixapp/apps/ 下的冲突应用
→ 上传当前代码
→ 在设备执行
→ 拉取 stdout、stderr、设备日志和调试图片
→ 根据证据修改
→ 重新运行
```

进入开发模式应停止 launcher daemon、停止其他应用，并通过短小的 `display.Display()` 刷新程序验证相机/显示资源可用。任何一步失败时都停止后续相机或显示代码执行。

## 调试图片

仅在输出无法通过日志判断时临时启用调试图片。把图片写入 helper 指定的单次运行 artifact 目录，并打印 helper 可识别的标记。最终交付前移除调用或默认禁用。

每次运行后检查项目内：

```text
.maixpy/runs/<run_id>/summary.json
.maixpy/runs/<run_id>/development-mode.log
.maixpy/runs/<run_id>/stdout.log
.maixpy/runs/<run_id>/stderr.log
.maixpy/runs/<run_id>/artifacts/
```

## 失败处理

- SSH 失败：运行 `device check`，报告具体连接错误但隐藏秘密。
- 冲突应用无法停止：不要继续运行相机/显示代码。
- 开发模式显示刷新失败：检查 stderr 和设备 launcher 日志。
- 应用挂起：先检查退出路径、阻塞 I/O、资源冲突和循环节拍。
- 视觉输出不清楚：临时启用调试图片，验证后关闭。

## 交付

说明设备型号、固件/API 版本、运行文件、真机执行命令、对应 run ID、日志结论和仍未验证的硬件功能。不要把本地主机 `doctor` 通过描述成设备端验证通过。
