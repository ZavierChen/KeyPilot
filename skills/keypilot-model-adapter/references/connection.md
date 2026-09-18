# 连接与验证

本说明中的命令从已安装项目开发环境的仓库根目录运行。所有门户命令都不执行电脑动作；`models` 和 `probe` 会访问你指定的模型服务。

## 1. 确认服务，而不是猜模型名称

KeyPilot 接收两种服务协议。模型权重名称本身不决定兼容性：模型必须由提供相应 API 的推理服务运行。

| 协议 | 端点示例 | 用途 |
| --- | --- | --- |
| `ollama` | `http://127.0.0.1:11434` | Ollama 原生接口 |
| `openai-compatible` | `http://127.0.0.1:1234/v1` | 提供聊天补全与模型列表接口的本地服务 |

示例端口不是服务发现结果；使用服务实际显示的地址。CLI 选项以 `--help` 和本版本实现为准。

```powershell
python scripts/keypilot.py models --protocol ollama --endpoint http://127.0.0.1:11434 models
python scripts/keypilot.py models --protocol openai-compatible --endpoint http://127.0.0.1:1234/v1 models
```

将模型列表返回的真实 ID 填入 `--model`。服务无法列出模型时，使用其界面确认的已加载模型 ID，并将列表功能缺失记入验收记录。不要把本项目示例 ID 当作已安装权重。

## 2. 导出契约与只读路由探测

```powershell
python scripts/keypilot.py models contract --output outputs/model-contract.json
python scripts/keypilot.py models --protocol ollama --endpoint http://127.0.0.1:11434 --model ACTUAL_MODEL_ID probe --text "音量调到百分之三十"
python scripts/keypilot.py models --protocol openai-compatible --endpoint http://127.0.0.1:1234/v1 --model ACTUAL_MODEL_ID --json-mode schema probe --text "打开计算器"
```

将 `ACTUAL_MODEL_ID` 替换为第一步核实的值。JSON 模式的选择是显式的：`schema` 请求结构化输出，`json` 请求 JSON 对象，`prompt` 只在提示词中要求 JSON。若服务器不支持某种响应格式，记录错误并切换到其支持的模式重新探测；无论哪种模式，应用都校验返回内容。

有认证的服务使用 `--api-key-env` 指向一个已经设置的环境变量，例如 `--api-key-env KEYPILOT_LOCAL_API_KEY`。不要把密钥值写进命令行、共享截图或契约。该选项指的是环境变量的名称，不是密钥本身。

## 3. 独立验证目标模型的原始输出

将模型的三个字段 JSON 保存为 UTF-8 文件，例如 `outputs/route-response.json`：

```json
{"matched":true,"skill_id":"set_volume","arguments":{"operation":"set","percent":30}}
```

```powershell
python scripts/keypilot.py models validate-response --file outputs/route-response.json
```

这里传入原始路由对象，不能传完整 HTTP 响应、Markdown 代码围栏或 `probe` 命令的诊断包装对象。验证成功仅说明动作格式可接受，不说明 Windows 操作已执行，也不证明模型理解正确。

输出中的 `execution` 应为 `not_executed`。有效未匹配是 `valid=true, matched=false`，不是服务故障。非法动作返回 `valid=false` 或错误信息及退出码 2；正常验证与有效未匹配退出码为 0。

至少探测三种输入：明确的已支持操作、普通知识问答、未知或多步骤操作。后两者在**操作路由**模式中应返回 `matched=false`；应用另有独立聊天流程。

## 4. 写入应用门户并验收

在应用设置中的“本地模型门户”填入已验证的协议、端点、模型 ID 与 JSON 模式并保存。保持本次任务既有的联网与复杂代理设置；模型接入本身不需要启用它们。先输入“打开计算器”并由用户提交，检查实际窗口与应用回执；语音、网页问答和声音合成分别验收，不能用一次路由探测代表全部通过。

| 观察结果 | 下一步 |
| --- | --- |
| 连接被拒绝或超时 | 核实服务已启动、地址/端口及模型加载状态；不要启动未知可执行文件 |
| HTTP 404 或模型不存在 | 对照模型列表检查 ID 与端点路径 |
| `response_format` 等参数不支持 | 显式选择服务支持的 JSON 模式 |
| 返回解释文字或非法 JSON | 检查模型支持情况及输出模式，保留失败样本 |
| 返回未知 Skill、越界值或额外字段 | 验证必须拒绝；修正模型输出，不修改限制来迁就它 |
| 验证通过但应用没有动作 | 检查规则/聊天分流、用户提交和 Windows 执行回执；不要宣称探测已执行 |

无需安装此 Skill 也能接入普通模型：读取 [动作协议与提示词](action-contract.md)，将提示词和导出的当前契约提供给它。具备 Skill 发现机制的编码助手可以安装整个 `keypilot-model-adapter` 文件夹，仍需单独指出项目所在目录。
