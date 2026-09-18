# KeyPilot（Copilot 键助手）

把 Windows 键盘上的 Copilot 键变成一个可扩展的个人助手入口。

当前按键 MVP 不依赖 PowerToys 或 AutoHotkey：

- 单击 Copilot 键：打开 KeyPilot；窗口已经在前台时将它最小化
- 双击 Copilot 键：开始 Windows 听写；听写中再次双击则取消
- 长按 Copilot 键：不拦截额外动作，保留这台电脑原有的 Ctrl 行为
- 配置文件可把任一手势改成启动其他应用或发送其他快捷键

## 独立本地助手应用（测试版）

现在可以先测试助手本身，不绑定 Copilot 键。双击 [run-assistant.cmd](run-assistant.cmd) 打开图形应用。

测试版支持：

- 中文文字命令，以及通过 Windows `Win+H` 中文听写输入
- 打开 ChatGPT、计算器、记事本和开始菜单中可发现的应用
- 查询、设置、增减和静音系统主音量
- 查询和设置笔记本内置屏幕亮度
- 直接打开常用 Windows 设置页面；未知设置自动填写设置搜索框
- 可选晓晓、晓伊、云希、云健等联网自然声音，也可通过 Windows OneCore 使用本机实际安装的慧慧、瑶瑶、康康离线声音
- 听写停顿后，只有标记为低风险且无需确认的本地 Skill 才会直接执行
- 快速规则无法理解口语时，使用本机 Ollama `qwen3:8b` 选择 Skill 并填写参数
- Ollama 托盘程序可以关闭；KeyPilot 在需要本地模型而服务未运行时会静默启动 `ollama serve`。模型文件本身仍须已安装
- 稳定的普通和中等复杂询问尽量由本机 Qwen 直接回答；只在高风险或明显不可靠时询问是否使用 GPT
- 复杂操作才使用只读、临时、结构化 Codex 兜底
- “今天天气”等实时问题优先使用免 API Key 的天气 Skill，不让离线模型猜测
- “打开 YouTube/B站/GitHub”等常用网站直接使用默认浏览器；明确网址只允许 `http/https`
- 找不到本地应用时先询问是否使用 Google 搜索；确认后通过默认浏览器直接搜索，不再经由资源管理器
- 主界面内置可视化时钟助手，可设置倒计时、闹钟、提醒、世界时间并管理等待中的项目
- 闹铃提供晨光、数字、柔和三种旋律；到点后持续循环，直到关闭提醒窗口
- “需要时读取 Google”默认开启：普通问题先由本地 Qwen 思考；只有实时资料或本地确实无法回答时，才读取 Google 已渲染结果和可用的 Gemini AI 概览
- KeyPilot 发起的搜索默认使用 Google AI 模式，并在系统默认浏览器的无痕/InPrivate 窗口打开；直接打开网站和网址仍使用普通浏览器窗口
- “知识问答智能强度”滑条提供三级策略：0 关闭联网、1 本地不足时搜索、2 所有未命中操作 Skill 的内容都优先读取 Google AI（默认，包括仅说出人名或主题）。二级直接提取并朗读 Google AI 页面原文，Qwen 只负责意图路由，读取失败也不会回退成 Qwen 知识回答
- 二级语音回复只读取 Google AI 的第一段简短介绍，通常控制在约 150–450 个字符；编号详解和长正文留在浏览器中，不进行全文朗读
- 语音听写和手动执行现在使用同一套二级路由；Qwen 只选择 Skill，知识问答统一进入 Google AI
- Qwen 8B 改为按需加载并在闲置约 45 秒后自动卸载；二级模式下明确的知识问题会直接进入 Google AI，避免无意义地加载数 GB 模型
- 新增第 3 级“Marvis”：知识问答会唤起腾讯 Marvis，并由专用转接器自动粘贴发送；不读取或保存 Marvis 登录凭据
- 第 4 级“云端 API”：可在界面填写 OpenAI 兼容 API 地址、模型名称和 API Key；Key 使用 Windows DPAPI 按当前账户加密保存，知识问答走云端模型，电脑操作仍优先走本地 Skill
- 复杂操作代理可独立选择 Codex、Marvis 或关闭，与知识问答等级互不影响
- 主界面采用精简对话布局；智能等级、代理、语音、Qwen、API 和关键词管理集中在右上角“设置”弹窗
- 主界面新增云端模型二级下拉菜单，可直接切换 DeepSeek Flash、Pro、Vision 实验模型，也可输入任意兼容模型名称；选择后立即保存
- 为识别应用或文件别名而临时打开的搜索标签页会在读取完成后自动关闭；普通问答搜索和用户主动搜索会继续保留窗口
- “打开”会同时读取 Windows 应用清单和桌面顶层的应用、文件、文件夹及快捷方式，并容忍少量听写错字；仍未命中时，有网先查名称映射再由 Qwen 从本机候选中选择（如“黎明杀机”→ Dead by Daylight），断网时由 Qwen 自己推断
- 可以说“总结当前网页”或“浏览器页面讲了什么”，只读取当前浏览器已渲染文本；密码、验证码、密钥、银行卡等敏感问题不会自动搜索
- GPT 转交由独立的“GPT 转接器”子应用完成，可等待输入框、验证粘贴、自动发送，并在失败时保留问题供重新发送
- 新语音回复会立即终止旧播放进程并清空等待队列；打开麦克风时也会强制终止当前播报
- 本地问答保留当天最近 4 轮、最多约 2400 个字符的滚动上下文，用于理解“它、刚才那个、再详细一点”等追问；结果区可随时清除上下文
- 无法直接修改的 Windows 设置会等待“设置”窗口加载，前置窗口并自动填写“查找设置”；填写后会复制回读校验，避免只打开空搜索框
- 设置搜索兼容首次启动的 `SystemSettings` 窗口和后续由 `ApplicationFrameHost` 托管的窗口，可连续执行不同查询
- 窗口顶部的“关键词管理”提供网站与应用/文件两类持久化映射；每一项都能直接编辑、保存或点 × 删除，应用/文件目标可填写完整系统路径
- 世界时间完全离线；倒计时、闹钟和本地提醒由开机常驻后台持久处理，到点发声并弹窗
- “在日历添加……”会生成带提醒的标准日历事件，并打开日历让用户确认导入

常用测试命令：

```text
打开计算器
音量调到百分之三十
当前音量是多少
屏幕调亮一点
打开蓝牙设置
在设置里找颜色管理
```

语音识别第一版暂时调用 Windows 自带听写，因此点击“听写”或双击 Copilot 键后会出现系统听写面板。每段回复使用独立的可终止播放进程；新回复、开始听写、实际打开麦克风以及识别到第一个字时都会结束当前播报并清空待播内容。启动前会先关闭残留听写面板，最初 1.2 秒内还会屏蔽重复切换，避免面板闪现后立刻消失。需要确认 GPT 或浏览器搜索时，提示结束后会自动再次打开听写。联网自然声音使用项目内置的 `edge-tts`，不需要 API Key；断网或服务失败时会自动退回慧慧。后续确认交互方式后，再替换为常驻的 Vosk 或 sherpa-onnx 中文离线识别。

上下文记忆只保存当天最近 4 轮问答，单条最多 600 个字符、总输入最多约 2400 个字符，文件位于 `%LOCALAPPDATA%\KeyPilot\conversation-memory.json`。该限制可以支持自然追问，同时避免 qwen3:8b 的上下文长度和内存持续增长；点击结果区的“清除上下文”可立即删除。

本地理解层通过 `http://127.0.0.1:11434` 调用 Ollama，不需要 API Key，也不会把控制命令上传到云端。处理电脑控制请求时，Qwen 只能返回已注册 Skill 的 ID 和 JSON 参数；程序会再次检查白名单、类型、枚举、数值范围与风险级别，模型不能生成或执行 shell 命令。普通问答使用独立的本地回答模式。常见明确命令仍优先走毫秒级规则，不会每次都加载模型。

普通问答同样优先使用本机 Qwen。Qwen 会提高本地回答的容忍度，在存在少量不确定性时说明限制并给出有用答案；只有高风险或很可能误导的问题才询问“请问需要用 GPT 回答吗？”。确认提示会自动续听。实时天气使用 `wttr.in` 的无密钥接口；未指定城市时会根据公网 IP 推测城市，因此位置可能存在偏差。

联网回答不调用付费搜索 API。KeyPilot 会在默认浏览器中打开 Google 查询，并复制当前已渲染页面文本；如果页面包含 Gemini AI Overview，会优先提取对应区域。网页文本始终被当作不可信资料，只用于回答，不允许其中的指令触发电脑操作。Google 页面结构或账号地区差异可能导致 AI Overview 不出现，此时会使用普通搜索结果或退回本地 Qwen。

转交 ChatGPT 或 Codex 前，KeyPilot 会先把完整请求写入 Windows 剪贴板。ChatGPT 每天第一次转交时新建一次聊天，之后复用当天聊天；独立 GPT 转接器会定位输入框、粘贴后重新复制校验，确认内容一致才按 Enter。失败的请求保存在 `%LOCALAPPDATA%\KeyPilot\chat-handoff.json`，可从门户打开“GPT 转接器”重新发送。Codex 每天保存一个 session ID，后续请求通过 `codex exec resume` 继续该会话。每日状态保存在 `%LOCALAPPDATA%\KeyPilot\handoff-state.json`，应用更新不会清除它。

## 安装为桌面应用并接管 Copilot 键

运行：

```powershell
./scripts/install-app.ps1
```

安装程序会把稳定副本放到 `%LOCALAPPDATA%\Programs\KeyPilot`，在桌面创建唯一的 `KeyPilot` 图标，并注册登录启动的后台按键接管任务。后台任务没有第二个图标，也不会在开机时弹出窗口。

- 单击 Copilot 键：打开/恢复 KeyPilot；窗口已经在前台时最小化
- 双击 Copilot 键：打开 KeyPilot 并立即听写；听写中再次双击则取消
- KeyPilot 窗口顶部仍可把本地助手、ChatGPT 语音或 ChatGPT 窗口作为快捷入口打开

为区分单击与双击，单击动作会在 280 毫秒的双击判断窗口结束后执行。

> Copilot 键在多数 Windows 11 设备上表现为 `Win + Shift + F23`。KeyPilot 会拦截这个组合，避免原来的搜索动作同时弹出。

## 可选：配置 ChatGPT 语音快捷键

1. 打开 ChatGPT 桌面应用。
2. 进入 `设置 → 语音 → 语音聊天快捷键`。
3. 把快捷键设为 `Ctrl + F12`。语音快捷键输入框只接受 `Ctrl + 另一个键` 或 `Alt + 另一个键`，不能使用 `Ctrl + Alt + V`。
4. 这个快捷键只供窗口内的“ChatGPT 语音”快捷入口使用；Copilot 键双击听写不依赖它。

如果窗口提示 `hook installed`，说明按键监听已启动。按 `Ctrl + C` 可退出调试模式。

## 常驻运行（推荐）

如果 KeyPilot 是从 ChatGPT/Codex 的终端启动，退出 ChatGPT 时子进程也可能被宿主清理。使用 Windows 计划任务安装后，KeyPilot 由 Windows 登录会话启动，不依赖 ChatGPT 是否正在运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
./scripts/install-resident.ps1
```

卸载常驻任务：

```powershell
./scripts/uninstall-resident.ps1
```

KeyPilot 图形应用未启动时，单击会启动应用，双击会启动应用并在窗口就绪后自动打开听写。后台按键监听由 Windows 计划任务独立常驻，不依赖 ChatGPT 或 Codex 是否运行。

## 临时后台运行

双击 [run.cmd](run.cmd)。它使用 `pythonw.exe` 静默运行，不显示终端窗口。

如需开机启动，在 PowerShell 中运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
./scripts/install-startup.ps1
```

卸载开机启动：

```powershell
./scripts/uninstall-startup.ps1
```

## 自定义应用和动作

编辑 [config.json](config.json)。支持三类动作：

```json
{
  "type": "open_packaged_app",
  "app_id": "OpenAI.Codex_2p2nqsd0c76g0!App"
}
```

```json
{
  "type": "command",
  "program": "notepad.exe",
  "args": []
}
```

```json
{
  "type": "hotkey",
  "keys": ["ctrl", "f12"]
}
```

`tap`、`double_tap` 和 `hold` 可以分别配置；动作修改会自动生效。只有触发键或手势时间修改后需要重新运行 `run.cmd`。

## 为什么 Windows 设置里选不到 ChatGPT

Windows 原生“自定义 Copilot 键”只显示符合其资格条件的签名 MSIX 应用。即使某个程序已经打包，是否出现在列表中仍由 Windows 的筛选和应用清单决定；普通 `.exe`、快捷方式不能直接添加。KeyPilot 绕过这个受限列表，直接处理硬件键发出的热键。

## 项目结构

```text
keypilot/
  assistant_app.py 图形化本地助手测试应用
  assistant_router.py 中文命令与 Skill 路由
  windows_control.py 音量、亮度、应用和设置控制
  speech.py        Windows 本地语音回复
  codex_bridge.py  只读、结构化 Codex 兜底
  actions.py       启动应用、运行命令、发送快捷键
  config.py        配置加载和校验
  gestures.py      单击、双击、长按状态机
  windows_hook.py  Windows 全局低级键盘钩子
  main.py          程序入口和单实例保护
skills/
  open_app/        长期语音助手的示例 skill
  set_volume/      长期语音助手的示例 skill
docs/
  ARCHITECTURE.md   长期架构、安全边界和路线图
  HARDWARE_PLAN.md  针对当前电脑的本地模型方案
run.cmd             双击后台启动
run-debug.cmd       双击启动调试模式
```

## 测试

```powershell
python -m unittest discover -s tests -v
```

## 已知限制

- 不同厂商可能对 Copilot 键使用不同固件映射。如果日志收不到事件，先用 PowerToys Keyboard Manager 查看实际组合。
- ChatGPT 语音快捷键需要在应用中手动设置一次；KeyPilot 不修改 ChatGPT 的内部配置。
- 当前 MVP 没有托盘图标和图形设置页。结束后台进程可运行 `scripts/stop.ps1`。
- 当前语音识别仍依赖 Windows 听写；本地语言理解已接入 Ollama `qwen3:8b`。

## 隐私与安全

当前 MVP 不录音、不联网、不采集按键内容；它只检查目标触发键是否为 Copilot 键组合。配置中的 `command` 动作能够启动本地程序，因此只应使用你自己信任的配置文件。
