# EasyInput V2.0 鼓机与稳定节拍器

这是一个面向 EasyInput V2.0（固件板型别名 `v2`，PCB 丝印 `AI Keyboard V2.1`）的 ESP-IDF 固件。它以扬声器 I2S TX 的连续 48 kHz 样本流作为唯一节拍时间基准，在样本域内累计 96 PPQN；网页、旋钮、声音和 5 颗 WS2812 都消费同一份固件状态，但网页不参与计时。

## 已实现

- GPIO8 先锁存为低；GPIO9/10/12/13/14/15 先锁存安全低电平，GPIO11 保持浮空，再拉高 GPIO8。
- GPIO8 拉高成功后等待 50 ms，再初始化灯带和扬声器。50 ms 是本项目按需求采用的等待值，不是已证明的硬件最短稳定时间。
- 麦克风不初始化；其 BCLK/WS 保持低，DATA IN 保持 disabled/floating。
- 扬声器 I2S：BCLK/WS/DOUT=`GPIO14/13/15`，48 kHz、16-bit、立体声重复采样。节拍停止时仍连续发送静音，I2S 主时钟不会因为停止或网页断开而消失。
- 96 PPQN 使用整数相位累计，不按 RTOS tick 延时推拍；默认 120 BPM，可调 40–240 BPM。
- 第 1、5、9…拍为 1760 Hz 强拍；其余拍为 1120 Hz 普通拍，非发声区间输出静音。
- S1、S2、S4–S7 是当前启用的低有效独立鼓垫，4 ms 消抖；S3 因硬件故障暂不触发，原 S3 闭镲迁移到 S7。按键通过同一条连续 I2S 音频链直接触发板载 PCM，即使节拍器处于停止状态也能演奏。
- 网页同步显示当前六个实体按键与音色的映射；实体按钮或网页试听触发时，对应音色卡片会高亮反馈。
- 网页提供六轨、每轨 16 步的可编辑音序器。每步是 1/16 音符，固件每 24 个 PPQN tick 推进一步，并直接在 I2S 音频任务中触发音色，因此会跟随 40–240 BPM 的实时变化而不依赖浏览器计时。
- 128 声部非抢占混音允许多键和同键快速重触发自然叠加；新触发不会偷取或截断已经播放的声音。混音输出带 64-sample 尾部淡出和整数软限幅。
- 针对实板小扬声器的频响，S1 底鼓、S7 闭镲、S5 拍手和 S6 鼓边击使用独立 Q15 板级增益；S5 已下调约 4.5 dB，总混音仍经软限幅，避免数字硬削波。
- 编码器 A/B/按压=`GPIO17/16/18`：每格调 1 BPM，按压切换开始/停止，25 ms 按压消抖。
- 5 颗 WS2812 通过 GPIO12 显示 `0→1→2→3→4→3→2→1` 往返光点；事件来自 I2S 样本累计。
- ESP32-S3 原生 USB Serial/JTAG 提供网页控制通道，不再创建 Wi-Fi AP，也不需要电脑切换网络。
- 本地网页通过 Web Serial 发送 `STATE`、`TOGGLE`、`BPM <40-240>`，固件按行返回 JSON 状态；四方块显示 `0→1→2→3→2→1` 往返节拍。
- USB 未连接或网页关闭不会停止旋钮、扬声器、LED 或 I2S，硬件可完全独立工作。

冷启动后的默认状态是 **120 BPM、停止**，避免上电后扬声器突然发声；按一次旋钮开始。

## 板载鼓音色

六种音色来自 FreePats `SynthesizerPercussion-SFZ-20220718` 和固定版本的 Free Drum Samples，两个上游均声明为 CC0 1.0。仓库保存统一转换为 48 kHz、单声道、signed 16-bit little-endian 的板载 PCM，无运行时解码或重采样。

| 按键 | GPIO | 音色 | 原始样本 |
| --- | ---: | --- | --- |
| S1 | 2 | Kick | `vintage-kick-01.wav` |
| S2 | 47 | Snare | `Snare09.wav` |
| S7 | 7 | Closed Hi-Hat | `ch-lofi.wav` |
| S4 | 41 | Open Hi-Hat | `OpenHiHat02-01.wav` |
| S5 | 1 | Clap | `Clap01.wav` |
| S6 | 6 | Rimshot | `perc-rimshot.wav` |

来源 URL、归档 SHA-256、逐文件映射、转换命令和输出哈希记录在 `main/assets/drums/SOURCE.md`，CC0 法律文本与上游许可声明快照保存在同目录。六个 PCM 总计约 209 KiB，并随应用镜像一起烧录到 Flash。

## 构建

项目目标为 ESP-IDF `5.5.x`（依赖声明为 `>=5.5,<6.0`），LED 驱动固定为 `espressif/led_strip 3.0.3`。

```bash
. /path/to/esp-idf/export.sh
idf.py set-target esp32s3
idf.py build
```

烧录前让开发板保持开机，**短按并松开一次 BOOT** 进入下载模式；不要按住 BOOT 配合重新上电。确认本次出现的 ESP32-S3 端口后再执行：

```bash
idf.py -p /dev/cu.<本次识别到的端口> flash monitor
```

退出下载模式时关机一次，再正常开机；不要再次按 BOOT。仓库不硬编码串口名，也没有在未确认目标设备时自动烧录。

## USB 网页控制

开发板刷入本固件并正常开机后，用一根支持数据传输的 USB 线连接电脑。先关闭 `idf.py monitor`、串口终端等占用端口的程序，然后在项目根目录启动本地网页：

```bash
pnpm dev
```

用支持 Web Serial 的 Chromium 浏览器打开 `http://127.0.0.1:8765/`，点击右上角“连接设备”，在系统列表中选择 ESP32-S3 的 `USB JTAG/serial debug unit`（macOS 端口通常显示为 `/dev/cu.usbmodem...`）。连接成功后，网页的开始/停止和 BPM 按钮会直接控制开发板。

`127.0.0.1` 属于浏览器允许的本地安全上下文；首次选择串口必须由用户点击触发，这是 Web Serial 的权限要求。串口通常只能被一个程序独占，如果网页连接失败，请先关闭烧录监视器或其他串口工具。

USB 行协议如下：

```text
网页 -> 固件: STATE\n
固件 -> 网页: {"type":"state","protocolVersion":2,"capabilities":["pattern","trigger","sequencer"],...}\n
网页 -> 固件: TOGGLE\n
网页 -> 固件: BPM 120\n
网页 -> 固件: PATTERN 4369 4112 21845 0 0 32768\n
固件 -> 网页: {"type":"ack","command":"PATTERN"}\n
网页 -> 固件: TRIGGER 1\n         # 试听 S1
固件 -> 网页: {"type":"state","bpm":120,"running":true,"sequenceStep":0,"pattern":[4369,0,0,0,0,0],...}\n
```

协议 v2 的 `PATTERN` 会将六轨 16-bit 掩码作为一个音频任务命令原子更新；音频任务完成应用并发布新状态后，USB 才返回 ACK。固件仍接受旧 `MASK <track> <mask>` 作为兼容入口，但当前网页不再逐轨发送。网页只有在 `STATE` 声明 `pattern`、`trigger`、`sequencer` 能力后才启用相应控件，并在收到 `PATTERN` ACK 后标记同步完成。协议错误显示在音序器区域，不会被误判为 USB 断线。

## 本机确定性测试

计时核心和 PCM 混音器都是与 ESP-IDF 解耦的纯 C 组件，可以先在主机验证 120 BPM 精确样本间距、137 BPM 分数相位、96 PPQN 计数、四灯/五灯往返序列、停止重启，以及鼓声叠加、同音重复触发、128 声部容量、尾部淡出和软限幅：

```bash
sh host_tests/run_tests.sh
```

## 仍需真机确认

- `ENCODER_DIRECTION=1` 是否对应实物顺时针加速；如果方向相反，将 `main/board_pins.h` 中它改为 `-1`。
- 50 ms 上电等待是否覆盖当前实板/批次的 GPIO8 电源稳定时间；现有硬件资料没有 ready 信号或跨批次最短值。
- MAX98357A 当前装配的声道选择、实际响度，以及两种 click 音色是否合适。
- S1、S2、S4–S7 的实物响应、六种 PCM 的主观音量平衡，以及人手快速连击/多键齐按时是否存在可感知延迟、爆音或中断。
- WS2812 在电池/USB 两种供电下的数据高电平裕量和亮度。
- I2S 声音、LED 和 USB 网页事件之间的真机相位差；软件路径共享样本基准，但尚未用逻辑分析仪/示波器测量。

## 关键配置

板级 GPIO 和项目参数集中在 `main/board_pins.h`。GPIO8、GPIO12、S1–S8、音频、编码器与 USB 引脚来自 `easyinput-board-cy` 的板级合同；当前启用按键、BPM 范围、音色映射、消抖、多声部策略、灯效、USB 控制协议和编码器方向均是本项目策略，不回写为开发板默认事实。
