# KeyPilot · 可复现的本地语音助手

Windows 桌面助手研究项目：文字/系统听写 → 规则与本地模型路由 → 受限操作 Skill → 系统操作与语音回复。

[公开源码](https://github.com/ZavierChen/KeyPilot-Repro) · [下载发布包](https://github.com/ZavierChen/KeyPilot-Repro/releases) · [Windows 自动验证](https://github.com/ZavierChen/KeyPilot-Repro/actions/workflows/test.yml)

**第一次使用请从 [项目入口](docs/START_HERE.md) 开始。给教授展示请看 [复现与演示指南](docs/PROFESSOR_GUIDE.md)。**

| 入口 | 内容 |
| --- | --- |
| [安装与运行](docs/START_HERE.md) | 从干净 Python 环境启动、验证、排错 |
| [本地模型门户](docs/LOCAL_MODELS.md) | Ollama / OpenAI 兼容接口、模型发现、连接与路由测试 |
| [陌生模型接入 Skill](skills/keypilot-model-adapter/SKILL.md) | 模型如何理解操作契约、输出参数、接入新服务 |
| [自定义语音包](docs/VOICE_PACKS.md) | 可移植格式、运行时、校验、导入与可用性边界 |
| [完整迭代历史](docs/VERSION_HISTORY.md) | 主应用与语音实验两条版本线，保留/回退原因 |
| [历史证据索引](docs/HISTORY_SOURCES.md) | 任务记录与实验报告的来源、覆盖范围 |
| [架构](docs/ARCHITECTURE.md) | 路由、操作权限、状态存储、组件边界 |
| [语音研究工具](docs/VOICE_LAB.md) | 本地复现方法与历史研究代码的位置 |
| [本次验证](docs/REPRODUCIBILITY.md) | 测试环境、已验证内容和未验证内容 |

## 快速启动（Windows 10/11，64 位 Python 3.12）

在项目根目录运行 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
.\.venv\Scripts\python.exe scripts/keypilot.py gui
```

也可以完成安装后双击 `run.cmd`。**启动应用不需要先安装大模型、申请 API Key 或准备私人音色。** 基础规则操作可以直接使用；自然语言模型理解需另接模型服务。

复现版默认关闭联网问答、复杂代理、语音自动执行和朗读。配置、缓存与语音包保存在 `%LOCALAPPDATA%\KeyPilot-Repro`，不会复用现用版 `KeyPilot` 数据。可用绝对路径环境变量 `KEYPILOT_DATA_DIR` 指定实验目录。

```powershell
.\.venv\Scripts\python.exe scripts/keypilot.py doctor
.\.venv\Scripts\python.exe scripts/keypilot.py models --help
.\.venv\Scripts\python.exe scripts/keypilot.py voices --help
.\.venv\Scripts\python.exe -m pytest -q
```

## 项目范围

- `desktop/`：完整桌面端源码、注册操作、系统语音脚本与测试；只支持 Windows。
- `src/voice_assistant/`：独立语音研究工具；不是启动桌面应用的前置服务。
- `skills/keypilot-model-adapter/`：给新模型/编程代理阅读的接入 Skill。它与 `desktop/skills/*/skill.json` 的运行时操作定义用途不同。
- `requirements/repro-windows-py312.lock`：本次复现使用的固定依赖版本。
- `scripts/build_share.py`：生成仅含源代码与文档的分享包和 SHA-256 清单。

```powershell
.\.venv\Scripts\python.exe scripts/build_share.py
```

产物是 `dist/KeyPilot-Repro-source.zip`。不包含 `.env`、API Key、私人录音、模型权重、会话记忆、原始聊天导出、实验工作目录或虚拟环境。发布包附 SHA-256，可从上面的 GitHub Releases 入口下载或直接发给教授。

**语音包仅在本地使用，不上传或随项目分发。** 项目中的 `examples/voice-pack/voice.json` 只是无音频、无权重、不可直接发声的格式模板。其他人按规范在自己的电脑准备和导入自己的声音资源。

当前可复现的是应用、接口契约与导入流程。特定私人音色的听感和历史训练指标依赖未分发的数据、权重和机器，不能仅凭此源码包重现。兼容接口也不保证所有模型均能正确遵守结构化输出，需逐个测试。
