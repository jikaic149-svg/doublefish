# process

## 2026-08-28 视觉控制边界改为完整 Frenet S/F

- 修改原因：用户要求路径跟踪使用完整的 Frenet `s/f` 状态，避免把二维池面坐标或旧的 `x_error` 名称继续当作控制语义；同时补齐航向变化和横向误差变化对控制诊断的表达。
- 最终决策：`VISION/runtime/navigation.py` 的结构化状态新增 `s_dot`、`f_dot` 和由视觉航向估计得到的 `yaw_rate`；引导命令新增 `s`、`f`、航向误差、实测/期望偏航率和归一化转向需求。`VISION/runtime/control.py` 改为优先消费 Frenet S/F 字段，旧 `cross_m/along_m/dist_m` 只保留为兼容别名；到 MCU 的 `x_error/y_error` 转换集中在 HTTP 适配边界，固件协议和执行器行为未修改。
- 涉及文件：`VISION/runtime/navigation.py`、`VISION/runtime/control.py`、`tests/vision/test_path_guidance.py`、`tests/vision/test_vision_control.py`。
- 验证方式和结果：37 项视觉路径/控制单元测试通过；`VISION/runtime` 编译检查通过；`git diff --check` 通过。
- 已知限制：`yaw_rate` 是基于视觉位移航向的估计，不是 IMU 实测；当前 MCU 仍接收旧的 `x_error/y_error` 协议，因此这次完成的是视觉端完整 S/F 控制边界，不是固件原生 Frenet 执行器分配；两条动力不同的机器鱼仍需各自的动力学标定。
- 待确认事项：入水验证 `s/f` 符号、`f_dot` 阻尼方向、期望偏航率与实际转弯响应；确认无误后再决定是否新增按硬件鱼 ID 的动力学配置和原生协议字段。

## 2026-08-28 Frenet 状态与等效转弯指令边界
- 修改原因：区分路径 Frenet 状态、池面 XY 几何和机器鱼的实际动力输入，避免把航向角误认为可以直接下发的执行器命令。
- 最终决策：在 `VISION/runtime/navigation.py` 增加结构化 `FrenetState` 与 `GuidanceCommand`。状态明确保存 `s`、有符号横向误差 `f`、路径/鱼体/期望航向、航向误差、曲率、速度和剩余距离；命令明确保存唯一归一化 `turn_demand`，并把现有 `x_error` 标记为兼容 MCU X-P 控制器的等效协议量。保留原 LOS、曲率前馈、航向反馈、`x_error = turn_demand / 3`、HTTP `/vision_pid` 和 ESP32 执行器混控，不修改固件、协议或控制数值。
- 验证方式和结果：新增结构化状态与命令回归测试；路径引导和视觉控制相关 34 项 unittest 通过，Python runtime 编译检查和 `git diff --check` 通过。完整视觉测试仍受当前环境缺少 `cv2` 影响，6 个依赖 OpenCV 的测试模块未能导入。
- 已知限制：当前仍是基于 Frenet 状态的几何路径跟踪，不是带鱼体动力学模型的 MPC/动态最优控制；`turn_demand` 到尾部偏置、螺旋桨舵角和推进功率的映射仍由固件经验参数完成，实机水动力等效性需要入水数据确认。

## 2026-08-28 YOLO 运行时模型改为项目相对路径

- 修改原因：视觉重构后模型路径由 Python 文件位置拼成绝对路径，换电脑或复制仓库时不便复用。
- 最终决策：`VISION/runtime/config.py` 将运行时模型设为相对于 `VISION/runtime/` 的 `../models/best.pt`；`VisionApplication.run` 继续在启动前切换到该工作目录，YOLO 调用实际加载 `VISION/models/best.pt`。
- 涉及文件：`VISION/runtime/config.py`、`VISION/runtime/perception.py`、`VISION/README.md`、`README.md`、`tests/vision/test_runtime_config.py`。
- 验证方式和结果：检查相对路径归一化后指向仓库内 `VISION/models/best.pt`，运行配置单元测试，并在 Ultralytics 环境加载模型确认类别与权重可读；未修改弯道坐标、ESP32 固件、HTTP 协议或控制逻辑。
- 已知限制：模型路径本身已由 `perception.py` 按模块位置解析，直接从其他目录实例化 `FishDetector` 也可加载；正式入口仍会切换到 `VISION/runtime/`，便于其他相对资源保持一致。
- 待确认事项：在目标电脑上从仓库根目录和 VS Code 各启动一次，确认工作目录打印为 `VISION/runtime` 且不触发模型文件不存在。

## 2026-08-15 曲率转向第二轮参数整定

- 修改原因：第一轮新日志解析到190个样本，触顶仅32次且 `曲<=0.10` 时触顶为0，证明低曲率0.45倍和普通恢复0.45已经有效，不应继续削弱。问题集中在真实弯道：曲率0.30～0.36且航向误差仍在±10°时，提前转向的平均 `|x|` 只有0.031 m，鱼速仍约0.27～0.34 m/s；随后航向误差扩大到约90°才连续触顶，最大离轨达到0.37 m。固件确认 `Kp=300` 下旧 `±0.24 m` 只对应72%螺旋桨舵和鱼尾偏置权限。
- 最终决策：保持低/高曲率增益0.45～1.90、普通恢复0.45和MCU PID不变。曲率前馈由0.35提高到0.50，让弯道在航向误差建立前更早偏转；视觉X安全上限由 `±0.24 m` 提到 `±0.30 m`，急弯最多对应90%转向，仍不允许达到100%。控制严重度继续按0.24 m几何前视距离归一化，避免提高安全上限反而减小固件弯道减速。路径曲率的动力减速增益设为1.50，例如原始 `曲=0.30/0.40` 下发 `动` 至少为0.45/0.60，使螺旋桨上限约从76%/68%提前降至64%/52%；终端增加 `动=` 便于实测。
- 验证方式和结果：Python语法检查、`git diff --check` 和58项视觉单元测试通过；新增覆盖 `±0.30 m` 安全权限及1.50倍曲率减速。随后用 ESP-IDF 5.3.2 对 ESP32-S3 完整编译、链接和分区检查通过，应用镜像938528字节，OTA分区剩余72%；生成 `RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260815-152302.bin`，SHA-256为 `683001944eb3f041803cd394460c3624ed085cc88bc2d7650f249ef61516d8cf`。固件侧仅更新参数注释，生成镜像与此前同尺寸同哈希；本轮控制行为修改仍全部位于电脑视觉侧，无需烧录。
- 已知限制：0.30 m仍是安全上限，若下一次大弯长期触顶且离轨继续增大，说明剩余问题是物理转向力或曲率/航向观测延迟，不能继续无限提高视觉指令。提高曲率减速会同时把鱼尾摆幅从74%向60%降低，但鱼尾转向偏置仍随转向强度提高；真实净偏航力必须入水验证。
- 待确认事项：下一次重点比较 `曲=0.30～0.40` 时 `动` 是否达到约0.45～0.60、速度是否在航向误差超过40°之前下降，以及ACK的ESC是否能从旧71°/109°进一步接近67°/113°。若提前减速和舵量都生效但离轨仍不收敛，停止调比例，转查橙色鱼尾航向延迟。

## 2026-08-15 曲率转向第一轮参数整定

- 修改原因：基线实机共解析到224个控制样本，其中101个达到 `±0.24 m` 安全上限，37个甚至发生在 `曲<=0.10`；实际最大曲率只有0.61，高曲率36个样本的平均最终增益仅0.994。原因是原0.55～1.35映射在实际曲率范围内提升不足，而普通航向恢复在90°误差时总会回到1.00，低曲率仍被大角度误差主导。
- 最终决策：只调整曲率比例参数，不改协议、MCU PID、制动状态机和跟踪框架。曲率增益范围由0.55～1.35改为0.45～1.90，使实际 `曲=0.60` 已达到约1.32倍；普通航向恢复只应用0.45系数，低曲率90°误差的最终增益约0.6975。目标位于正后方120°锥区时仍至少保留1.00倍掉头力度，避免为了抑制画龙导致无法掉头；安全上限继续为 `±0.24 m`。
- 验证方式和结果：Python语法检查、`git diff --check` 和57项视觉单元测试通过，新增低曲率90°误差不触顶、实测0.60曲率增益至少1.30的覆盖。按最新224个日志样本的角度、离轨和曲率离线代入新闭环项，总饱和样本估算由101降至75，低曲率饱和由37降至13；高曲率样本平均增益由0.994升至约1.166、最大约1.334。
- 已知限制：离线回放没有完整记录曲率方向和前馈项，饱和数量是闭环主项估算，不等于下一次真实水动力结果；橙色鱼尾仍会污染运动航向。一次同时改变了低/高曲率两个端点和普通恢复系数，下一轮必须用相同类型轨迹比较，不能继续叠加更多参数。
- 待确认事项：重启视觉程序即可实测，无需烧录。重点观察 `曲<=0.10` 时是否减少长期 `x=±0.240`，以及 `曲=0.4～0.6` 时 `增` 是否升到约1.03～1.32并更早完成转弯；若大弯足够但小弯仍摆，再只降低恢复系数，不改变高曲率端点。

## 2026-08-15 曲率连续转向比例基线

- 修改原因：上一轮实机中 X 命令在急弯长时间卡在固定 `±0.18 m`，离轨仍持续增大；小曲率段又以相近比例左右纠偏，表现为急弯半径不足、缓弯画龙。固定限幅同时丢失了“还需要增加多少转向”的信息。
- 最终决策：前方 `0.32 m` 的平滑路径预览角作为平均曲率严重度，闭环曲率增益采用 `0.55 + 0.80 × path_curve_severity`，即从 0.55 倍连续提高到 1.35 倍；曲率前馈由 0.25 提高到 0.35。小曲率且小航向误差时降低纠偏，严重航向偏差时连续恢复基础掉头能力。X 的 `±0.24 m` 仅作为异常安全上限，不再作为常规固定舵量。终端把原来混合含义的“弯”改为纯路径 `曲` 与最终 `增`，固件收到的动力严重度和通信协议保持不变。
- 验证方式和结果：Python 语法检查、`git diff --check` 和 55 项视觉单元测试通过；新增覆盖同一 30° 航向误差下大曲率输出大于直线、小曲率 5° 误差低增益以及安全上限。随后实机日志中 `曲=0.00～0.61`、`增=0.58～1.04` 连续对应，终点反转制动把速度从约 0.20 m/s 降到 0.08 m/s，并在 0.20 m 停止圈内成功 STOP，证明框架与制动链路生效。
- 已知限制：实机大部分强转仍由较大的航向误差触发，低曲率时也多次达到 `±0.24 m`；曲率样本最高只有 0.61，尚未覆盖理论 1.35 倍上限。第二次路径起步沿用了上次运动航向，首个误差约 170°，初始掉头造成较大离轨，不能把该段直接用于小曲率稳态参数评价。
- 待确认事项：以此版本作为 Git 基线后只调参数。下一轮优先降低低曲率强转的恢复程度，并提高实际 `曲≈0.4～0.6` 区间的曲率增益；保持协议、PID结构、制动状态机和视觉跟踪框架不变。

## 2026-08-15 正后方掉头连续性与终点死区收紧

- 修改原因：新固件实测证明弯道前馈减速已生效，但第二条反向路径起步航向误差在 `+179°/-179°` 之间跨界，X 四次翻转；终点从0.50 m开始制动后停在约0.24 m且速度降到0，但原0.22 m停止圈始终不成立，连续116帧重复发送制动。用户要求停止死区再缩小一点。
- 最终决策：目标位于鱼身后方且角误差大于等于120°时，沿用首次确定的掉头侧；后续 `atan2` 跨过 `+180°/-180°` 只保持角度幅值，不改变X符号，离开后方120°锥区后恢复普通闭环。终点制动起点由0.50 m收回0.40 m，给鱼多保留0.10 m转向修正距离；停止圈由0.22 m缩到0.20 m。否决把停止圈放宽到0.25 m的临时方向。
- 涉及文件：`VISION/path_guidance.py`、`VISION/yolo(PID).py`、`VISION/tests/test_path_guidance.py`、`VISION/VISION_OPTIMIZATION_PLAN.md`、`process.md`。
- 验证方式和结果：新日志中两段非制动满弯平均速度约0.175/0.130 m/s，轻弯约0.264/0.250 m/s，证明20%螺旋桨/60%尾舵的减速明显；ESC满转稳定约76°/104°，不再达到64°/115°。视觉Python语法检查通过，53项单元测试全部通过，新增覆盖后方目标跨角度边界保持同一X符号、默认0.40 m制动和0.20 m到达圈。
- 已知限制：本次仅修改电脑视觉侧，尚未用真实鱼验证0.40/0.20 m；如果制动后横向误差仍增大，说明“制动阶段回中且关闭尾舵”本身限制终点精度，继续缩小停止圈会再次导致制动保持卡住。
- 待确认事项：无需重烧固件，重启视觉程序后先测试一条需要180°掉头的短路径，确认X不再换号；再测试终点是否能在0.20 m内触发STOP。若仍停在圈外，下一步应让终点制动保留小幅转向，而不是继续调整死区。

## 2026-08-15 实机否决弱弯道限速并移除 X 微分

- 修改原因：用户确认已烧录上一版并实测转弯减速不明显、超调较大。日志中满弯 `curve>=0.9` 时平均速度约 `0.188 m/s`，轻弯 `curve<=0.25` 时约 `0.232 m/s`，只下降约 19%；两次运行分别出现 10/3 次明显 X 左右换向和 6/9 次超过 60° 的相邻航向跳变。上一版满弯螺旋桨仍为 55%，同时把尾舵动力从 74%提高到92%，总推进没有明显降下来；X 的 `Kd=35` 又放大摆动鱼尾和通信/相机延迟造成的误差突变。
- 最终决策：不建立普通弯道速度闭环，也不对视觉速度做微分；下发给固件的标量速度只用于终点反转制动的结束判断，`vx/vy` 仍用于相机延迟位置补偿。弯道减速保持纯曲率前馈，满弯螺旋桨由55%降到20%，鱼尾不再升到92%而由直线74%降到60%。X 控制改为纯 P：`Kp=300, Ki=0, Kd=0`，视觉 `±0.18 m` 满量程对应约 `±54%` 转向。运动航向窗口由0.40 s增至0.60 s，最短建立时间由0.12 s增至0.25 s，最低更新速度由0.04提高到0.08 m/s，融合由0.45降到0.20。终点柔性制动起点由0.35 m提前到0.50 m；0.22 m STOP 不变。旧的“满弯螺旋桨55%且尾舵升到92%”方案已被实机否决。
- 涉及文件：`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`VISION/path_guidance.py`、`VISION/yolo(PID).py`、`VISION/tests/test_path_guidance.py`、`VISION/VISION_OPTIMIZATION_PLAN.md`、`process.md`。
- 验证方式和结果：视觉 Python 语法检查通过，51 项单元测试全部通过，新增覆盖默认0.50 m制动起点和航向单次融合不跟随90°鱼尾摆动。ESP-IDF 5.3.2 完整编译、链接和分区检查通过，应用镜像938528字节，OTA分区剩余72%；生成 `RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260815-142933.bin`，SHA-256 为 `683001944eb3f041803cd394460c3624ed085cc88bc2d7650f249ef61516d8cf`。
- 已知限制：新参数尚未烧录和入水验证；橙色色标仍在摆动鱼尾上，较强滤波只能减弱伪航向，不能得到真实瞬时鱼头方向。纯前馈动力百分比尚无水动力标定，满弯20%螺旋桨/60%鱼尾可能需要一次实机微调。
- 待确认事项：烧录新镜像后优先跑同一条短轨迹；比较满弯速度是否明显低于轻弯、X 是否不再频繁换向、ESC 是否不再长期到64°/115°。若转弯变慢但仍超调，先把 `Kp` 从300降到250；若速度仍降不下来，再只降低鱼尾满弯动力，不引入速度D环。

## 2026-08-15 视觉曲率预判、转向限幅与弯道减速

- 修改原因：最新实机日志中离轨超过约 0.12 m 后 `弯=1.00` 长期不释放，X 反复饱和到 `±0.240 m`，即使航向误差已缩小仍持续大舵量；用户要求降低转向增益、按前方路径曲率提前控制，并在转向时减速。
- 最终决策：保留航向误差闭环纠偏，并用前方 4～12 cm 与约 20～32 cm 两段平滑路径弦线预估未来 0.32 m 曲率，曲率仅以 0.25 倍轻量前馈提前转向且离轨时淡出。离轨距离达到 0.18 m 时前视由 0.24 m 缩到 0.14 m、吸附增益最高 1.25 倍，X 命令限制为 `±0.18 m`；离轨比例不再直接强制满转。下发的 `curve` 取路径曲率与实际舵量严重度的较大者，ESP32 把螺旋桨动力上限由直线 100% 渐降到满弯 55%；尾舵维持现有 74%～92% 独立动力。普通转弯不进入反转制动，只有终点 0.35 m 范围沿用柔性反转制动，0.22 m 内渐变 STOP。
- 涉及文件：`VISION/path_guidance.py`、`VISION/yolo(PID).py`、`VISION/tests/test_path_guidance.py`、`VISION/VISION_OPTIMIZATION_PLAN.md`、`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`process.md`。
- 验证方式和结果：`yolo(PID).py` 与 `path_guidance.py` 语法检查通过；49 项视觉单元测试全部通过，新增覆盖直线零曲率、左右弯符号、弯前转向/减速、严重离轨但朝向正确时释放舵量及 `±0.18 m` 限幅。ESP-IDF 5.3.2 完整编译、链接和分区检查通过，应用镜像 938560 字节，OTA 分区剩余 72%；生成 `RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260815-141552.bin`，SHA-256 为 `226869560f833d4a4e2dcf82b6a9d0ae841b480367046147f36b4743e8409edd`。
- 已知限制：尚未烧录或入水验证；单个摆动鱼尾色标会给位置、速度和运动航向引入周期误差，离线曲率测试不能证明实鱼转弯半径和制动距离已经合适。
- 待确认事项：烧录后先跑一条直线接单弯的短轨迹，观察终端中的 `角/弯/esc`：进入弯道前 `弯` 应先升高，鱼头对准后 `esc` 应主动回到 90°附近；若仍过冲，优先继续降低曲率前馈或螺旋桨弯道上限，不恢复“离轨即满舵”。

## 2026-08-14 VISION 由纯 PROP 切换为 HYBRID 联合转向

- 修改原因：用户实测确认螺旋桨单独转向力不足，决定加入仿生双尾舵形成混合推进。原 VISION 启动前只确认 PROP，而固件 `applyVisionControl/applyVisionPid` 每帧都强制写回 `DriveMode::Prop`。
- 最终决策：VISION 启动时循环确认进入 `HYBRID`；MCU 两个视觉控制入口统一固定 `DriveMode::Hybrid`。X PID 的正负和幅度同时驱动双尾舵偏置和螺旋桨转向；Y PID 的动力百分比同时驱动尾舵 CPG 摆幅与螺旋桨油门。右转 2°/35°/18° 轻补偿、左右极性、PID 参数、路径公式和停止逻辑不变。`/vision_control` ACK 的 `mode` 同步改为 `HYBRID`，不增加新协议字段。
- 涉及文件：`RoboFishPartnerDriverSDK/src/control/MotionController.h/.cpp`、`src/web/ProductWebService.cpp`、`VISION/yolo(PID).py`、`VISION/vision_toolbar.py`、`VISION/VISION_OPTIMIZATION_PLAN.md`、`process.md`。
- 验证方式和结果：五个视觉 Python 文件 `py_compile` 通过，31 项 `unittest` 全部通过。ESP-IDF 5.3.2 编译、链接和分区检查通过；应用镜像 937632 字节，OTA 分区剩余 72%，最终生成 `RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260814-184355.bin`，SHA-256 为 `47b0b832ccd34a56cf03c264700764ad0565051f4d5865173b927d30583c99f8`。
- 已知限制：尚未烧录或入水验证。HYBRID 会同时增加尾舵横向力和螺旋桨推力，可能放大既有侧翻风险；单鱼尾色标仍不能直接测量实时鱼体航向。
- 待确认事项：烧录后先架空确认左右指令下双尾舵偏置和螺旋桨转向同向；再入水跑短直线/折线，同时观察转弯半径、X 误差是否收敛及侧翻方向。

## 2026-08-14 视觉检测/引导解耦与鱼体坐标 LOS

- 修改原因：原主程序把 YOLO、路径几何、鱼头标定、UI 和通信混在一个文件；X 误差是水池坐标下的线段横差，鱼头方向只显示不参与控制，导致鱼可能一直直走；原路径没有等距插值和前视，终点旁侧还可能因剩余路程为零提前失去推进。
- 最终决策：新增 `fish_detector.py`，在后台线程延迟导入 Ultralytics/Torch，采用单槽最新帧且不积压；新增 `path_guidance.py`，统一负责 3 cm 等距路径、单向进度、20 cm 前视、人工初始鱼头方向、可靠色标运动航向和鱼体左右 LOS 误差。水池坐标 y 向下时，鱼体左侧为 `heading_y * target_x - heading_x * target_y`，正值继续映射固件 LEFT。推进误差独立为 `max(沿路径剩余, 到终点欧氏距离)`，避免投影到末端但仍偏离终点时停死；到达同时要求路径进度和终点欧氏距离进入 0.12 m。正后方目标固定沿用同一转向侧，避免 ±180° 噪声翻转。主程序只保留相机、UI、标定、网络、录像和绘制编排。
- 涉及文件：`VISION/fish_detector.py`、`VISION/path_guidance.py`、`VISION/yolo(PID).py`、`VISION/vision_toolbar.py`、`VISION/tests/test_fish_detector.py`、`VISION/tests/test_path_guidance.py`、`VISION/VISION_OPTIMIZATION_PLAN.md`。
- 验证方式和结果：五个视觉 Python 文件 `py_compile` 通过；31 项 `unittest` 全部通过，覆盖后台加载、最新帧、关闭状态、左右符号、正后方稳定转向、回环不提前到达和末端旁侧继续推进；`git diff --check` 通过。视觉 X PID `Kp` 从 150 提至 450，ESP-IDF 5.3.2 构建成功。
- 已知限制：单个橙色鱼尾仍会随摆尾移动，动态航向只能用可靠色标的运动方向近似，不能测量鱼体真实艏向或侧滑角；相机、网络和录像尚未从主程序拆出；未进行入水闭环验证。
- 待确认事项：实机先画短直线和左右折线，观察终端 `x` 正负、ACK `applied/esc` 与鱼实际左右是否一致，再决定前视距离、X PID 和航向融合参数。

## 2026-08-14 螺旋桨右转单边 PWM 死区补偿

- 修改原因：用户确认左转正常、右转响应异常，判断为电调/推进混控正向侧不一致并要求软件补偿。现有 GPIO44 转向通道以 90° 为中心，逻辑左为负偏移、逻辑右为正偏移；软件不能证明是物理电流死区，因此按 PWM 指令侧不对称处理。
- 最终决策：用户实测否决首版 5°/40°/22° 强补偿。左转映射和最大 32°/16° 保持不变；实际正偏移侧的任何非零转向改为 2° 起步，再随转向百分比线性增加，纯 PROP 右侧最大 35°，HYBRID 右侧最大 18°。补偿放在统一 `MotionController` 螺旋桨混控出口，因此网页和 VISION 同时生效，`steeringReversed` 后按实际 PWM 正侧判断。
- 涉及文件：`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`RoboFishPartnerDriverSDK/src/control/MotionController.cpp`。
- 验证方式和结果：ESP-IDF 5.3.2 完整构建、链接和分区检查通过；应用镜像 937648 字节，OTA 分区剩余 72%，生成 `RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260814-182925.bin`，SHA-256 为 `f008e91af026a4941cc19999ddf5d5ba3c653958f51f843f89f93945b3becf50`。满右转目标为 125°，仍低于 136° 软件上限；24% 转向时左/右偏移约为 8°/10°。
- 已知限制：轻补偿仍是开环试值，尚未由电流、PWM 波形或左右转弯半径标定。最新视觉日志证明负 X 误差持续触发正偏移右转，但误差由约 -0.02 m 扩大并饱和到 -0.20 m，说明视觉航向估计或闭环左右关系仍未收敛，不能只靠右转补偿解决。
- 待确认事项：烧录轻补偿镜像后先用网页对比同一百分比左右转弯，再跑短视觉直线；若网页左右接近但视觉 X 误差仍持续同号扩大，停止调电调补偿，转查航向更新和视觉左右闭环。

## 2026-08-14 视觉 PID ACK 最小执行遥测

- 修改原因：现有 `/vision_pid` ACK 只证明 HTTP 请求被接收和排队，不能确认 `VisionControl` task 是否处理了样本，也不能看到转向输出；用户否决同时增加 `action`、`turn_strength` 和 `esc_steering` 等重复字段，要求保留最少诊断信息。
- 最终决策：ACK 只新增 `applied_seq` 和 `esc`。`applied_seq` 在 `VisionControl` task 实际消费最新 PID 样本后更新；`esc` 是经过转向渐变后的 ESC 舵机输出角，90°为中位。`action` 与 `turn_strength` 不传，因为方向和幅度已由 `esc` 相对 90°的偏差表达。VISION 终端 ACK 行精简为接收序号、已执行序号、ESC 舵角和 RTT；入队行继续显示 X/Y 误差。控制公式、PID 参数、任务周期、优先级、超时和执行器映射均不变。
- 涉及文件：`RoboFishPartnerDriverSDK/src/control/MotionController.h/.cpp`、`RoboFishPartnerDriverSDK/src/web/ProductWebService.cpp`、`VISION/yolo(PID).py`、`process.md`。
- 验证方式和结果：按 `.vscode/tasks.json` 的 ESP-IDF 5.3.2 Build 任务完成编译、链接和分区检查；应用镜像 937600 字节，OTA 分区剩余 72%，生成 `RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260814-172341.bin`，SHA-256 为 `3128465a12c5d16edbd42a8ae1bb49633d234c5870be5172f441efd93dea50c6`。VISION 三个 Python 文件 `py_compile` 通过，16 项 `unittest` 全部通过，`git diff --check` 通过。
- 已知限制：ACK 是异步状态快照，正常时 `applied_seq` 可比当前 `seq` 慢一帧，`esc` 也可能体现上一控制周期；若序号持续推进后仍长期不增长才表示视觉任务未消费。当前只验证到软件输出值，尚未烧录，也不能证明 GPIO44、舵机机构或水动力实际响应。
- 待确认事项：烧录新固件后运行短轨迹；若 `applied_seq` 连续跟进且 `esc` 明显偏离 90°但鱼仍直走，转查 GPIO44、侧舵机构和推进结构；若 `esc` 偏转方向与误差扩大方向一致，反转视觉转向极性。

## 2026-08-14 VISION 动力对齐、缩放鼠标修复与初始鱼头方向

- 修改原因：用户认为 VISION 推进和转向过软，确认优先提高动力；随后要求放大预览窗口、减小顶部遮挡、修复鼠标点击，并增加简单的鱼头方向标定。本次明确没有平板，不把平板连接作为验证条件。
- 最终决策：VISION 纯 PROP 直行上限与网页一致为 100%，转弯推进上限为 80%，转向由 70% 放开到 100%；Y 轴推进参数改为 `Kp=800, Ki=0, Kd=0`，约 12.5 cm 外达到直行满档，保留 1.5 cm 死区和 500 ms 视觉指令超时停机。预览窗口按屏幕 90% 范围保持画面比例放大；顶部卡片缩小并改为 35% 不透明度。当前 `opencv-python 5.0.0.93 / WIN32UI` 实机没有向 `setMouseCallback` 发送任何鼠标事件，因此否决“继续调整 HighGUI 坐标映射”的方向；Windows 下改为轮询原生主鼠标/触屏按键状态与绝对光标位置，再按 `getWindowImageRect` 映射到 640×480，非 Windows 才保留 OpenCV 回调。新增“鱼头方向”按钮：可靠橙色鱼尾中心自动作为尾点，用户单击鱼头中心后记录尾→头初始方向；该方向不是实时艏向。
- 涉及文件：`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`src/control/MotionController.h/.cpp`、`src/web/ProductWebService.cpp`、`VISION/yolo(PID).py`、`VISION/vision_toolbar.py`、`VISION/tests/test_vision_toolbar.py`、`process.md`。
- 验证方式和结果：ESP-IDF 5.3.2 对 ESP32-S3 完整构建、链接和分区检查通过；应用镜像 `RoboFishPartnerDriverSDK/build/idf/RoboFishPartnerDriverSDK.bin` 为 937472 字节，OTA 分区剩余 72%，SHA-256 为 `eeee1120b91203f3e24b9e8ab15a4d03309ea8530bfc1351ad63f129667a351a`。VISION 三个 Python 文件 `py_compile` 通过，16 项 `unittest` 全部通过，覆盖 12 个按钮命中、窗口尺寸和 Windows 绝对指针到 640×480 的映射。随后启动无相机、无 YOLO、无平板、无机器鱼的真实 HighGUI 测试窗；Windows 原生输入实际捕获到 `CLEAR_PATH`、`POOL_CALIB` 及多次画布按下/抬起，用户确认“点击成功”。`git diff --check` 通过。
- 已知限制：正式 VISION 启动时摄像头曾出现首帧后连续无新帧并按现有 0.5 秒保护退出，因此本轮没有在完整 YOLO 运行窗口内完成四角标定；鼠标/触屏输入层已独立实机通过。没有平板连接或平板通信验证；本地平板 TCP 服务无人连接时只保持空闲监听，不影响电脑端鼠标控制。没有烧录、驱动执行器或入水验证；更高动力可能放大当前转向符号或航向模型错误。
- 待确认事项：摄像头连续出帧稳定后，在正式窗口依次点击场地四角；随后完成鱼尾标定，点击“鱼头方向”并单击鱼头中心，确认方向箭头从尾指向头。

## 2026-08-14 中文视觉界面、鱼尾自动标定与 PID 问题诊断

- 修改原因：实机截图显示原 HUD 字号过大、英文状态重叠、按钮配色杂乱；用户要求中文化并简化 ROI 标定，最终选择先跟踪现有橙色鱼尾，同时指出鱼头指向尚未确定。
- 最终决策：使用微软雅黑/黑体渲染完整中文界面，HUD 改为顶部两块紧凑深灰半透明卡片，工具栏统一为深灰底、青蓝主色、绿色成功、橙色警告、红色仅用于停止/退出；按钮改为中文。`鱼尾标定`允许粗框鱼尾附近区域，程序自动提取 HSV 高饱和橙色轮廓、排除多目标和边界裁切并取轮廓质心，成功后显示自动框和中心十字 3 秒。旧模型 `90×54 px / sat_min=5 / area=924.5 px²` 因包含白色鱼身和反光而自动判为不合格，要求重新标定。鱼尾不是刚性鱼身参考点，因此精标定可用性保持为否。
- PID 诊断证据：电脑端定义的 `PIDController` 当前没有参与轨迹控制；实际控制是单片机 X/Y 两个 PID。运行日志中横向误差从 `+0.015 m` 持续增至约 `+0.45 m`，说明当前转向符号或“误差相对鱼头方向”的假设不成立；剩余距离约 `1.187 m` 时，Y 轴 `Kp=180` 已把推进长期夹到 70%，形成近似满油门；控制器只看位置横差和剩余距离，没有鱼头指向、运动航向、前视点或速度闭环。日志还出现多次 HTTP timeout。以上是公式/观测结构问题，不能只靠微调 PID 参数解决，本次未修改 MCU 控制公式。
- 涉及文件：`VISION/vision_toolbar.py`、`VISION/fixed_reference_tracker.py`、`VISION/yolo(PID).py`、`VISION/requirements.txt`、`VISION/tests/test_fixed_reference_tracker.py`、`VISION/tests/test_vision_toolbar.py`、`VISION/VISION_OPTIMIZATION_PLAN.md`、`process.md`。
- 验证方式和结果：生成 640×480 离线预览确认中文字体、紧凑布局与统一配色后删除预览文件；14 项 `unittest` 全部通过，三个 Python 文件 `py_compile` 通过，`git diff --check` 通过。随后直接读取用户保存的原始 `640×480` 截图做离线鱼尾标定：粗框 `(390,240)→(490,320)` 后，程序自动得到橙色鱼尾框 `(425,271)→(459,292)`、轮廓中心 `(441.45,283.09)`、面积 `379.5 px²`，证明无需精确手框。没有启动相机、下发推进、连接机器鱼或修改/编译 MCU 固件。
- 已知限制：鱼尾摆动会给位置和速度引入周期误差；单个鱼尾点不能判断鱼头指向。当前结果适合快速验证识别和极性，不适合最终轨迹精度或 PWM—速度标定。

## 2026-08-14 视觉固定参考点离线框架与可点击工具栏

- 修改原因：用户确认先建立阶段 1 框架，等连接摄像头并提供鱼的照片后再做实物参数标定；同时指出原视觉程序功能主要依赖键盘快捷键，难以记忆，要求优化 UI。
- 最终决策：新增独立 `FixedReferenceTracker`，把刚性色标物理中心定义为唯一精确鱼体位置。YOLO 只提供身份、搜索框和重捕获；有色标时输出 `MARKER`，缺测最多约 0.16 秒输出 `PREDICTED`，之后输出无位置的 `INVALID`；无色标时仅输出不可用于 PWM—速度精标定的 `ESTIMATED_FALLBACK`。增加面积、圆度/矩形度、长宽比、颜色覆盖、搜索边界裁切、预测位置突变和总质量门控，并把光照相关模型保存到被 Git 忽略的 `VISION/marker_profile.local.json`。主程序 JSON/OSD 增加来源、质量、门控原因和精标定可用性，无效速度/方向显示 `INVALID`。底部新增 11 个可点击按钮：启动、停止、清轨迹、色标框选、场地标定、录像、截图、CLAHE、曝光减/增和退出；键盘仅保留兼容快捷键。
- 涉及文件：`VISION/fixed_reference_tracker.py`、`VISION/vision_toolbar.py`、`VISION/tests/test_fixed_reference_tracker.py`、`VISION/tests/test_vision_toolbar.py`、`VISION/yolo(PID).py`、`VISION/VISION_OPTIMIZATION_PLAN.md`、`.gitignore`、`process.md`。
- 验证方式和结果：使用项目 `VISION/.venv` 执行 11 项 `unittest` 全部通过，覆盖 YOLO 框大小变化、鱼身绕固定点旋转、位置假跳变、短时预测后 `INVALID`、边界裁切、重捕获、无色标降级、配置读写、工具栏按钮命中与渲染范围；三个 Python 文件 `py_compile` 通过，`git diff --check` 通过。
- 已知限制：当前全部测试使用合成图，没有连接摄像头、机器鱼或单片机，也没有下发推进或烧录。HSV、色标期望面积/形状、允许跳变和旋转漂移阈值仍是保守框架值；水面反光、折射、深度变化、侧翻和真实曝光会改变成像，不能根据合成测试宣称阶段 1 实物验收完成。单个色标仍不测鱼体艏向或侧滑角。
- 待确认事项：用户连接摄像头后提供固定鱼、不同旋转角、正常光照、强反光和部分遮挡照片；据此选择刚性色标、通过 `MARKER ROI` 生成模型、调整门控参数并实测像素漂移。实物验收通过前保持阶段 2 待实施。

## 2026-08-14 三模式收紧转弯与HYBRID慢升油

- 修改原因：用户实测推进速度改善后转弯半径仍过大，并确认BIONIC、PROP、HYBRID三种模式都要提高转向能力；同时要求HYBRID螺旋桨更慢启动以减小瞬时反扭矩，且不增加IMU。
- 最终决策：BIONIC/HYBRID双尾舵转向偏置由12°/8°提高到18°/14°；纯PROP/HYBRID螺旋桨转向舵角由24°/8°提高到32°/16°；纯PROP网页直行动力保持100%，左右转动力单独降为80%，避免满油门顶舵扩大半径；ESC转向每20 ms渐变由4°提高到8°。HYBRID仅在油门离开中位、动力幅值增大时使用每20 ms 1°慢升油，减速、STOP和换向先以原3°速度回中；BIONIC和纯PROP油门渐变不变。
- 涉及文件：`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`src/control/MotionController.cpp`、`src/web/ProductWebService.cpp`、`process.md`。
- 验证方式和结果：静态计算确认最大转向时BIONIC两尾舵范围30.5°～141.5°/34.25°～137.75°，HYBRID为28.5°～143.5°/32.85°～139.15°，均在20°～152°限位内；PROP/HYBRID转向目标分别58°～122°、74°～106°，均在40°～136°限位内。HYBRID正向从中位升至75%约0.62秒，STOP约0.22秒回中；PROP转弯正向油门目标由满动力124降为117。ESP-IDF 5.3.2增量构建、链接和应用分区尺寸检查通过，应用镜像937456字节，OTA分区剩余72%。生成 `RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260814-135524.bin`，SHA-256 为 `ebdc9e5b3c2ce7daa8746591b7cc66c90754c581e3b5f38a7f899e6222c4569c`。
- 已知限制：用户已报告当前实机在水下存在侧翻，具体发生模式、方向和稳态/瞬态特征仍待分离；本次新镜像尚未烧录和入水验证。增大转向力可能同时增大横向载荷，编译与静态限位通过不能证明侧翻得到解决。软件没有IMU或横滚闭环，本次仅通过慢升油和开环转向参数降低瞬态风险。
- 待确认事项：入水分别测试绿色BIONIC、红色PROP和紫色HYBRID的左右转弯半径、侧翻方向和停车时间；若直行仍固定向同一侧翻，优先检查舵机中位、尾鳍安装、左右配重和螺旋桨反扭矩，不继续盲目增加转向角。

## 2026-08-14 网页尾部动力增强与后舵真滞后

- 修改原因：用户入水实测 BIONIC/HYBRID 推进偏弱、双尾舵摆幅不足，并观察到前后尾舵配合仍有卸力感；当前网页尾部模式统一使用55%动力，且生成器采用 `sin(phase + offset)`，原0.1667/0.20周期会让后舵提前而非滞后。
- 最终决策：网页 BIONIC/HYBRID 动力由55%提高到75%，纯 PROP 保持100%；在不改生成器公式的前提下，将 BIONIC/HYBRID 相位偏移改为0.83333333/0.80周期，分别等效于后舵滞后60°/72°；每20 ms尾舵渐变上限由6°/10°配套提高到8°/11°并集中到 `sdk_config.h`。频率1.7/2.0 Hz、前舵幅值基数50°/58°、后舵0.9比例及转向偏置保持不变。
- 涉及文件：`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`src/control/MotionController.cpp`、`process.md`。
- 验证方式和结果：静态计算确认75%下 BIONIC 前/后舵半摆幅为37.5°/33.75°、每周期最大变化7.996°/7.196°；HYBRID为43.5°/39.15°、每周期最大变化10.904°/9.814°，均不超过新渐变上限。含最大转向偏置时两舵目标仍在34.5°～137.5°内，未触及20°～152°软件限位。ESP-IDF 5.3.2增量构建、链接和应用分区尺寸检查通过，应用镜像937328字节，OTA分区剩余72%。生成 `RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260814-131937.bin`，SHA-256 为 `d935f1c26bc4a48ff06db893ed3222405de9d6d51ecca80a11da5c8cac7a4cff`。
- 已知限制：尚未烧录和入水验证；静态限位与编译通过不能证明舵机在水载荷下能跟随8°/11°每周期的变化，也不能替代前后舵物理安装方向确认。
- 待确认事项：先架空低时长点动，确认后舵实际跟随前舵且无机械干涉，再入水比较直行推力、尾端合成摆幅、电流、偏航和HYBRID螺旋桨动力；若后舵仍弱，再单独评估0.9幅值比例。

## 2026-08-14 HYBRID 尾舵频率柔化

- 修改原因：用户实测 HYBRID 尾部缺少柔性感；当前 2.45 Hz 在55%动力下每20 ms最大目标变化约9.783°，几乎贴住10°渐变上限。
- 最终决策：仅将 HYBRID 尾舵频率从2.45 Hz降至2.0 Hz，BIONIC保持1.7 Hz；两项频率集中到 `sdk_config.h`。HYBRID 的58°基准摆幅、55%网页动力、72°相位参数、10°渐变上限、螺旋桨动力和公式均不变。
- 涉及文件：`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`src/control/MotionController.cpp`。
- 验证方式和结果：静态计算确认 HYBRID 前舵在55%动力下实际摆幅31.9°，每20 ms最大目标变化降至约7.996°；ESP-IDF 5.3.2增量构建、链接和应用分区尺寸检查通过，应用镜像937328字节，OTA分区剩余72%。生成 `RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260814-125606.bin`，SHA-256 为 `a9086685b905d80243a1077ceeb1c617cbf1074c4acf2f558275605c3a3e5048`。
- 已知限制：尚未烧录观察实际柔性和推进效率；当前公式仍使用 `phase + 72°`，若实机后舵表现为抢先而非跟随，下一步应优先验证物理方向后再调整相位参数。
- 待确认事项：实机对比2.45 Hz与2.0 Hz的尾部柔性、直行推力和偏航；若仍不自然，确认前后舵运动先后关系，再决定是否将HYBRID相位参数从0.20周期改为0.80周期。

## 2026-08-14 IDLE 启动模式与 RGB 状态区分

- 修改原因：用户要求连接成功后保持 IDLE，未下达模式指令时不得默认选择推进模式；同时要求新增启动、启动失败和连接颜色，但保留推进模式颜色。
- 最终决策：新增 `DriveMode::Idle=0` 并作为上电默认模式。连接事件只更新链路状态，不选择推进模式；第一次网页 MODE 指令执行 IDLE→BIONIC，随后按 BIONIC→PROP→HYBRID→BIONIC 循环。IDLE 下人工及 Partner 非停止运动命令返回拒绝，停止、俯仰、水泵仍可用；视觉控制、视觉 PID、Demo 和 Partner 模式命令均属于显式选择，继续进入各自指定模式。此前“连接颜色长期替代推进模式颜色”的方向被用户否决。
- RGB 映射：应用启动中为蓝色；任一核心启动环节失败为红色并保持；启动成功且 IDLE 未连接为蓝色、IDLE 已连接为青色；BIONIC 为绿色、PROP 为红色、HYBRID 为紫色；失联保护为橙色且优先于模式色。
- 涉及文件：`RoboFishPartnerDriverSDK/src/control/MotionController.h/.cpp`、`src/app/RoboFishRuntime.h/.cpp`、`RoboFishPartnerDriverSDK/README.md`。
- 验证方式和结果：ESP-IDF 5.3.2 增量构建、链接和应用分区尺寸检查通过；应用镜像 937296 字节，OTA 分区剩余 72%。生成 `RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260814-123343.bin`，SHA-256 为 `5ca3c92d23fca63cc66eb954361d3249b9a38271f076dd107ae7c8671a30bbec`。
- 已知限制：尚未烧录验证灯色和网页拒绝反馈；若 RGB 灯条自身初始化失败，则硬件无法显示启动失败红色。编译通过不能证明实际 GRB 色序与肉眼颜色正确。
- 待确认事项：实机依次验证蓝色启动、青色已连接 IDLE、首次 MODE 后绿色 BIONIC、后续红色 PROP/紫色 HYBRID、断联保护橙色，以及 IDLE 下运动按钮不会驱动执行器。

## 2026-08-14 网页人工动力按推进模式分流

- 修改原因：统一降到 55% 能避免高频尾舵 CPG 超过渐变跟踪能力，但用户实测纯 PROP 直行推力明显不足，要求恢复螺旋桨动力。
- 最终决策：网页 `servo_forward`、`servo_backward`、`servo_left`、`servo_right` 读取当前模式并显式传入动力；纯 PROP 使用 100%，BIONIC/HYBRID 使用 55%，转向力度仍为 100%。频率、相位、摆幅基值、油门渐变、停止渐变和运动公式不变。此前“所有推进模式统一使用 55%”的方向不再采用；视觉与 Partner 显式动力参数不受网页默认值影响。
- 涉及文件：`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`src/control/MotionController.h`、`src/web/ProductWebService.cpp`。
- 验证方式和结果：ESP-IDF 5.3.2 增量构建、链接和应用分区尺寸检查通过；应用镜像 937328 字节，OTA 分区剩余 72%。生成 `RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260814-124556.bin`，SHA-256 为 `f7a450e4c2149a95577a0a2b5dc32061b2ba9a29a859d4bcf358cffbd9a0ec00`。
- 已知限制：尚未烧录和入水验证。PROP 的 100% 命令仍按现有每 20 ms 最大 3°的油门渐变输出，不是瞬时满油；左右转尾部偏置和物理方向问题未在本次修改。
- 待确认事项：架空确认 PROP 渐变升速和停止正常，再入水比较 100% 直行推力；BIONIC/HYBRID 继续验证 55% 下的尾舵波形、转向方向和推进效率。

## 2026-08-13 视觉端切换 MCU 双 PID 协议

- 修改原因：用户要求试运行 MCU X/Y PID，视觉端需要停止本地 PID 并发送标定误差。
- 最终决策：`VISION/yolo(PID).py` 保留 YOLO、标定、轨迹和 10 Hz 最新值队列；移除运行期电脑转向 PID，改发 `GET /vision_pid?seq=&x_error=&y_error=`，其中 X=`cross_m`、Y=`dist_m`，并校验 JSON ACK 的 `ok` 与回显序号。
- 安全行为：同步停止前先清空待发送队列，防止 stop 后旧 PID 命令出队；相机/目标丢失、清轨迹和退出仍发送 `servo_stop`。
- 验证方式和结果：视觉虚拟环境 Python 语法检查通过；本地模拟 MCU 验证实际请求为 `/vision_pid?seq=1&x_error=0.1250&y_error=1.7500` 且 ACK 校验通过。
- 已知限制：当前 `192.168.4.1/get_ip` 和 `/vision_pid` 均超时，未连接到可响应的机器鱼，因此没有进行实机推进测试。

## 2026-08-13 MCU 双轴视觉 PID

- 修改原因：用户确认执行器极性正确，并要求 X/Y 两个视觉 PID 全部放到单片机侧。
- 最终决策：新增 `GET /vision_pid?seq=&x_error=&y_error=`；`x_error` 是横向误差（米，正值保持现有左转极性），`y_error` 是到终点的剩余距离（米）。静态 `VisionControl` task 只在收到新视觉样本时计算 X 转向 PID 与 Y 推进 PID，输出分别限制为 -70..70 和 0..70；原 `MotionControl` task 继续独占硬件输出。
- 参数与保护：X PID 为 150/8/35，Y PID 初值为 180/2/10，积分限制 0.5，死区 0.015 m；保留序号防倒序和 500 ms 超时停车，旧 `/vision_control` 兼容接口仍保留。
- 涉及文件：`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`src/control/MotionController.h/.cpp`、`src/web/ProductWebService.h/.cpp`。
- 验证方式和结果：ESP-IDF 5.3.2 编译、链接和应用分区尺寸检查通过；应用镜像 934592 字节，OTA 分区剩余 72%。
- 已知限制：尚未在真实水池验证 PID 增益和动态响应；当前电脑端仍发送旧离散动作，尚未改为调用 `/vision_pid`。
- 待确认事项：完成电脑端协议修改后，先架空螺旋桨确认正横向误差左转，再以低功率短轨迹整定 Y PID。
- 生成文件：`RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260813-161910.bin`。

## 2026-08-13 视觉 PID 鱼端控制接口

- 修改原因：用户要求电脑视觉与机器鱼形成闭环，先完成单片机侧接口，暂不修改视觉 Python。
- 最终决策：新增 `GET /vision_control?seq=&power=&steering=`，复用现有 `MotionController`，自动使用 PROP 模式；`power` 限制 0..70，`steering` 限制 -70..70，序号拒绝重复或倒序命令。视觉租约和 500 ms 超时停车由独立静态 `VisionControl` FreeRTOS task 负责，ESC 输出仍由原 `MotionControl` task 独占。
- 安全行为：视觉指令 500 ms 未刷新时自动停止推进并回中转向；网页人工控制、Partner、OTA 和现有 `/control` 接口保持原有路径。
- 涉及文件：`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`src/control/MotionController.h/.cpp`、`src/web/ProductWebService.h/.cpp`。
- 验证方式和结果：ESP-IDF 5.3.2 目标构建成功，应用镜像 926480 字节，OTA 分区剩余 72%；尚未在真实鱼上验证 ESC 左右方向、网络延迟和超时停车。
- 生成文件：`RoboFishPartnerDriverSDK/build/RoboFishPartnerDriverSDK-OTA-20260813-161047.bin`。

## 2026-08-13 OTA 实机验证标记

- 修改原因：用户要求执行一次可肉眼确认的无线 OTA 测试。
- 最终决策：仅在遥控网页顶部增加醒目的 `OTA TEST SUCCESS · 2026-08-13` 绿色标记，不改运动和保护逻辑。
- 涉及文件：`reverse_analysis/web_assets/html_01_0x0000100b.html`。
- 验证方式和结果：目标固件编译与无线 OTA 结果在本次测试结束后确认。
- 已知限制：旧 Service Worker 可能缓存 `/gpio`；验证时使用带查询参数的新地址绕过旧缓存。
- 待确认事项：OTA 重启后访问 `/gpio?ota-test=20260813` 确认标记和相机图传。

## 2026-08-13 无 PSRAM 摄像头启动修复

- 修改原因：实机启动日志确认 OV3660 已识别，但无 PSRAM 时以 UXGA 初始化会申请 384000 字节内部 RAM 帧缓冲并失败，导致端口 81 图传服务未启动。
- 最终决策：保留有 PSRAM 时的 UXGA 初始化；无 PSRAM 时直接以网页实际使用的 SVGA 初始化，避免无意义的大帧缓冲申请。
- 涉及文件：`RoboFishPartnerDriverSDK/src/camera/CameraService.cpp`。
- 验证方式和结果：实机日志已确认原故障为 `frame buffer malloc failed`；修复后完成 ESP-IDF 目标构建，实机图传结果待重新烧录确认。
- 已知限制：当前工程仍按原镜像配置关闭 PSRAM，仅使用单个内部 DRAM 帧缓冲。
- 待确认事项：重新有线烧录后确认 `Camera ready`、端口 81 MJPEG 和持续图传。

## 2026-08-04 SDK 内部重构

- 修改原因：按嵌入式固件工作流整理可编译 SDK，保持行为不变，降低执行器互斥锁路径和 OTA 任务参数维护风险。
- 最终决策：不修改公共 API、GPIO、执行器限幅、超时策略、OTA 认证策略、任务周期、优先级、栈大小或绑定核心；仅做内部结构重构。
- 涉及文件：`RoboFishPartnerDriverSDK/RoboFishDriver.h`、`RoboFishPartnerDriverSDK/RoboFishDriver.cpp`、`RoboFishPartnerDriverSDK/OtaService.cpp`、`RoboFishPartnerDriverSDK/sdk_config.h`。
- 验证方式和结果：已静态检查 SDK 源码中 FreeRTOS 等待路径和 OTA 任务参数引用；本机未安装 Arduino CLI、ESP32 Arduino 包或 Xtensa 编译器，未完成目标板编译。
- 已知限制：未进行硬件上电、执行器输出、Web OTA 上传或栈水位测量。
- 待确认事项：在 Arduino ESP32 Core 3.3.7 与 XIAO ESP32-S3 环境执行一次编译，并在硬件上确认 OTA 上传时执行器停机和锁定行为。

## 2026-08-04 SDK 框架分层

- 修改原因：用户要求进一步做“结构、框架”级重构，明确 Arduino 入口、app、config、device、service 的职责边界。
- 最终决策：实现文件迁入 `src/` 分层目录；根目录保留 `RoboFishDriver.h`、`OtaService.h`、`sdk_config.h` 兼容转发头；新增 `RoboFishRuntime` 负责启动编排、周期 update 和 OTA 停机回调。
- 涉及文件：`RoboFishPartnerDriverSDK.ino`、`ARCHITECTURE.md`、`README.md`、`src/app/RoboFishRuntime.h`、`src/app/RoboFishRuntime.cpp`、`src/config/sdk_config.h`、`src/device/RoboFishDriver.*`、`src/service/OtaService.*`、根目录兼容头。
- 验证方式和结果：已静态检查源码结构、include 路径、FreeRTOS 等待路径和 OTA 任务参数引用；未发现根目录残留实现 `.cpp`。
- 已知限制：本机仍未安装 Arduino CLI、ESP32 Arduino 包或 Xtensa 编译器，未完成目标板编译、硬件执行器输出、OTA 上传或栈水位测量。
- 待确认事项：在 Arduino ESP32 Core 3.3.7 与 XIAO ESP32-S3 环境确认 `src/` 递归编译、串口启动、Web OTA 和执行器停机锁定行为。

## 2026-08-04 Device 锁边界修正

- 修改原因：用户指出 device 包含灯条、两个尾舵、一个侧舵和一种螺旋桨，不应把所有执行器放在一个全局 mutex 下串行化。
- 最终决策：否决“全执行器单锁”方向；`RoboFishDriver` 改为兼容门面和 OTA 安全门，尾舵、侧舵、推进和水泵分别由独立 device owner 管理，每个 device 使用自己的静态互斥锁；OTA 的 `otaLocked` 只作为全局命令安全门。
- 涉及文件：`src/device/DeviceMutex.h`、`src/device/TailServos.*`、`src/device/SideRudder.*`、`src/device/Propulsion.*`、`src/device/PumpOutput.*`、`src/device/RoboFishDriver.*`、`ARCHITECTURE.md`、`README.md`、根 `README.md`。
- 验证方式和结果：已静态检查 device 目录无旧 `ScopedLock`/全局 `mutex_` 残留；未发现 `portMAX_DELAY` 或无限互斥等待；各等待仍使用有限超时或 0 tick 轮询。
- 已知限制：灯条未接入 SDK，当前缺少已确认的灯条 GPIO、协议、像素数和电气信息；本机仍未安装 Arduino CLI、ESP32 Arduino 包或 Xtensa 编译器，未完成目标板编译和硬件验证。
- 待确认事项：确认灯条硬件映射后新增 `LightStrip` device；在 Arduino ESP32 Core 3.3.7 与 XIAO ESP32-S3 环境确认 `src/device` 新增文件被递归编译，并验证 OTA 停机、舵机、推进和水泵输出。

## 2026-08-12 VS Code 编译与无线 OTA

- 修改原因：提供可重复的时间命名构建、电脑连接鱼热点、认证与 Web OTA 反馈入口，并防止误传非应用镜像。
- 最终决策：默认构建固定复用 XIAO ESP32-S3、Arduino ESP32 Core 3.3.7、8 MB Flash、`default_8MB` 双 OTA 分区和关闭 PSRAM；输出 `build/RoboFishPartnerDriverSDK-OTA-yyyyMMdd-HHmmss.bin`。无线拓扑固定为鱼 AP、电脑 STA，OTA 默认目标为鱼 AP 地址 `192.168.4.1`；工具只接受 `/status` 返回 `sdk=1.0.0` 且 AP 地址有效的目标。此前“电脑 AP、鱼 STA”的方向已被用户否决，不再生成或部署鱼 STA 凭据。
- 涉及文件：`.vscode/tasks.json`、`.vscode/launch.json`、`.vscode/settings.json`、`.vscode/robofish-ota.ps1`、`.gitignore`、`README.md`、`RoboFishPartnerDriverSDK/README.md`、`src/config/sdk_config.h`。
- 验证方式和结果：已核对固件使用 `WiFi.softAP` 创建鱼 AP；HTTP 路由为 Basic Auth `POST /update`、multipart 字段 `firmware`。已静态检查隐藏密码输入、目标状态校验、时间命名筛选、`0x330000` 大小门禁、上传前确认、设备反馈、资源释放和无自动重试；VS Code JSON 可解析，任务依赖完整，PowerShell AST 无语法错误，`git diff --check` 通过，FQBN 与已有 `build.options.json` 完全一致。
- 已知限制：本机未安装 Arduino CLI，未执行实际编译；未连接机器鱼热点、输入真实密码或上传固件。自动 Wi-Fi 连接使用 Windows `netsh`，并会为当前 Windows 用户保存机器鱼 Wi-Fi 配置。
- 待确认事项：安装构建环境后完成一次实际编译；在硬件上验证 AP 连接、认证失败反馈、上传成功反馈和重启后重新上线。

## 2026-08-12 VS Code 运行和调试入口

- 修改原因：用户要求从 VS Code“运行和调试”面板直接启动现有编译、联网和 OTA 流程。
- 最终决策：新增 `launch.json`，使用 `node-terminal` 启动器和 `preLaunchTask` 复用现有任务；不复制构建参数或密码，不宣称提供 ESP32 JTAG 断点调试。
- 涉及文件：`.vscode/launch.json`、`.gitignore`、`README.md`。
- 验证方式和结果：`launch.json` 可解析，6 个配置名称唯一，启动类型和请求类型有效，所有 `preLaunchTask` 均能在 `tasks.json` 中找到；`git diff --check` 通过。
- 已知限制：实际启动仍依赖 Arduino CLI/Arduino IDE 2.x、Windows Wi-Fi、机器鱼 AP 和硬件在线。
- 待确认事项：在 VS Code 中刷新工作区后确认运行配置列表可见，并完成一次硬件流程验证。


## 2026-08-12 完整固件摄像头与网页资源恢复

- 修改原因：用户要求依据 `CameraTest.ino.bin` 的静态逆向证据，在纯 ESP-IDF 工程中恢复摄像头接口、MJPEG 图传和原驾驶/Partner 网页资源。
- 最终决策：新增 `CameraService`，固定采用已确认的 XIAO ESP32-S3 Sense 摄像头引脚、JPEG、12 MHz XCLK 和 GPIO21 补光灯映射；主 HTTP 服务提供 `/status`、`/control`、`/capture`、`/bmp`，主端口加 1 的独立服务提供 `/stream`。`/control` 未识别参数通过回调交给运动应用层，保持相机和机器鱼命令共用原 URI。新增 `WebAssets`，用 `EMBED_TXTFILES` 直接链接四个恢复资源并提供 `/gpio`、`/partner`、`/manifest.json`、`/sw.js`，不改写前端业务协议。
- 涉及文件：`RoboFishPartnerDriverSDK/src/camera/CameraService.h`、`RoboFishPartnerDriverSDK/src/camera/CameraService.cpp`、`RoboFishPartnerDriverSDK/src/web/WebAssets.h`、`RoboFishPartnerDriverSDK/src/web/WebAssets.cpp`、`RoboFishPartnerDriverSDK/main/CMakeLists.txt`。
- 验证方式和结果：确认本机 ESP-IDF 5.3.2、工作区和常见 Arduino/PlatformIO 目录均没有 `esp32-camera`；缺组件路径会明确返回 `ESP_ERR_NOT_SUPPORTED`/HTTP 503。已在该真实缺组件环境完成 ESP32-S3 全量构建，并用 `xtensa-esp32s3-elf-nm` 核对四个嵌入资源的 `_binary_*_start/end` 符号与源码引用一致；`git diff --check` 通过。
- 已知限制：ESP-IDF 5.3.2 不自带 `esp32-camera`，当前构建只有可用的降级接口，未包含真实图像驱动；工程还关闭 PSRAM，后续启用相机时会使用单 DRAM 帧缓冲。恢复网页仍调用尚待整合的 Wi-Fi、运动、Partner 和旧 `/ota_upload` 协议；本条修改没有替换现有 OTA 服务。
- 待确认事项：将官方 `esp32-camera` 放入本地 `components/esp32-camera` 并登记依赖后，重新编译真实相机分支；在 XIAO ESP32-S3 Sense 上验证传感器型号、帧尺寸枚举、图像方向、GPIO21 亮度、DRAM 帧缓冲稳定性、端口 81 持续图传和并发控制响应。

## 2026-08-13 官方摄像头组件依赖闭环

- 修改原因：原工程只具备缺组件时的 HTTP 503 降级分支，尚未用真实 `esp32-camera` 编译相机初始化、抓拍、BMP 和 MJPEG 代码。
- 最终决策：在 `main/idf_component.yml` 声明官方 `espressif/esp32-camera ^2.0.0`，由 Component Manager 锁定 `esp32-camera 2.1.7`、传递依赖 `esp_jpeg 1.3.1` 和 ESP-IDF 5.3.2；提交清单与 `dependencies.lock`，忽略生成的 `managed_components/` 和 `build/*-idf/`。保持原固件证据对应的 PSRAM disabled、8 MB Flash、QIO 80 MHz，不为相机强行启用 PSRAM。
- 涉及文件：`RoboFishPartnerDriverSDK/main/idf_component.yml`、`RoboFishPartnerDriverSDK/dependencies.lock`、`RoboFishPartnerDriverSDK/components/README.md`、`.gitignore`。
- 验证方式和结果：在独立 `build/camera-idf` 使用 ESP-IDF 5.3.2 全量构建成功；编译定义包含 `RF_HAS_ESP32_CAMERA=1`，`CameraService.cpp` 对象存在 `esp_camera_init`、`esp_camera_fb_get`、`frame2bmp` 未定义引用，最终 ELF 链接出 `esp_camera_init`，证明真实分支参与编译和链接。应用镜像为 923808 字节，SHA-256 为 `a603272ce2c7efdbdf1b77dfbf6957a26e9bfcd84b669f5fdf6f65e1232a1b37`，OTA 分区剩余约 72%；构建日志未发现 warning 或 error。
- 已知限制：本次只验证源码、依赖解析和目标链接，未烧录硬件；PSRAM 关闭时相机采用单个 DRAM 帧缓冲，持续图传的帧率和内存余量尚无实机数据。ESP-IDF 5.3.2 在选择 QIO 时将镜像头模式字符串映射为 `dio`，但有效 Kconfig 选择仍为 `CONFIG_ESPTOOLPY_FLASHMODE_QIO=y`。
- 待确认事项：在 XIAO ESP32-S3 Sense 上验证摄像头型号、图像方向、帧尺寸、GPIO21 补光灯、DRAM 稳定性、端口 81 MJPEG 与并发遥控；不得把编译通过当作整机图传已经实测通过。

## 2026-08-13 Partner HTTP 接口恢复

- 修改原因：按完整固件静态证据恢复 Partner Lab 脚本 API，并为网络 owner 提供受控的 `/get_ip` 与 `/save_wifi` 回调边界。
- 最终决策：新增无独立 Task、无动态分配的 `HttpService`；注册 `GET/POST /partner_script`、`POST /partner_run`、`POST /partner_stop`、`GET /partner_status`，可选注册 `GET /get_ip` 和 `GET /save_wifi`。脚本正文严格限制 1～3500 字节并循环接收；启动失败返回 409；保存成功、停止成功、状态 JSON 和 Wi-Fi 重启正文保持恢复证据中的协议。网络状态、凭据持久化和重启仍由网络 owner 回调完成。
- 涉及文件：`RoboFishPartnerDriverSDK/src/partner/PartnerHttpService.h`、`RoboFishPartnerDriverSDK/src/partner/PartnerHttpService.cpp`。
- 验证方式和结果：复用 ESP-IDF 5.3.2 `compile_commands.json` 的 Xtensa ESP32-S3 C++ 参数独立编译通过，生成 128320 字节对象文件；`nm -C` 确认路由与七个处理路径符号存在；`git diff --check` 通过。
- 已知限制：本条只完成可注册服务，未改 Runtime、OTA 服务或 CMake；尚未在真实 HTTP 服务、NVS 和硬件网络上进行请求测试。
- 待确认事项：主线接入时必须保证服务实例生命周期长于 HTTP server、提供网络回调，并为新增路由预留足够 `max_uri_handlers`。

## 2026-08-13 视觉坐标标定加固

- 修改原因：手动标定原先不校验点击顺序、区域或矩阵，重新标定期间仍保留旧矩阵；自动标定只统计四个 ArUco 同时出现的帧数，不能证明角点稳定。
- 最终决策：保持水池映射 `3.14 m × 1.6 m` 和 TL→TR→BR→BL 坐标方向不变；新增凸性、顺序、最小面积、有限值和矩阵退化检查；显示手动点击编号；自动标定要求四个角点连续 15 帧最大位移不超过 2 像素；按 `T` 重新标定时立即发送停止并清除旧矩阵与位置滤波。Windows WIN32 HighGUI 的鼠标回调直接使用原图坐标，禁止再次按窗口尺寸缩放，避免二次映射偏移。
- 涉及文件：`VISION/yolo(PID).py`。
- 验证方式和结果：Python 语法检查通过；合规四点映射为 `(0,0)`、`(3.14,0)`、`(3.14,1.6)`、`(0,1.6)`；交叉顺序和过小区域测试均被拒绝。
- 已知限制：未在真实水池画面验证 ArUco 稳定阈值；物理尺寸必须与实际有效区域一致。
- 待确认事项：实机标定后核对中心点约为 `(1.57,0.8)`；架空执行器确认画面横向误差与机器鱼左右转符号一致。

## 2026-08-13 本机绘图 PROP 轨迹追踪

- 修改原因：用户要求直接在电脑 YOLO 画面绘制轨迹，并暂时只使用螺旋桨推进系统执行 PID 追踪。
- 最终决策：左键拖动创建单条像素轨迹，右键清除，Enter 启动，Space 停止，Q 或窗口关闭时停止后退出；启动前要求完成标定、YOLO 已识别鱼、轨迹起点距鱼不超过 0.40 m。启动时根据固件 `/control?var=mode&val=1` 的响应循环确认进入 `PROP`，之后只发送 `servo_forward`、`servo_left`、`servo_right`、`servo_stop`；PROP 模式保持尾舵中位，只驱动 ESC 油门与 ESC 转向。轨迹误差按 10 Hz 输入现有 PID，到终点 0.12 m 内停止；摄像头中断或 YOLO 目标丢失时停止并退出/取消追踪。
- 涉及文件：`VISION/yolo(PID).py`。
- 验证方式和结果：Python 语法检查通过；直线路径测试确认在线横向误差为 0、路径两侧误差符号相反、末段剩余距离正确；静态核对固件 `ProductWebService`、`MotionController`，确认 PROP 模式仅驱动 ESC 推进与转向，尾舵保持中心。
- 已知限制：固件现有 `/control` 动作接口只消费 `var`，不接收电脑计算的 `power/strength`；当前 PID 只能决定直行、左转、右转三种动作，固件按默认 100% 动作参数执行。摄像头与机器鱼未连接，未做实机闭环验证。
- 待确认事项：架空执行器验证 PROP 模式与左右转方向；入水后从低风险短轨迹确认路径横向误差符号和终点停止距离。

## 2026-08-14 PROP 左右转向力度增强

- 修改原因：用户确认将螺旋桨模式最大转向偏角从 12° 增加到 24°，增强左右转向力度。
- 最终决策：新增配置 `RF_PROP_TURN_MAX_OFFSET_DEG=24` 并由 `MotionController` 消费；PROP 满转目标由中位 90° 的 ±12° 扩大为 ±24°，视觉 PID 在现有 70% 限幅下最大约 ±17°。HYBRID 的 8°、推进油门、20 ms 控制周期、转向每周期 4° 的渐变速度及保护逻辑保持不变。
- 涉及文件：`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`RoboFishPartnerDriverSDK/src/control/MotionController.cpp`。
- 验证方式和结果：ESP-IDF 5.3.2 全量构建成功；应用镜像 934592 字节，SHA-256 为 `f712a9b0846a359fd0d93d67ea71d5492d131faca3ff334a6bae027649e085d3`，OTA 分区剩余 72%。满转目标 66°/114° 位于现有 40°～136° 软件限位内。
- 已知限制：尚未烧录并进行水中转向测试；编译和数值边界检查不能证明实际转向角速度与水动力效果。
- 待确认事项：首次测试应架空螺旋桨并确认左右极性，再在低油门短时入水测试中确认转弯半径、执行器机械余量和电流。

## 2026-08-14 双尾鳍相位抵消调整

- 修改原因：用户观察到前后尾鳍舵机动力抵消，确认按原模式比例降低相位差。
- 最终决策：BIONIC 后舵机相位滞后由 0.35 周期（126°）降至 0.16666667 周期（60°），HYBRID 由 0.42 周期（约151°）按相同比例降至 0.20 周期（72°），保留两模式相位差 1:1.2 的比例。频率、前后摆幅 1:0.9、转向偏置、渐变速度和保护逻辑不变；相位参数集中到 `sdk_config.h`。
- 涉及文件：`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`RoboFishPartnerDriverSDK/src/control/MotionController.cpp`。
- 验证方式和结果：静态计算确认相位分别为约 60°、72°，比例约 1.2；随后与网页 STOP 修改一并通过 ESP-IDF 5.3.2 全量构建，应用镜像 937072 字节，OTA 分区剩余 72%。
- 已知限制：尚未确认两只舵机安装方向是否一致，也未验证尾端实际合成幅度、推进效率、电流和机械干涉；静态计算不能替代实机水动力验证。
- 待确认事项：编译烧录前先低幅度单独驱动两只舵机确认物理正方向；之后架空低动力观察波形，再入水比较前进速度、偏航和电流。

## 2026-08-14 网页 STOP 可靠停止

- 修改原因：网页用本地 `lastAction` 对 STOP 去抖，页面状态与设备不一致或前次请求失败时会直接跳过停止；运动请求失败也没有可见反馈，鼠标移出按钮后松开可能漏发。
- 最终决策：中央 STOP 改为按下即发送且永不受本地状态、节流或去抖阻止；发送前取消尚未完成的前后左右请求，并在鼠标松开、触摸取消、窗口失焦、页面隐藏或离开时走同一停止路径。中央按钮仅在 HTTP 200 后提示成功，失败显示红色错误。后端 `servo_stop` 继续通过原目标值和 `slew` 渐变归中，同时取消视觉 PID、Demo、Partner 并关闭水泵，胸鳍角度不变；用户否决了执行器瞬时跳回中位的硬停止方案。
- 涉及文件：`reverse_analysis/web_assets/html_01_0x0000100b.html`、`RoboFishPartnerDriverSDK/src/control/MotionController.cpp`。
- 验证方式和结果：Node.js 解析嵌入脚本成功；ESP-IDF 5.3.2 全量构建成功并确认网页资源重新生成、参与链接。应用镜像 937072 字节，SHA-256 为 `169a0c701ca1f37545f114ce26907e69bf56863414a84127c1554e5a5fffb6fc`，OTA 分区剩余 72%。
- 已知限制：尚未在手机浏览器、实际 Wi-Fi 丢包和执行器上验证；取消浏览器请求不能撤销已经到达后端的旧命令，但随后独立 STOP 请求会覆盖设备状态。
- 待确认事项：实机验证页面刷新后直接按 STOP、断续网络、按钮外松手、切后台及重复 STOP；观察尾鳍、油门和转向是否按原渐变速度归中且水泵关闭。

## 2026-08-14 视觉侧分阶段优化计划

- 修改原因：用户要求把视觉优化计划写入 Markdown 并逐步实施；同时确认普通 YOLO 框无法可靠测量侧滑角，希望用 OpenCV 色块跟踪辅助抑制 YOLO 框中心突变。
- 最终决策：新增 `VISION/VISION_OPTIMIZATION_PLAN.md`。第一版只输出位置、速度和运动航向，不宣称鱼体艏向或侧滑角。普通YOLO框中心、自然轮廓质心和自然色块质心均不能保证相对鱼体固定；推荐在鱼体中央安装刚性专用色标，并把色标物理中心直接定义为控制参考点。采用 YOLO/BoT-SORT 做身份与搜索区域、OpenCV HSV/轮廓跟踪固定色标、常速度预测和质量门控的分层方案。无色标降级模式只能输出 `ESTIMATED`，不得用于最终PWM—速度精标定。实施顺序固定为参考点融合、时间戳/运动估计、初始航向输入、临时记录、一次性极性/PWM基准、纯PROP控制、STOP与线程整理。
- 涉及文件：`VISION/VISION_OPTIMIZATION_PLAN.md`、`process.md`。
- 验证方式和结果：计划明确每阶段输入、输出、验收条件和实机授权边界；本条只写文档，尚未修改视觉运行代码。
- 已知限制：即使使用刚性色标，单目平面映射仍受水深、侧翻、折射、反光和部分遮挡影响，不能承诺数学意义上的绝对不变；单色标与普通水平检测框不能区分鱼头/鱼尾，因此不能测量鱼体艏向和侧滑角。
- 待确认事项：阶段 1 实施前确认是否能在鱼体中央安装专用色标，并用真实画面确认色标面积、HSV稳定性、轮廓形状和水面反光影响；阶段 5 前完成低风险实机授权。

## 2026-08-15 白色刚性鱼身跟踪、弯道预判与 HYBRID 柔性制动

- 修改原因：橙色块固定在摆动鱼尾且无法移动，直接作为位置会把摆尾带入路径误差；现有固定前视、尾舵/螺旋桨共用动力及终点不发 STOP，造成转弯迟、半径大和终点超调。用户确认改用前部白色刚性鱼身，并要求防止小白点和反光误识别、分离动力、提高 HYBRID 桨动力及柔性反转制动。
- 最终决策：控制参考点按 `RIGID_BODY` 白色刚性鱼身优先、`MARKER` 橙色鱼尾兜底；白色无法锁定时允许先用橙色中心启动控制，但橙色数据包含摆尾干扰，不得用于最终 PWM—速度标定。白色候选经过绝对面积、相对尾标面积、相对 YOLO 面积、过曝比例、尾标距离和位置连续性门控；小白点、远处圆形反光和远处过曝反光拒绝，直接测量短时缺失只预测约 0.16 秒。真实日志证明盲搜门控过严后，现有“鱼头方向”点击同时用于初始化白色刚体位置与尾标—鱼身距离；点击附近的真实白色鱼身允许圆形或过曝，但远离该预测位置的亮斑不得接管。鱼尾 ROI 松键增加空起点保护，失败重试明确清除拖动状态；启动失败打印位置来源和具体门控。HTTP 控制显式使用短连接；HYBRID 模式确认遇到单次 `10054` 不再立即失败，而是以 120 ms 间隔最多尝试 5 次。路径引导加入 0.34 m 弯道预览、曲率前馈和 0.24～0.10 m 动态前视；直线看远、弯道看近并提前转向。`/vision_pid` 新增 `speed`、`curve`、`brake`，ACK 仍只保留序号和 ESC 执行量。视觉 HYBRID 独立使用尾舵动力 74%～92% 和按曲率限制的螺旋桨动力 100%～75%；HYBRID 桨正向增益由 44°提高到 52°，最大转向左/右为 26°/25°，尾舵转向偏置为 18°。尾舵在偏置中心两侧按机械余量对称限幅，禁止单侧波形削顶造成左右水动力不对称。终点制动采用非阻塞单枚举状态机 `Cruise -> Neutralizing -> NeutralDwell -> ReverseBrake -> Hold`：先按原渐变回中，确认中位 ±1° 后停留 160 ms，再以 26% 反向动力慢升油，至少 120 ms、最多 480 ms，速度低于 0.03 m/s 后回中；到达且低速后电脑实际发送 STOP。
- 涉及文件：`VISION/fixed_reference_tracker.py`、`VISION/path_guidance.py`、`VISION/yolo(PID).py`、`VISION/vision_toolbar.py`、`VISION/tests/test_fixed_reference_tracker.py`、`VISION/tests/test_path_guidance.py`、`VISION/VISION_OPTIMIZATION_PLAN.md`、`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`RoboFishPartnerDriverSDK/src/control/MotionController.h`、`RoboFishPartnerDriverSDK/src/control/MotionController.cpp`、`RoboFishPartnerDriverSDK/src/web/ProductWebService.cpp`。
- 验证方式和结果：Python 语法检查、41 项视觉离线测试和 `git diff --check` 通过；测试覆盖白色刚体锁定、鱼头点击种子接受近处圆形/过曝真实鱼身、拒绝更大但较远反光、短时预测、小白点/无种子圆形反光/无种子过曝反光拒绝、左右 90° 弯预判、动态前视和速度相关终点制动。ESP-IDF 5.3.2 全量编译链接成功，应用镜像 938560 字节，OTA 分区剩余 72%；最终时间命名镜像 `RoboFishPartnerDriverSDK-OTA-20260815-112130.bin`，SHA-256 为 `3347cccccb16ef026357fcb4deb053714e95cecffd79abea2b0a6bb2ed7c8f3e`。
- 已知限制：白色阈值与面积门限只用合成图和现有截图建立，尚未在实时水面反光、侧翻和不同深度下验收；编译通过不能证明反转电流、ESC 换向时序、真实制动距离和转弯半径安全。当前未发现串口，也未确认连接机器鱼 AP，因此本次未烧录。
- 待确认事项：实时画面先确认绿色控制框稳定锁在前部白色刚体而不是反光；架空低动力确认回中停留后才反转且左右极性正确，再入水短距离依次测直线动力、左右弯半径、反转电流峰值和终点停车距离。若白色刚体被过曝门控误拒绝，优先按真实轮廓面积与过曝比例调整阈值，不放宽位置突变门控。

## 2026-08-15 YOLO/橙色色块解耦与起步航向连续性

- 修改原因：实机日志反复在仍可使用橙色鱼尾时打印“YOLO 目标丢失”并取消轨迹；每次重新启动还会退回最初人工航向，并通过旧 `mode` 接口连续轮换 BIONIC、PROP、HYBRID，造成起步转向和执行器状态瞬变。
- 最终决策：YOLO 置信度最终降到 `0.18`，仅以 5 Hz 做全局身份确认和宽范围重捕；低频推理改用纯 `predict`，不再使用依赖连续帧的 BoT-SORT。HSV 橙色色块继续逐相机帧跟踪，本地搜索窗口由上次位置和速度预测产生，不再要求 `yolo_confirmed`；鱼尾透视/摆动允许更大的面积、长宽比、圆度和位置搜索变化，YOLO 丢失时仍允许直接色块测量和最多约 0.45 秒短时预测，只有两者都失效才取消轨迹并打印具体色标门控及 YOLO 结果年龄。重新启动优先沿用上一次可靠运动航向，人工鱼头方向仅作为首次/重新标定后的起始值；启动准备不再循环推进模式，只复位一次视觉序号，首个 `/vision_pid` 样本由固件原子进入 HYBRID。轨迹吸附按离轨距离动态把前视由 0.24 m 缩短到 0.10 m，同时最高把航向转向误差增益提高到 1.65 倍；下发固件的 `curve` 改为路径曲率、离轨程度和航向误差三者最大值，使严重离轨的直线段也会提高尾舵动力并降低直推桨力。终点制动一旦触发便锁存，进入 0.18 m 捕获区后不再因速度噪声退出；速度降至 0.08 m/s 或制动达到 1.8 秒即实际 STOP，禁止越过终点后满舵绕圈找点。
- 涉及文件：`VISION/yolo(PID).py`、`VISION/fixed_reference_tracker.py`、`VISION/tests/test_fixed_reference_tracker.py`、`VISION/VISION_OPTIMIZATION_PLAN.md`、`process.md`。
- 验证方式和结果：Python 语法检查通过，46 项视觉离线测试全部通过；测试覆盖 YOLO 保持期过后橙色色块继续直接跟踪、无 YOLO 时色块短时预测、离轨后缩短前视与增强吸附，以及高速越过或低速进入终点捕获区后都结束控制而不绕圈。`git diff --check` 通过。
- 已知限制：单个橙色鱼尾会摆动，只能近似位置和运动航向，无法观测真实鱼头瞬时朝向；0.45 秒预测和 5 Hz YOLO 频率仍需入水验证，不能在色块真实遮挡后无限闭环。
- 待确认事项：下一次实测观察 YOLO 框消失时绿色/黄色参考框是否继续移动，终端不应再因单独 YOLO 丢失取消；每次启动核对新增“起步使用人工鱼头方向/上次运动航向、首个引导左/右”提示与鱼实际动作是否一致。
## 2026-08-15 视觉轨迹控制逻辑简化

- 修改原因：上一版同时包含白色鱼身优先、动态前视、曲率前馈、离轨吸附、制动锁存和终点捕获，实机绕圈时难以判断是哪一层造成问题；用户要求先用最少逻辑跑通。
- 最终决策：运行时关闭白色鱼身识别，只以橙色鱼尾 `MARKER` 和短时 `PREDICTED` 作为控制位置；YOLO 保持 5 Hz 全局重捕，橙色色块逐帧跟踪。轨迹按 3 cm 等距插值；贴轨时前视 0.24 m，离轨距离达到 0.12 m 时线性缩短至 0.10 m，同一航向误差的转向增益线性提高至 1.65 倍。离轨比例同时进入下发固件的 `curve` 严重度，实现前视转向时同步降低直推。实机日志证明 MCU ACK 正常且满转已达到 ESC 64°/115°，响应慢来自旧航向估计而非执行器动力：旧算法用约 0.60 s 首尾位移、0.18 融合并拒绝超过 90° 的航向变化，导致急转时航向长期停留。现改为约 0.40 s 位置直线拟合、最短 0.12 s 建立和 0.45 航向融合，允许真实急转跨过 90°，只拒绝接近 180° 的瞬时反跳；同一拟合输出速度并拒绝超过 0.80 m/s 的不可能尖峰。终点仍只保留两个固定圈：0.35 m 内请求固件柔性反转制动，0.22 m 内电脑直接发送渐变 STOP。
- 验证方式和结果：`yolo(PID).py`、`fish_detector.py`、`fixed_reference_tracker.py`、`path_guidance.py` 语法检查通过；44 项视觉离线测试全部通过，覆盖 0.24～0.10 m 前视、1.00～1.65 倍吸附、短窗口速度拟合、速度尖峰拒绝、超过 90° 真实急转跟随、180° 跳变拒绝、左右符号、正后方稳定满转、单向进度、固定制动/停止距离、回环不提前停车、白色识别关闭、YOLO 与色块跟踪框架。
- 已知限制：橙色鱼尾会摆动，运动航向仍是位移估计，不是真实瞬时鱼头方向；本轮只修改电脑视觉侧，未重新编译或烧录单片机，必须通过下一次入水短轨迹验证 0.24/0.10/0.12/1.65、0.40 s 航向窗口和 0.35/0.22 m 数值。
- 相机门控调整：按用户实机反馈，删除主循环中“相机时间戳超过 0.5 s 未变化便进入 `CAMERA PAUSED` 并跳过视觉处理”的门控，始终处理采集线程持有的最新画面。坐标平滑、速度拟合和航向融合仍按真实帧时间戳去重，重复画面不会被当作新的运动样本。
- 相机延迟补偿：用户三张屏幕秒表照片分别显示约 0.26 s、0.53 s、0.13 s 延迟，实际采集仅约 10～20 FPS、单次读取约 30～110 ms。视觉配置写入 `CAMERA_LATENCY_S=0.30`，控制位置按拟合 `vx/vy` 向前预测 0.30 s，并以 0.12 m 限制最大补偿距离；原始测量位置仍保留在 JSON，另输出 `control_x/control_y/camera_latency_s`。Python 语法检查和 45 项视觉离线测试通过。
## 2026-08-15 独立摄像头延迟测试

- 新增 `VISION/camera_latency_test.py`，只按正式视觉程序相同的 `src=1` 外接 USB 摄像头、DirectShow、MJPG、640×480、60 FPS、曝光和增益配置打开画面；不导入 YOLO、不启动网络、不连接机器鱼。默认曝光统一为 `-6`（约 1/64 秒），避免 `-5` 的约 1/32 秒曝光把物理帧率限制在约 30 FPS。画面显示实际分辨率、平滑 FPS、单次 `read()` 用时、毫秒时钟和帧序号，关闭窗口或按 ESC/Q 退出。
- VS Code `launch.json` 增加 `VISION: 仅摄像头延迟测试`，可直接从运行选项启动。Python 语法检查、Launch JSON 解析和 `git diff --check` 通过。

## 2026-08-15 真实曲率前馈与网页 HYBRID 满转动力锚定

- 修改原因：最新实机日志显示大角度起步时视觉 X 已到 `-0.30 m`、ESC 已接近 HYBRID 最大舵角，但控制仍把螺旋桨降到20%、鱼尾降到60%，导致实际转向力不足；原算法的曲率只放大已经出现的航向误差，且只有离轨后才缩短前视，因此表现为先冲出轨迹再回拉。用户确认总转向拆为曲率预判、航向误差和离轨误差三项，并说明网页 HYBRID 满转圆直径约40 cm但不是精确测量。
- 最终决策：路径前方两段平滑弦线的有符号夹角除以实际测量跨度，输出单位为 `m⁻¹` 的真实曲率；以估计半径 `0.20 m` 仅建立第一版曲率前馈 `clip(κ×0.20, -1, 1)`，等待自动圆拟合替换。总转向为曲率前馈、鱼头相对轨迹切线的航向反馈、`atan2(带符号离轨距离, 当前前视)` 几何反馈三项之和，最终限幅 `±1`；前视在离轨前随曲率、离轨后随距离从0.24 m连续缩到0.10 m。总转向映射到视觉 X `±1/3 m`，配合 MCU `Kp=300 %/m` 对应 `±100%`，删除原 `0.45~1.90` 曲率增益、`1.50` 曲率减速放大和120°增益切换。固件按总转向需求把直线鱼尾74%/螺旋桨100%连续插值到网页 HYBRID 满转鱼尾75%/螺旋桨75%，不再降到60%/20%。柔性反转制动进入 Hold 后若尚未收到终点 STOP，则保留最新转向并以现有26%限流档低速重新接近；反转期间螺旋桨舵角保持中位，避免反推使转向符号倒置。
- 涉及文件：`VISION/path_guidance.py`、`VISION/yolo(PID).py`、`VISION/tests/test_path_guidance.py`、`VISION/VISION_OPTIMIZATION_PLAN.md`、`RoboFishPartnerDriverSDK/src/config/sdk_config.h`、`RoboFishPartnerDriverSDK/src/control/MotionController.cpp`、`process.md`。
- 验证方式和结果：`path_guidance.py`、`yolo(PID).py` 语法检查通过，58项视觉离线测试通过，覆盖真实曲率方向/单位、曲率提前缩短前视、三项转向独立求和、正后方稳定满转、`±0.333 m` 精确满量程及动力严重度等于实际总转向；`git diff --check` 通过。ESP-IDF 5.3.2 编译链接和分区检查通过，应用镜像938560字节，OTA分区剩余72%；生成 `RoboFishPartnerDriverSDK-OTA-20260815-170809.bin`，SHA-256 为 `e8a0bf711d26c3607cb8c8f8f287bcf8167b99101f7c5be5bc99f47097f347f4`。
- 已知限制：40 cm直径是用户目测，只能作为曲率映射初值；离线测试和编译不能证明实际左右转弯半径、动力—曲率线性关系、26%重新接近速度或反转电流安全。本次仅编译，未烧录。
- 待确认事项：重启视觉程序并烧录新固件后，先跑短路径观察新日志中的 `曲率=/m`、`转向=` 与 ACK 舵角；分别用网页 HYBRID 满左/满右稳定转圈并让视觉拟合半径，再补测至少一个中间转向比例，建立左右独立的实测曲率查表。首次验证反转制动后重新接近时应架空或低风险短距离进行，确认反转阶段舵角中位、Hold阶段低速向终点而不是反向偏航。

## 2026-08-15 HYBRID 左右满转半径视觉拟合

- 修改原因：网页 HYBRID 转圈直径约40 cm只是目测值，不能直接当成精确曲率映射；用户要求参数有实测或计算依据，并明确左右动力可能不一致。
- 最终决策：新增独立 `turn_calibration.py`，只被动采集视觉位置，不发送运动指令。底部中文【转圈测量】按钮按一次开始采样，用户在网页手动保持 HYBRID 满左或满右至少半圈，再按一次完成；仅橙色色块直接 `MARKER` 数据可进入拟合，预测和YOLO降级位置全部排除。圆拟合采用Huber迭代和MAD径向残差门控，至少25个有效点、至少180°圆弧、至少70%内点，并检查半径、RMS残差和单向旋转一致性。左右结果分别持久化到被Git忽略的 `VISION/turn_calibration.local.json`；正曲率使用左转实测半径，负曲率使用右转实测半径，未标定方向继续使用0.20 m估计值。一次满转测量只替换曲率前馈端点，不伪造中间转向比例的线性实测。
- 涉及文件：`.gitignore`、`VISION/turn_calibration.py`、`VISION/path_guidance.py`、`VISION/yolo(PID).py`、`VISION/vision_toolbar.py`、`VISION/tests/test_turn_calibration.py`、`VISION/tests/test_path_guidance.py`、`VISION/tests/test_vision_toolbar.py`、`VISION/VISION_OPTIMIZATION_PLAN.md`、`process.md`。
- 验证方式和结果：Python语法检查、65项视觉离线测试和 `git diff --check` 通过；测试覆盖左右方向符号、半径精度、鱼尾周期扰动、少量离群点、半圈门槛、重复帧去重、左右JSON合并保存、工具栏按钮命中以及路径控制使用左右独立半径。本轮未再修改固件，因此没有重新编译或烧录ESP32。
- 已知限制：橙色标记在摆动鱼尾，稳健圆拟合只能降低而不能消除参考点摆动误差；场地单应矩阵、水深、折射和侧翻也会改变尺度。满转端点不能证明40%～100%转向与曲率严格线性，后续仍应至少补测一个中间档位。
- 待确认事项：实机依次测满左和满右，尽量保持相同水深、油门和稳定圆周；终端应报告方向、直径、半径、曲率、有效点、圆弧与RMS残差。若自动判断方向与网页指令相反，先检查视觉坐标到鱼体左右极性，不要直接交换标定文件字段。

## 2026-08-27 Frenet/LOS 统一转向目标输出

- 修改原因：原路径引导把路径切线航向反馈和横向离轨反馈分别归一化、分别限幅后相加；大航向误差与回归路径方向相互抵消时会改变期望方向的真实几何关系。用户确认先保留现有控制结构，只重生成 PC 端目标值输出。
- 最终决策：保留最近点投影、单向进度、曲率预览、动态前视、HTTP `/vision_pid`、MCU P 映射、推进和终点制动逻辑。横向误差先在局部路径坐标系中通过 `atan2(e, lookahead)` 生成唯一 LOS 期望航向，再计算鱼的运动航向到该目标的统一误差；总转向只叠加曲率前馈和统一航向反馈。原横向反馈保留为诊断量，不再单独叠加。新增路径切线航向误差、LOS 角和期望航向向量诊断字段。
- 涉及文件：`VISION/navigation.py`、`tests/vision/test_path_guidance.py`、`process.md`。
- 验证方式和结果：Python 语法检查通过；路径引导、视觉控制会话和左右转圈标定共 39 项离线测试通过；新增测试证明切线误差 `+120°` 与 LOS 回归角 `-60°` 会先合成为统一 `+60°` 目标误差，再映射为 `2/3` 转向需求。完整视觉测试发现当前 Python 环境缺少 `cv2`，6 个依赖 OpenCV 的测试模块无法导入，未将其记为通过。
- 已知限制：尚未实机验证摆尾波动、相机延迟和水流下的轨迹效果；本次没有修改速度估计、无后退策略、推进控制或终点状态机，也没有重新编译或烧录 ESP32 固件。
- 待确认事项：左右执行器以及视觉误差到转向输出的极性沿用既有实机确认结论，本轮不再重复验证。应在相同路径、相近水况和动力条件下入水对比修改前后的横向 RMS、最大离轨、入弯响应时机、转向饱和时长、弯道超调与回轨收敛时间；根据轨迹性能结果，再决定是否继续做摆尾周期平均速度和无后退终点策略。

## 2026-08-28 视觉目录按技能边界重构

- 修改原因：用户要求拆除 `VISION/video/` 单一混合目录，并按 vision 与 embedded-firmware skill 明确实时视觉、训练数据、模型配置和设备固件边界。
- 最终决策：实时 Python 代码迁移到 `VISION/runtime/`；运行时模型使用 `VISION/models/best.pt`，历史候选权重放入 `VISION/models/candidates/`；本地标定迁移到 `VISION/configs/`；V15 数据集脚本和元数据迁移到 `VISION/training/fish_v15/`；原始视频和识别结果分别迁移到 `VISION/data/raw/`、`VISION/data/results/`。`RoboFishPartnerDriverSDK/` 保持独立，未修改 FreeRTOS 任务、Topic、协议、引脚或控制行为。
- 涉及文件：`VISION/runtime/config.py`、`VISION/runtime/*.py`、`VISION/models/`、`VISION/configs/`、`VISION/training/`、`VISION/data/`、`.vscode/launch.json`、`.gitignore`、`README.md`、`VISION/README.md`、`docs/VISION_ARCHITECTURE.md`、`tests/vision/*.py`。
- 验证方式和结果：检查 `VISION/video/` 已移除；运行时配置解析到 `VISION/models/best.pt` 且文件存在；当前 Ultralytics 环境成功加载模型，类别为 `{0: red_fish, 1: blue_fish}`；Python 语法检查、81 项视觉离线测试和 `git diff --check` 通过。
- 已知限制：保留了大体积原始视频和训练运行目录，但它们已按路径加入忽略规则；本次仅重排目录和路径，未在真实相机、机器鱼或 ESP32 硬件上验证。
- 待确认事项：后续运行应从 `VISION/runtime/` 执行 `python main.py`，并确认外置相机、机器鱼 HTTP 和标定配置在目标机器上可用。
