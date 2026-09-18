---
name: keypilot-model-adapter
description: 将本地推理服务接入 KeyPilot Windows 助手，导出真实操作目录并验证受限动作 JSON。用于更换模型、配置 Ollama 或 OpenAI 兼容端点、排查模型操作转接，以及让不了解此项目的模型遵守其操作协议。
---

# KeyPilot 模型转接

把模型作为意图解析器接入 KeyPilot。模型提出一个已注册操作，应用验证参数并按用户提交方式决定是否执行。此 Skill 是随仓库分发的接入说明；它本身不授予电脑控制权限，也不创建 HTTP 执行接口。

## 先建立项目上下文

1. 找到仓库根目录，确认存在 `desktop/keypilot/local_model_portal.py` 和 `desktop/skills/`。从别处安装本 Skill 后，不要把 Skill 安装目录当作项目根目录。
2. 使用项目的 Python 环境；安装步骤见仓库 `docs/START_HERE.md`。本 Skill 的 `python` 指已准备好的项目虚拟环境解释器；没有激活环境时，在 Windows 用 `.\.venv\Scripts\python.exe` 替代。运行 `python scripts/keypilot.py models --help` 确认本版本接口。
3. 导出本版本契约：`python scripts/keypilot.py models contract --output outputs/model-contract.json`。将输出作为唯一动作目录来源；不要根据本 Skill 的示例猜测新增能力。

## 按请求选择工作流

- **接入或更换模型**：读 [连接与验证](references/connection.md)。核实实际服务协议、端点和模型 ID，先做只读探测，再保存 GUI 门户配置。
- **教模型输出操作**：读 [动作协议与提示词](references/action-contract.md)，把导出的契约连同其中的提示词交给目标模型。模型输出经过 `validate-response` 验证后，仍须交回应用的正常提交路径。
- **新增操作能力**：同时更新 `desktop/skills/<id>/skill.json`、实际执行分支及相关测试；只增加 Skill 文本或 JSON 注册文件不会产生新的执行能力。读仓库 `docs/ARCHITECTURE.md`。

## 必须保持的边界

- 一次只返回一个完整、明确的已注册操作。多步骤、缺少必要信息、普通聊天或未知操作，返回 `{"matched":false,"skill_id":"","arguments":{}}`。
- 仅输出 `matched`、`skill_id`、`arguments` 三个字段。参数遵守当前目录的 `input_schema`；不输出 shell、Python、任意命令、模型自定义的动作类型或 `codex_fallback`。
- `contract`、`models`、`probe`、`validate-response` 用于发现、推理和验证；不执行 Windows 操作。模型生成的“成功”说明不是执行结果。
- 对模型错误、服务不支持的协议和验证失败，保留失败并报告原因。不要绕过校验、放宽注册表、切换云端或开启复杂代理来掩盖接入失败。
- 用户已要求接入时，可以完成配置和只读探测；实际电脑操作仍遵守该请求的范围和应用的提交机制。当前低风险语音自动执行可直接运行，其他请求需要用户提交；不能声称所有操作都有额外确认弹窗。

交付时给出实际端点、模型 ID、所用 JSON 模式、验证结果及尚未实测的能力。不要把密钥、个人音色、对话记录或本机绝对路径写进可分享配置。
