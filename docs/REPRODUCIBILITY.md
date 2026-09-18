# 本次复现验收记录

日期：2026-09-18。目标是把现有 Windows 助手整理为可分享的源码项目；没有重跑全部历史训练，也没有用私人模型代替公开依赖测试。

## 复现基线

- Windows x64、CPython 3.12.14，重新创建不继承全局包的 `.venv`。
- 使用 `scripts/setup.ps1` 从固定依赖表安装，再执行环境检查。运行 `pip check` 未发现依赖冲突。
- `desktop/keypilot/__init__.py` 原代码版本为 `0.23.0`。本次采用“研究复现版 2026-09-18”标识；根目录 Python 包 `0.1.0` 是独立语音研究工具的历史版本，不代表桌面应用回退到早期版本。
- 个人状态经 `KEYPILOT_DATA_DIR` 隔离；测试不调用真实 Windows 动作，不启动实际本地模型，不调用收费语音服务。

## 已验证

| 项目 | 方法与结果 |
| --- | --- |
| 从空虚拟环境安装 | 实际运行 setup.ps1，固定包安装与 doctor 成功 |
| 默认启动 | `scripts/keypilot.py gui --smoke-test` 创建/关闭 Tk 窗口，退出码 0 |
| 注册操作 | doctor 加载 12 个运行时 Skill，三个规则命令命中预期操作，执行数 0 |
| 自动测试 | 从分享 ZIP 解压的独立目录和新建虚拟环境中：228 passed / 3 skipped；含原应用、语音工具、新模型桥接与语音包导入测试 |
| 干净源码包 | 实际解压分享包、运行其 setup.ps1、GUI smoke、合法提案验证和 pip check，均通过；不依赖原工作区的 work、vendor、录音或权重 |
| 模型传输 | 使用回环 HTTP 测试服务检查 Ollama 和 OpenAI 兼容请求/模型列表/结构化返回；没有称作真实 LLM 评测 |
| 非法操作 | 拒绝未知 Skill、额外字段、错误类型、越界值、缺少设置值及非有限数；校验工具始终不执行动作 |
| 语音包 | 临时模型文件与 mock 运行时验证目录边界、运行时分离、失败清理、同名拒绝和 ready 发布条件 |
| 可选语音依赖 | 对 `requirements-voice-zipvoice.txt` 运行 pip dry-run，Windows CPython 3.12 依赖均可解析；这不代表权重加载或声音合成已验收 |
| 统一 CLI | models/voices 帮助、契约导出、合法/非法提案检查与退出码已验证 |
| 陌生模型按 Skill 接入 | 独立代理只读文档，导出当版契约并生成音量 30 的提案；真实 CLI 校验通过，`execution=not_executed` |

3 项跳过：两项需要额外 PyTorch/历史 ZipVoice 训练 checkout；一项需要当前 Windows 用户创建符号链接的权限（另有 reparse point 模拟测试覆盖）。这些跳过不等于训练或模型质量验证成功。

## 需要在实际环境中验证

- 真实模型的路由准确率、拒绝率、冷/热启动延迟和内存占用。
- 可移植公开权重加自有参考录音的实际合成、音质、播放设备兼容性。本次没有用私人参考录音进行这项验收。
- 真实 Windows 听写、亮度/音量设备、Copilot 硬件键与开机常驻行为。
- 云端 TTS、Google 页面读取、外部桌面代理与第三方 API 的在线行为。
- GitHub Actions 的实际运行状态见 [Windows 自动验证](https://github.com/ZavierChen/KeyPilot-Repro/actions/workflows/test.yml)；本页的本地验收与每个提交的 CI 结果分别记录。

历史性能数字与版本取舍见 [VERSION_HISTORY.md](VERSION_HISTORY.md)，其证据和本次验收明确分开。可以公开复现软件接口和验证流程，不能据此宣称已重现所有历史声音实验。

## 分享包

`scripts/build_share.py` 按源码目录和文件类型白名单生成 ZIP，包含文件 SHA-256 清单，并另外输出整个 ZIP 的 SHA-256。权重、录音、用户状态、凭据、历史原始聊天、`work/` 和虚拟环境均排除。

所有语音包均只在本地使用，分享材料仅包含实现规范、无资源模板和本地导入代码；不发布任何可发声的语音包。

解压源码发行包后，在本机重建 `.venv`，按 [START_HERE.md](START_HERE.md) 运行。桌面端入口为 `scripts/keypilot.py`；单独安装根目录 Python wheel 只提供语音研究工具，不包含桌面资源。
