# 本地语音复现与历史研究工具

**语音包仅在本地使用，不上传、不随项目分发。** 本页只说明实现方法、代码位置和研究边界。公开源码中的配置模板不包含录音、模型权重或可发声资源。

## 本地复现路径

1. 在自己的电脑安装独立语音 Python 环境。
2. 从上游取得可合法使用的公开 ZipVoice / Vocos 资源；使用自己的或取得许可的参考音频及逐字稿。
3. 按 [VOICE_PACKS.md](VOICE_PACKS.md) 组装包内相对路径清单。
4. 通过本地验证器检查资产、依赖和 ONNX 加载，然后导入本机数据目录并试听。
5. 本地记录资源版本、SHA-256、硬件、文本与评测结果。音色相似度依赖参考材料，不保证复现作者的私人声音。

以上不需要作者的录音、账户、声音ID或训练权重。导入代码没有上传接口。

## 可选本地训练与分析

需要自行训练时，根据 [ZipVoice 上游](https://github.com/k2-fsa/ZipVoice) 准备数据并训练，保留训练、验证和独立测试划分，再导出应用可用的 ONNX INT8 格式。历史 `work/ZipVoice` 和个人训练工作区不在分享范围；新实验需要自行固定上游提交、依赖与随机种子。

`src/voice_assistant/voice_analysis.py` 可分析参考音频的声学参数；`prepare_combined_dataset.py` 可辅助生成数据清单；`zipvoice_runner.py` 是原有训练启动辅助。它们不是启动桌面助手的前置服务，也不构成一套已锁定的完整训练环境。

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[analysis]'
.\.venv\Scripts\voice-params.exe data\reference.wav --transcript '实际逐字稿' --output outputs\voice-parameters.json
```

`emotion-analysis` 是额外实验环境，包含 SenseVoice/FunASR 与 openSMILE，未纳入桌面端固定依赖与本次默认验收。历史音质数字不作为新环境已验证的结果。

## 既有在线研究代码的位置

项目历史探索过火山引擎声音训练、双向流式 TTS 与教师语料。相应代码保留在 `src/voice_assistant/providers/volcengine.py` 和 `cloud_teacher_dataset.py`，用于理解历史实验；它们不是本次语音包复现的默认路径。调用这些历史在线工具会传输相应数据并可能产生服务费用，本次整理没有调用它们，也不以它们上传语音包。

代码已移除开发者音色 ID 和自动读取现用版密钥的默认值，必须使用者另行明确配置。无需配置这些服务也能启动桌面助手和使用本地语音包。

完整迭代、保留和回退理由见 [VERSION_HISTORY.md](VERSION_HISTORY.md)。仓库保留技术过程与结果摘要，不包含原始录音、生成音频、训练产物或原始聊天记录。
