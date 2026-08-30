# EasyInput 鼓点盲听 Pilot

这是一个独立、离线的单人盲听页面。默认读取原始 `audition-cases.json`，不会访问模型 API、不会自动上传评分，也不会改写正式实验结果。

## 启动

在仓库根目录运行：

```bash
python3 -m http.server 8766 --directory eval/audition
```

然后用桌面版 Chrome 或 Edge 打开：

- `http://127.0.0.1:8766/`：原始 `blind-v1` Pilot，行为和旧入口一致；
- `http://127.0.0.1:8766/?dataset=blind-v2`：显式加载 `audition-cases-blind-v2.json`，用于整套音色替换与增益重平衡后的 post-hoc 复测。`?dataset=v2` 仅作为兼容别名。

页面顶部也提供两个明确入口。Web Serial 需要 localhost 或 HTTPS，不能双击 `index.html` 直接运行。未知的 `dataset` 参数会直接报错，不会静默回退到另一套数据。

`blind-v2` 是整套音色替换与增益重平衡后的 post-hoc 复测，不是闭镲单变量实验，也不是预注册实验的新主结果。页面从公开数据的 `condition` / `retestDesign` 读取并展示复测定义，导出的 JSON 也保留这些元信息；其结果必须与 `blind-v1` 分开报告，不能替代原 Pilot。

## 单人 Pilot 流程

1. 用 USB 连接已经烧录 protocol v2 固件的开发板，点击“连接 USB 设备”。连接本身不会发送 `STATE`、`BPM` 或 `PATTERN`。
2. 点击“播放”。页面这时才检查 protocol v2，必要时停止上一段，再依次设置 BPM、六轨 Pattern 并启动。
3. 可点击“重听”重新从当前 Pattern 开始，点击“停止”结束播放。
4. 对风格辨识度、律动自然度、直接应用意愿分别打 1–5 分。停止后再进入上一条或下一条。
5. 12 条全部评分后复制或下载 JSON。页面也会展示完整只读 JSON，避免浏览器拦截下载后无法取回结果。结果仍然只有盲样 ID，不含模型身份。
6. 点击“断开并清空”。页面会尽力停止设备、写入空 Pattern，再释放串口。

关闭或离开页面时也会发起一次尽力清理，但浏览器不保证异步串口写入一定完成。正式 Pilot 请优先点击“断开并清空”；意外拔线时页面无法清理板上状态。

这是单人 Pilot，不应被描述为多人用户研究或具有统计显著性的结论。

## 本机暂存与导出

- 每次评分、切换盲样和试听计数都会写入当前页面自己的 namespaced `localStorage` 键；刷新后会恢复进度。
- 键包含数据集 ID 和顺序指纹，因此 `blind-v1` 与 `blind-v2` 不共享评分，也不会因相同盲样 ID 串数据。
- 页面只读写 EasyInput 盲听页自己的进度键，不读取其他站点或其他用途的浏览器数据。
- 暂存和导出均只发生在本机；代码没有上传端点。完成后可使用“复制 JSON”、“下载评分 JSON”或直接手工复制页面中的只读 JSON。
- 下载链接会短暂保留后再释放，降低浏览器尚未接管 Blob 就被撤销的风险。即使下载仍被浏览器阻止，复制和可见 JSON 仍可用。

## 盲化边界

- 公共文件 `audition-cases.json` 和 `audition-cases-blind-v2.json` 各自固定为 12 条匿名样本，只含盲样 ID、任务提示、BPM 和六轨掩码。
- 使用正式实验的首答 `firstPassPatternMasks`，未使用修复输出。
- 顺序由固定私有种子经 SHA-256 排序得到；公开文件保存顺序指纹以便核验。
- 真值映射只存在于 `private/model-mapping.json`（blind-v1）和 `private/model-mapping-blind-v2.json`（blind-v2）。`private/.gitignore` 会忽略两份文件，不应在对应 Pilot 结束前展示给评分者或提交到 Git。

## 本地检查

```bash
node --check eval/audition/app.js
node eval/audition/tests/static-check.mjs
```

静态检查验证 v1（以及文件存在时的 v2）各自包含 12 条匿名样本、掩码范围、固定顺序指纹、公共 JSON 无模型身份、页面无外链依赖、v1/v2 入口与暂存键分离，以及私有映射确实被 Git 忽略。Web Serial 的最终验收仍需连接实机完成。
