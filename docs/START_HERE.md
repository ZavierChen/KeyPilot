# 项目入口

这份源码包可以在另一台 Windows 电脑重建应用，不要求复制开发者的 Python、D 盘、用户配置或私人模型。

想先了解项目为什么制作、现在有哪些功能，以及如何一步步发展到当前版本，请看 [项目动机、功能与演进](PROJECT_OVERVIEW.md)。

## 1. 准备并安装

需要 Windows 10/11、64 位 CPython 3.12（安装时包括 Tcl/Tk）、PowerShell 5.1 或更新版本。首次安装依赖需要网络。当前验证环境为 Windows、CPython 3.12.14；其他 Python 版本不作为此次验收基准。

解压到普通用户可写的目录，进入含 README.md 的根目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1
```

没有 `py` 启动器时，可明确提供本机解释器：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -Python 'C:\Python312\python.exe'
```

也可以手动执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements/repro-windows-py312.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe scripts/keypilot.py doctor
```

虚拟环境必须在接收者电脑上重建，不能复制开发者 `.venv`。这些命令直接调用环境里的 Python，无需激活脚本。参见 [Python venv 文档](https://docs.python.org/3.12/library/venv.html)。

## 2. 启动与基础演示

```powershell
.\.venv\Scripts\python.exe scripts/keypilot.py gui
```

或双击根目录 `run.cmd`。文字输入“打开计算器”，点击执行。该演示使用内置规则，不需要大模型。软件不会自动安装模型、接管 Copilot 键或注册开机任务。

先保持默认的“自动联网问答关闭”“复杂代理关闭”“自动语音回复关闭”和“语音自动执行关闭”。手动试听和朗读仍可使用。Windows `Win+H` 听写是系统功能，不能视为项目自带的离线 ASR。模型问答与语音合成可以分别启用。

## 3. 选择接入入口

| 要做的事 | 软件/命令入口 | 说明 |
| --- | --- | --- |
| 了解项目与功能 | 仓库/GitHub 文档 | [动机、功能与开发过程](PROJECT_OVERVIEW.md) |
| 接自己的本地模型 | 本地模型门户 | [协议、发现、路由检查](LOCAL_MODELS.md) |
| 让不了解项目的模型接入 | 阅读或安装接入 Skill | [SKILL.md](../skills/keypilot-model-adapter/SKILL.md) |
| 加自己的本地音色 | 自定义语音包导入 | [规范与导入步骤](VOICE_PACKS.md) |
| 了解实验和版本取舍 | 版本迭代记录 | [完整时间线](VERSION_HISTORY.md) |
| 测试功能与复现实验 | 测试与复现指南 | [测试步骤与记录格式](TESTING.md) |

统一命令从任何工作目录都能通过脚本的完整路径运行：

```powershell
.\.venv\Scripts\python.exe scripts/keypilot.py models --help
.\.venv\Scripts\python.exe scripts/keypilot.py voices --help
```

## 4. 数据位置与退出

默认 `%LOCALAPPDATA%\KeyPilot-Repro` 保存设置、密钥加密文件、当天上下文、快捷映射、时钟任务及语音包。现用版 `%LOCALAPPDATA%\KeyPilot` 不会被自动导入。若希望实验互相隔离，启动前指定：

```powershell
$env:KEYPILOT_DATA_DIR = Join-Path (Get-Location) 'data\experiment-a'
.\.venv\Scripts\python.exe scripts/keypilot.py gui
```

关闭窗口结束桌面助手。可选键盘监听由下述命令单独启动，`Ctrl+C` 结束；不要与其他接管相同按键的助手同时使用：

```powershell
.\.venv\Scripts\python.exe scripts/keypilot.py hook
```

该模式只在当前会话中运行监听，不注册开机启动；会启动处理时钟任务的独立后台进程。需要完整结束实验后台时，结束对应 `keypilot.time_worker` Python 进程。基础 GUI 演示无需使用此模式。

仅启动 `gui` 不会启动计时后台。倒计时、闹钟和提醒可以保存，但到点通知需要上述后台进程持续运行；保存任务不等于重启电脑后会自动响铃。

## 5. 排错与分享

- `No module named tkinter`：安装带 Tcl/Tk 的 CPython 3.12，重建 `.venv`。
- 窗口能打开但模型不可用：先在模型门户发现模型并执行路由测试，检查服务 URL、协议和实际模型 ID。应用不自带模型权重。
- 听写不可用：检查 Windows 语音语言包、麦克风权限与系统听写；先用文字验证程序。
- 内置离线声音未列出：安装 Windows 对应语言的语音功能，或关闭朗读继续演示。
- 自定义声音不可用：运行语音包验证并查看错误；模板不含模型，不能直接用于发声。
- 云端 TTS / Google / Marvis / ChatGPT 集成依赖网络、外部产品、页面结构或账户，仅作为可选能力，基础验收不依赖它们。

分享前运行 `python scripts/build_share.py`，使用生成的 ZIP。详细验证记录见 [REPRODUCIBILITY.md](REPRODUCIBILITY.md)。
