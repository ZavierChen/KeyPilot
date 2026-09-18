# 本地模型门户与陌生模型接入

[返回项目入口](START_HERE.md) · [模型操作 Skill](../skills/keypilot-model-adapter/SKILL.md)

KeyPilot 把「理解命令」与「执行 Windows 操作」分开。模型只返回一个 Skill 提议；应用检查真实 Skill 白名单、参数名称、类型、枚举和范围之后，再交给已有执行器。模型无需知道 Python 源码，也不需要获得终端权限。

## 软件中的入口

在仓库根目录运行 `.\.venv\Scripts\python.exe scripts/keypilot.py gui`，在主窗口点击 **本地模型门户**；设置窗口也有同名入口。

1. 启动自己的模型服务，在该服务内下载/加载一个能遵循 JSON 指令的模型。
2. 选择协议，填写地址。点击 **连接并发现模型**，选取实际返回的模型 ID；也可手填。
3. 输入「把音量设置为 50%」，点击 **只读路由测试**。正确结果含 `valid: true`、`skill_id: set_volume`、`percent: 50` 和 `execution: not_executed`，不会改变音量。
4. 点击 **保存并启用**。日常界面会使用所选模型做意图补充和本地问答。已有规则可以直接识别的命令仍优先走规则。
5. **预览契约 / 导出契约** 可以把当前技能目录、输入 schema 和示例交给一个新模型。**项目与接入** 可直接阅读本项目说明。

项目不强制使用某个模型，也不会自动下载权重、安装服务或更改已有 Ollama 服务。未选择模型时，确定性规则仍可使用；模型调用会提示先配置。

## 支持的协议

| 协议 | 地址示例 | 发现模型 | 对话请求 | 回包文本位置 |
| --- | --- | --- | --- | --- |
| `ollama` | `http://127.0.0.1:11434` | `GET /api/tags` | `POST /api/chat` | `message.content` |
| `openai-compatible` | `http://127.0.0.1:1234/v1` | `GET /v1/models` | `POST /v1/chat/completions` | `choices[0].message.content` |

Ollama 的聊天 API 支持 `format` 为 JSON 或 JSON Schema；本适配器使用非流式请求。[Ollama 官方接口文档](https://docs.ollama.com/api/chat)

LM Studio 提供上述兼容模型列表和 Chat Completions 路径；1234 是其文档中的示例端口，实际地址以你的服务设置为准。[LM Studio 官方兼容接口文档](https://lmstudio.ai/docs/developer/openai-compat)

其他服务只要实现表中的请求/回包形状，也可以接入。接口兼容性与模型能否稳定输出正确 Skill 是两项独立要求，应当分别验证。只实现 Responses API、流式接口、`tool_calls` 而不返回 `message.content` 的服务，需要在服务侧添加适配。

### JSON 模式

| 模式 | Ollama 发送字段 | 兼容协议发送字段 | 适用情况 |
| --- | --- | --- | --- |
| `schema` | `format: {...schema}` | `response_format.type: json_schema` | 服务支持结构化输出时首选 |
| `json` | `format: "json"` | `response_format.type: json_object` | 只支持 JSON 对象的服务 |
| `prompt` | 不发送 `format` | 不发送 `response_format` | 仅靠系统提示词遵守 JSON 的服务 |

三种模式都把 schema 放入提示词，并使用相同的应用端校验。服务不支持 schema 时，手动切换 `json` 或 `prompt` 后重测。不要把模型返回的自然语言或代码当作命令执行。

## 可复制的终端入口

从仓库根目录运行，先按 [README](../README.md) 创建 `.venv` 并完成环境安装。下面显式使用项目虚拟环境的解释器，无需激活 Shell；所有模型门户命令都不执行 Windows 操作。

```powershell
# 离线导出当前版本的技能契约
.\.venv\Scripts\python.exe scripts/keypilot.py models contract --output artifacts/model-contract.json

# 连接 Ollama，查看真实模型 ID
.\.venv\Scripts\python.exe scripts/keypilot.py models --protocol ollama --endpoint http://127.0.0.1:11434 models

# 将 actual-model-id 换成上一条返回的模型 ID
.\.venv\Scripts\python.exe scripts/keypilot.py models --protocol ollama --model actual-model-id probe --text "把音量设置为 50%"

# 兼容 API 的本地服务
.\.venv\Scripts\python.exe scripts/keypilot.py models --protocol openai-compatible --endpoint http://127.0.0.1:1234/v1 models
.\.venv\Scripts\python.exe scripts/keypilot.py models --protocol openai-compatible --endpoint http://127.0.0.1:1234/v1 --model actual-model-id --json-mode prompt probe --text "打开计算器"

# 校验另一个模型产生的文件；不连接模型服务，也不执行操作
.\.venv\Scripts\python.exe scripts/keypilot.py models validate-response --file examples/model-response.valid.json
```

全局选项必须放在子命令 `contract/models/probe/validate-response` 前。CLI 每次使用显式参数和自身默认值，不读取或覆盖 GUI 中已保存的配置。统一启动器会自动找到仓库内的 `desktop/keypilot`，无需安装 desktop 包或手动设置 PYTHONPATH。

退出码 `0` 表示完成或有效的「未匹配」；`2` 表示连接/配置/文件/JSON 错误，或提议未通过校验。仅 `valid: true` 且 `matched: true` 表示拿到了合规的动作提议，不表示动作已完成。

## 给一个陌生模型的最小输入

把导出的 `model-contract.json` 作为系统侧操作约定，再提供用户当次的原话；同时可给它 [KeyPilot 模型操作转接 Skill](../skills/keypilot-model-adapter/SKILL.md)。它只需输出：

```json
{"matched":true,"skill_id":"set_volume","arguments":{"operation":"set","percent":50}}
```

无法用单个现有 Skill 满足请求时，输出：

```json
{"matched":false,"skill_id":"","arguments":{}}
```

不允许额外顶层字段、Markdown 围栏、尾随说明、未知 Skill、缺失必填参数或参数越界。布尔值不能充当整数。`set_volume` 和 `set_brightness` 的 `operation: set` 还必须给出 `percent`。`codex_fallback` 是应用自己的后备路径，不在模型可调用契约内。

`validate-response` 只用于离线联调。正式接入方式是在 GUI 连接模型 API，让应用接收并验证提议；本版本没有接受外部 JSON 后直接执行的 HTTP 服务器、远程 Shell 或任意代码执行入口。

## 配置和认证

GUI 在研究版独立数据目录中的 `assistant-settings.json` 保存以下对象：

```json
{
  "local_model": {
    "protocol": "openai-compatible",
    "endpoint": "http://127.0.0.1:1234/v1",
    "model": "actual-model-id",
    "json_mode": "schema",
    "timeout_seconds": 60,
    "api_key_env": ""
  }
}
```

默认数据目录是 `%LOCALAPPDATA%/KeyPilot-Repro`，也可通过绝对路径环境变量 `KEYPILOT_DATA_DIR` 指定。URL 不接受嵌入的用户名/密码、查询参数或片段。只填主机地址时，兼容协议会自动补 `/v1`；自定义代理前缀请明确填写完整 API 基址。

如果服务需要认证，在启动 KeyPilot 的环境中设置一个自己的环境变量，并在门户 `API Key 环境变量名` 输入其名称，例如 `KEYPILOT_LOCAL_API_KEY`。应用发送 `Authorization: Bearer ...`，配置只保存变量名。CLI 对应 `--api-key-env KEYPILOT_LOCAL_API_KEY`。无需认证时留空。对话内容会发送到你填写的服务地址；完全离线使用时选择本机地址及本地权重。

## 验证与边界

`desktop/tests/test_local_model.py` 用回环 HTTP 测试服务器验证两种协议的发现、路由和三种 JSON 模式；同时覆盖非法字段、类型、范围、回包格式与 CLI 退出码。这些测试无需模型，也不改变系统音量。真实模型的延迟、语言理解质量和 schema 支持程度仍需在目标机器使用「只读路由测试」确认。

操作契约版本目前为 `1.0`。增加功能应先在源码中增加明确的执行分支及 `desktop/skills/<id>/skill.json`，再更新测试与契约；单纯让模型编写 Skill 名称或返回代码不会增加执行权限。

排错顺序：连接错误先检查服务是否启动与端口；HTTP 404 检查模型 ID/API 前缀；HTTP 400 检查 JSON 模式；超时可提高 1–600 秒的设置；`valid: false` 查看 `reason`，按契约修改模型输出。推理模型应配置服务侧的思考预算，确保内容字段中实际包含最终 JSON。
