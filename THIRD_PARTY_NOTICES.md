# 第三方组件与分发范围

源码包包含现有 KeyPilot 应用代码及项目资源、本次整理的接入模块与文档。仓库公开提供源码与复现实验说明，尚未指定独立开源许可证；第三方组件和模型仍适用其各自许可。

第三方 Python 包通过 pip 安装，不把开发者机器的 `vendor` 目录打入分享包。依赖的完整固定版本见 `requirements/repro-windows-py312.lock`；各包许可保存在其安装发行物 metadata/license 中。

主要上游：

- [Python](https://www.python.org/)：解释器、Tcl/Tk 与标准库。
- [edge-tts](https://github.com/rany2/edge-tts)：可选联网自然声音。
- [Ollama](https://github.com/ollama/ollama)：可选本地模型服务；模型权重分别适用其自身许可。
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) 与 [ZipVoice](https://github.com/k2-fsa/ZipVoice)：可选本地语音推理与训练。模型、声码器、词典和 eSpeak 数据各自有许可，应用许可不替代它们。
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) 和 RVC 相关引擎：保留历史适配代码，不打包运行时和权重，本次可移植导入格式只覆盖 ZipVoice。
- [openSMILE](https://github.com/audeering/opensmile-python)：可选研究分析工具；使用前查看上游许可，不属于桌面默认安装。

所有语音包仅在本地使用，不随源码上传或分发。私人参考声音、训练语料、授权证据、API Key、模型权重与原始会话记录均不进入源码分享包。公开项目只给出实现规范、空配置模板和本地复现方法。
