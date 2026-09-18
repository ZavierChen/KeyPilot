# 测试与复现指南

本指南覆盖三类功能的测试方法：Windows 助手的规则与受控操作、更换本地模型后的结构化路由、自定义语音包的导入与合成。自动测试验证接口和流程；模型理解准确率、语音质量与硬件延迟需要在实际运行环境中分别测量。

项目采用 AI 辅助开发：作者主导系统架构、运行逻辑、功能需求与迭代选择，大量代码由 AI 工具辅助实现。设计过程及失败后的修正见 [版本历史](VERSION_HISTORY.md)，依据见 [历史来源](HISTORY_SOURCES.md)。语音包仅在本地使用，源码发行包不包含声音资源。

先完成 [START_HERE](START_HERE.md) 的安装和环境检查。以下命令中的 `python` 指项目虚拟环境解释器；未激活环境时，在 Windows 将它替换成 `.\.venv\Scripts\python.exe`，无需修改系统 Python。首次演示使用文字输入，随后再测听写和语音输出，便于区分识别、推理、执行与播放的问题。无需作者电脑上的私有声音、云端账号或路径配置即可开始离线契约与规则实验。

## 1. 最小复现：无需模型、无需音色

从仓库根目录、项目 Python 环境运行：

```powershell
python scripts/keypilot.py doctor
python scripts/keypilot.py models contract --output outputs/model-contract.json
python -m pytest -q
```

保留环境检查结果、测试摘要和导出的契约。记录 Git 提交号（源码 ZIP 则记录文件名及 SHA-256）、Windows 版本、Python 版本。环境检查通过不等于可选云服务和外部模型已经可用。

然后运行 GUI：

```powershell
python scripts/keypilot.py gui
```

保持初始的自动联网问答关闭、复杂代理关闭、语音自动执行关闭、自动语音回复关闭。输入“打开计算器”，手动点击执行，观察计算器窗口与应用回执。此实验主要验证规则与 Windows 执行层，不能作为模型推理结果。

## 2. 模型可替换实验

按照 [本地模型门户](LOCAL_MODELS.md) 启动自己选择的推理服务并记录真实模型 ID，先只读探测。下面的 `ACTUAL_MODEL_ID` 必须替换，地址也应与本机服务一致：

```powershell
python scripts/keypilot.py models --protocol ollama --endpoint http://127.0.0.1:11434 models
python scripts/keypilot.py models --protocol ollama --endpoint http://127.0.0.1:11434 --model ACTUAL_MODEL_ID probe --text "音量调到百分之三十"
python scripts/keypilot.py models --protocol ollama --endpoint http://127.0.0.1:11434 --model ACTUAL_MODEL_ID probe --text "什么是机器学习"
python scripts/keypilot.py models --protocol ollama --endpoint http://127.0.0.1:11434 --model ACTUAL_MODEL_ID probe --text "删除下载文件夹"
```

第一条操作探测的期望是 `set_volume` 与数值 30；后两条在路由实验中的期望是有效未匹配。所有探测的 `execution` 都应为 `not_executed`，不会改变实际音量或删除文件。

换模型时固定测试输入、契约版本和 JSON 模式，只改变模型或服务配置；用 `openai-compatible` 对接另一种兼容服务。将 [模型转接 Skill](../skills/keypilot-model-adapter/SKILL.md) 交给从未接触项目的模型或编码助手，它可从契约与协议开始接入。这里的“可替换”指接口与参数可替换，不保证任意模型都能可靠遵循指令。

直接 `probe` 绕过 GUI 规则路由，适合评估模型本身。实际 GUI 的规则优先分流属于另一实验条件，不能把两者的准确率混在一起。

## 3. 无模型的动作校验实验

将以下每一行分别保存为一个 UTF-8 JSON 文件，通过 `python scripts/keypilot.py models validate-response --file <文件路径>` 校验：

| 样本 | 期望 |
| --- | --- |
| `{"matched":true,"skill_id":"set_volume","arguments":{"operation":"set","percent":30}}` | 有效；不执行 |
| `{"matched":false,"skill_id":"","arguments":{}}` | 有效未匹配；不执行 |
| `{"matched":true,"skill_id":"delete_files","arguments":{}}` | 拒绝未知 ID |
| `{"matched":true,"skill_id":"set_volume","arguments":{"operation":"set","percent":130}}` | 拒绝越界值 |
| `{"matched":true,"skill_id":"set_volume","arguments":{"operation":"set","percent":"30"}}` | 拒绝错误类型 |
| `{"matched":true,"skill_id":"set_volume","arguments":{"operation":"set"}}` | 拒绝缺少设置值 |
| `{"matched":true,"skill_id":"open_app","arguments":{"app":"calculator","command":"calc.exe"}}` | 拒绝额外参数 |

有效未匹配退出码为 0；无效响应退出码为 2。这个实验只证明客户端约束生效，不能证明模型不会给一个错误但合法的操作。

## 4. 语音包实验

使用 [自定义语音包规范](VOICE_PACKS.md) 中的模板、检查和导入入口。先验包结构、路径与所需模型，再在 GUI 选择导入音色试听。录音、训练权重、云端凭据不包含在公开项目中；没有这些资源时，记录“尚未完成音色实测”，继续使用默认系统声音或纯文字流程。

模型转接与声音包是两个独立扩展点：更换路由模型不要求训练音色，导入声音也不应改变模型操作权限。云端声音训练、在线合成和本地推理分别记录，避免把云端效果标成离线效果。

## 5. 可复现实验记录

每个实验至少保留以下字段。可建 CSV 或 JSONL；使用固定输入集合并保存失败结果。

| 字段 | 记录内容 |
| --- | --- |
| 版本 | 源码提交/ZIP 校验值、契约版本、测试日期 |
| 环境 | OS、Python、CPU/GPU、内存/显存、模型服务版本 |
| 模型 | 完整模型 ID、量化/权重版本（已知时）、协议、JSON 模式 |
| 条件 | CLI 直接路由 / GUI 规则优先、联网与复杂代理状态、冷/热启动 |
| 输入与期望 | 原始文本、预期 Skill 和参数，或预期未匹配 |
| 结果 | 原始输出、验证状态、实际 Skill/参数、是否真正执行、错误原因 |
| 时间 | 测量范围与起止点；模型请求时间和整段进程时间分开 |
| 语音 | 包 ID/版本、后端、文本、首音频时间、总时长、播放异常 |

建议先建立含明确命令、同义表达、信息不足、普通问答、多步骤与不支持操作的固定测试集，再重复运行。分别报告：合法 JSON 比例、Skill 选择准确率、参数准确率、应拒绝样本的正确未匹配率、服务失败数。有效却错误的动作要计入失败，不能只报告“验证通过率”。

CLI 进程总耗时包含 Python 启动、网络与模型加载；只测一次会混入冷启动影响。测延迟时明确计时范围，分别报告冷启动与预热后的多次结果，并给出样本数和中位数。语音模块已有指标的定义见对应文档；输入结束到首音频的端到端指标仍需单独埋点。

## 已知能力边界

- 仅 Windows 桌面控制经过设计；硬件亮度、麦克风、默认浏览器、应用安装情况会影响结果。
- 可复现默认配置关闭联网问答、复杂代理、自动语音操作和朗读；启用这些选项后需作为不同实验条件记录。
- 本地模型按有限目录提出一次操作，没有通用多步骤规划或任意电脑控制接口；注册动作和参数验证不是完整系统沙箱。
- Windows 听写与可选云服务可能访问网络。纯本地模型推理不能证明整个语音链路完全离线。
- 不附带作者的声音与训练数据，不复用作者凭据；个人语音结果无法仅凭公共源码逐字节复现。
- 准确率、推理速度和音色质量取决于模型、数据与运行设备，测试结果需附环境信息和实验记录。

实现细节与扩展位置见 [架构说明](ARCHITECTURE.md)。
