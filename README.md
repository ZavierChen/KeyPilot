# KeyPilot · 可复现的本地语音助手

KeyPilot 是一个 Windows 桌面语音助手，把按键唤起、文字与听写输入、日常电脑操作、模型问答和语音回复放在同一个应用里。常用命令由规则直接处理，模糊表达可交给本地模型选择受限操作 Skill。

[公开源码](https://github.com/ZavierChen/KeyPilot-Repro) · [下载发布包](https://github.com/ZavierChen/KeyPilot-Repro/releases) · [Windows 自动验证](https://github.com/ZavierChen/KeyPilot-Repro/actions/workflows/test.yml)

## 为什么制作

项目从一个具体需求开始：让键盘上难以按需自定义的 Copilot 键，能打开自己选择的应用或语音入口。随后目标扩展为一个随手可用的桌面助手——打开应用、调节音量和亮度、查找系统设置这些日常操作，应当响应快，也不必每次都新建一段云端聊天。

因此，KeyPilot 逐步形成了“规则优先、本地模型补充理解、程序执行 Skill、复杂需求按配置转接”的结构。之后的迭代围绕实际使用展开：补齐时钟与网页功能，改善问答来源，减少模型空闲占用，再加入可选音色、语音调度和稳定启动。完整过程见 [项目动机、功能与演进](docs/PROJECT_OVERVIEW.md)。

## 功能简介

| 功能 | 可以做什么 |
| --- | --- |
| 日常电脑操作 | 打开应用、桌面文件和文件夹；调音量、亮度；打开设置页或填写设置搜索词 |
| 网站与快捷映射 | 打开网址或搜索；自定义“学校网站”“学习资料”等关键词与网址/本机路径的对应关系 |
| 时间助手 | 世界时间、倒计时、闹钟、提醒、任务列表与铃声；到点提醒需要后台计时进程运行 |
| 问答与页面读取 | 可选本地问答、Google AI 页面读取、Marvis 转接、兼容 API 问答；支持读取当前浏览器页面 |
| 对话与朗读 | Windows 听写、有限的当天上下文；结果编辑、复制、重读，剪贴板朗读及听写打断播报 |
| 声音设置 | 系统/联网声音、自定义本地语音包；回复长度三档、语速微调、按需加载或预热常驻 |
| Copilot 键入口 | 主动启动按键监听后，单击打开/最小化助手、双击开始/取消听写；不自动接管键盘 |
| 模型与声音扩展 | 本地模型门户、模型发现、只读路由测试、契约导出、陌生模型接入 Skill、语音包校验与本地导入 |

基础文字与规则操作无需大模型。听写依赖 Windows；模型服务、联网功能和自定义音色需分别配置。详细入口、示例与使用条件见 [完整功能说明](docs/PROJECT_OVERVIEW.md#当前功能)。

**第一次使用请从 [项目入口](docs/START_HERE.md) 开始。验证功能与复现实验请看 [测试与复现指南](docs/TESTING.md)。**

| 入口 | 内容 |
| --- | --- |
| [项目动机、功能与演进](docs/PROJECT_OVERVIEW.md) | 为什么制作、现在能做什么、从按键工具到当前版本的实现过程 |
| [安装与运行](docs/START_HERE.md) | 从干净 Python 环境启动、验证、排错 |
| [本地模型门户](docs/LOCAL_MODELS.md) | Ollama / OpenAI 兼容接口、模型发现、连接与路由测试 |
| [陌生模型接入 Skill](skills/keypilot-model-adapter/SKILL.md) | 模型如何理解操作契约、输出参数、接入新服务 |
| [自定义语音包](docs/VOICE_PACKS.md) | 可移植格式、运行时、校验、导入与可用性边界 |
| [完整迭代历史](docs/VERSION_HISTORY.md) | 主应用与语音实验两条版本线，保留/回退原因 |
| [历史证据索引](docs/HISTORY_SOURCES.md) | 任务记录与实验报告的来源、覆盖范围 |
| [架构](docs/ARCHITECTURE.md) | 路由、操作权限、状态存储、组件边界 |
| [语音研究工具](docs/VOICE_LAB.md) | 本地复现方法与历史研究代码的位置 |
| [本次验证](docs/REPRODUCIBILITY.md) | 测试环境、已验证内容和未验证内容 |

应用源码版本仍为 `0.23.0`，后续修复和公开整理单独记录；当前公开文档与源码包版本为 `repro-2026.09.18.2`。历史语音实验 `v1–v7` 是另一条版本线，相关私人声音资源不分发。

## 快速启动（Windows 10/11，64 位 Python 3.12）

在项目根目录运行 PowerShell：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
.\.venv\Scripts\python.exe scripts/keypilot.py gui
```

也可以完成安装后双击 `run.cmd`。**启动应用不需要先安装大模型、申请 API Key 或准备私人音色。** 基础规则操作可以直接使用；自然语言模型理解需另接模型服务。

复现版默认关闭自动联网问答、复杂代理、语音自动执行和自动语音回复；手动试听和朗读仍可使用。配置、缓存与语音包保存在 `%LOCALAPPDATA%\KeyPilot-Repro`，不会复用现用版 `KeyPilot` 数据。可用绝对路径环境变量 `KEYPILOT_DATA_DIR` 指定实验目录。

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

产物是 `dist/KeyPilot-Repro-source.zip`。不包含 `.env`、API Key、私人录音、模型权重、会话记忆、原始聊天导出、实验工作目录或虚拟环境。发布包附 SHA-256，可从上面的 GitHub Releases 入口下载。

**语音包仅在本地使用，不上传或随项目分发。** 项目中的 `examples/voice-pack/voice.json` 只是无音频、无权重、不可直接发声的格式模板。其他人按规范在自己的电脑准备和导入自己的声音资源。

当前可复现的是应用、接口契约与导入流程。特定私人音色的听感和历史训练指标依赖未分发的数据、权重和机器，不能仅凭此源码包重现。兼容接口也不保证所有模型均能正确遵守结构化输出，需逐个测试。
