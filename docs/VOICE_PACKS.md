# 自定义语音包：准备、校验、导入

选声音路线先看 [个性化语音子项目](VOICE_PROJECT.md)：GPU 短样本本地克隆、云端辅助制作后 CPU 长期使用，或直接选择云端 API。本页说明当前标准包的具体实现。

本项目提供可移植 **ZipVoice CPU 语音包 v1** 的模板、校验器和导入入口。仓库只包含代码与空模板，不包含作者的私人录音、训练后的私人音色、授权记录、Speaker ID 或云服务密钥。要复现自定义声音，使用者需要自行准备合法可用的参考录音、公开模型和本机运行时。公开基础模型可以复现接入流程，不会复现作者的私人音色。

**语音包仅在本地使用，不上传 GitHub，也不随项目分发。本文说明语音包的格式、准备方法和本地导入步骤；导入过程只在本机目录之间复制文件。**

软件设置中的“导入语音包”与下面的 CLI 调用同一个导入函数。先选择包文件夹，再单独选择自己安装的语音 Python；成功后选择该音色并试听。“语音包规范”可打开本文。首次加载模型可能需要等待，导入会先完成模型加载校验。

## 1. 实际支持范围

| 路线 | 已有代码能力 | 接入方式 |
| --- | --- | --- |
| Windows 内置声音 | 本机朗读，无克隆 | 安装 Windows 对应语言声音后可作为基本演示 |
| Edge TTS | 联网合成普通声音 | 软件已有提供方，不能称为完全离线 |
| `zipvoice` | sherpa-onnx + ONNX INT8，CPU，中英参考音频克隆 | **本版标准可移植导入路线** |
| `qwen3-tts-zero-shot` | `Qwen3TTSModel` 本机推理；当前 worker 固定 CUDA、bfloat16、SDPA | 保留高级适配代码；不受 v1 导入器支持，另配完整 GPU 环境 |
| `edge-rvc` | 先由 Edge 联网生成，再由本机 RVC 转换 | 保留高级适配代码；需要外部 RVC 源码和训练权重，不受 v1 导入器支持 |
| 火山引擎在线复刻 | WebSocket 流式合成 | 另见研究模块与云服务配置；需要账户与音色，不能离线复现 |

“支持”表示代码中存在对应适配，不表示仓库提供所有引擎的权重和运行环境。v1 故意只导入纯数据的 ZipVoice 包，不执行包中提供的 Python、安装脚本或 ffmpeg；复杂路由、质量预设以及其他引擎需要开发者单独接入。

## 2. 准备独立运行时

先按仓库 README 安装桌面项目。下面命令从仓库根目录运行，目标环境为 **Windows x64 / 官方 CPython 3.12**，不使用 MSYS Python。语音依赖安装到独立虚拟环境，不会进入普通桌面运行环境：

```powershell
py -3.12 -m venv .venv-voice
.\.venv-voice\Scripts\python.exe -m pip install -r requirements-voice-zipvoice.txt
.\.venv-voice\Scripts\python.exe -m pip check
```

依赖表固定 `sherpa-onnx==1.13.8`、`numpy==2.2.6`、`soundfile==0.13.1` 及其 CFFI 依赖。选定的 sherpa 版本提供 ZipVoice Python 接口和 Windows CPython 3.12 wheel，见 [PyPI 发布文件](https://pypi.org/project/sherpa-onnx/1.13.8/) 和 [对应版本的官方示例](https://github.com/k2-fsa/sherpa-onnx/blob/v1.13.8/python-api-examples/zipvoice-tts.py)。这份依赖表是可复现的安装起点；以导入器在自己机器上的检查结果为准。

安装阶段需要网络。模型和依赖准备完整后，ZipVoice worker 在本地推理。无需 CUDA、PyTorch、云服务密钥或额外 ffmpeg。不要把 Python 环境放进语音包，也不要接受别人给包附带的可执行文件。

导入时可选择虚拟环境的 `Scripts/python.exe`。导入器运行固定的探测代码，记录其真实 CPython 路径和 `site-packages`，使 Windows worker 可以直接退出而不留下虚拟环境转发进程。更换或删除该环境后，需用新 `id` 重新导入，或由开发者维护本机配置；运行时不会被复制进包。

## 3. 准备公开权重和参考录音

从 [sherpa-onnx 官方 ZipVoice 页面](https://k2-fsa.github.io/sherpa/onnx/tts/zipvoice.html) 下载这两个资源：

- [中英 ZipVoice INT8 模型归档](https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/sherpa-onnx-zipvoice-distill-int8-zh-en-emilia.tar.bz2)
- [Vocos 24 kHz 声码器](https://github.com/k2-fsa/sherpa-onnx/releases/download/vocoder-models/vocos_24khz.onnx)

用归档工具解压公开模型，把下面列出的四个模型文件及整个 `espeak-ng-data` 目录放入自己包的 `model` 子目录；把声码器放在包根目录。上游测试录音不必复制。v1 使用内嵌权重的 ONNX 文件；需要额外 tensor sidecar 的自定义 ONNX 导出应先按此布局重新导出。模型、声码器的许可与来源应自行核对并记录；仓库没有重新分发这些大文件，也未提供独立的权重校验和承诺。

```text
my-voice/
  voice.json
  reference.wav
  vocos_24khz.onnx
  model/
    encoder.int8.onnx
    decoder.int8.onnx
    tokens.txt
    lexicon.txt
    espeak-ng-data/
      ...完整上游数据...
```

`reference.wav` 使用本人或获许可的单人干声，单声道、8–48 kHz、1–30 秒；本版导入器会检查时长、采样率、通道数、静音及非有限样本。建议选择清楚、无音乐、无明显混响的一段短录音。`reference_text` 必须逐字对应录音，不能填写想让模型输出的新句子。ZipVoice 同时需要参考音频和对应文本，见 [官方输入说明](https://k2-fsa.github.io/sherpa/onnx/tts/zipvoice.html)。

授权证据留在独立私人位置，**不要放入公开项目或示例包**。模板没有真人数据，也不会自动替使用者作出授权声明。

## 4. 创建模板

```powershell
.\.venv\Scripts\python.exe scripts/keypilot.py voices template "$env:USERPROFILE\Documents\my-voice" --id my-voice --name "我的实验音色"
```

也可复制 [examples/voice-pack/voice.json](../examples/voice-pack/voice.json)。模板不生成录音或权重，不能直接试听，`ready` 初始为 `false`：

```json
{
  "schema_version": 1,
  "id": "my-voice",
  "name": "我的实验音色",
  "engine": "zipvoice",
  "ready": false,
  "synthetic_voice": true,
  "model": "model",
  "vocoder": "vocos_24khz.onnx",
  "reference_audio": "reference.wav",
  "reference_text": "这里填写参考录音中实际说出的文字。",
  "num_steps": 4,
  "num_threads": 2
}
```

`id` 为 1–64 个小写字母、数字、`-` 或 `_`，首位为字母或数字，不得使用 Windows 保留名称。`name` 是界面显示名。资源路径统一用 `/`，必须为包内相对路径，不接受绝对路径、`..`、符号链接或目录联接。

`num_steps` 为 1–16，`num_threads` 为 1–8；可选 `idle_seconds` 为 15–600，默认 60；可选 `min_char_in_sentence` 为 1–120，默认 5。v1 不接受清单以外字段，尤其不能包含 `python`、`site_packages`、`ffmpeg`、`command` 或密钥。高级引擎旧版的本机 `voice.json` 与这个可移植格式不同，不能直接混用。

## 5. 校验与导入

只检查布局、文件是否非空、参数和路径（不会执行语音 Python）：

```powershell
.\.venv\Scripts\python.exe scripts/keypilot.py voices validate "$env:USERPROFILE\Documents\my-voice"
```

返回 `validation: files_only`、`ready: false` 是正常结果。仅文件存在不足以证明模型可用。

进一步解码参考音频、检查依赖并实际加载 ONNX 模型：

```powershell
.\.venv\Scripts\python.exe scripts/keypilot.py voices validate "$env:USERPROFILE\Documents\my-voice" --python .\.venv-voice\Scripts\python.exe
```

通过后返回 `validation: model_loaded` 和当前运行时版本。这一步不播放、不做试听评分，不保证任何指定的克隆相似度。

导入到当前研究版的数据目录：

```powershell
.\.venv\Scripts\python.exe scripts/keypilot.py voices import "$env:USERPROFILE\Documents\my-voice" --python .\.venv-voice\Scripts\python.exe
```

默认位置是 `%LOCALAPPDATA%\KeyPilot-Repro\voice-packs\my-voice\voice.json`；若设置 `KEYPILOT_DATA_DIR`，使用该数据根目录下的 `voice-packs`。应用和 CLI 必须使用相同的数据目录。CLI 的 `--destination` 适合测试或备份，指定其他目录时应用不会自动扫描它。

导入流程会选择性复制六个明确文件和 `espeak-ng-data`，在暂存目录检查模型和参考录音，成功后才写 `ready: true` 的本机配置。清单中自行声称 `ready: true` 不会跳过检查。同名 `id` 一律拒绝覆盖，需改成另一个 `id`。失败时清理本次暂存文件，不修改源包或其他已安装包。导入器不复制包根目录的授权记录、日志、缓存、测试录音和任意脚本。

成功后在软件选择音色并点击“试听”。CLI 导入后若软件已经打开，重新打开设置或重启应用刷新列表。性能模式按需加载并空闲退出；质量模式预热并保持模型。退出或移除包前先停止朗读。移除当前用户数据目录中的对应包可以清除其模型副本与合成缓存，外部独立 Python 环境由使用者管理。

## 6. 失败排查与复现记录

| 结果 | 处理 |
| --- | --- |
| 缺少资源 / `espeak-ng-data` 为空 | 补齐公开模型文件；包应包含完整数据目录 |
| `sherpa-onnx lacks ZipVoice support` | 确认使用指定的语音 Python，并按依赖文件重新安装 |
| `DLL load failed` | 核对 CPython 3.12 x64、wheel 架构和 Windows 运行库；不要混入 MSYS 环境 |
| 音频格式、时长或静音错误 | 重新导出单声道 WAV，检查实际录音与转写 |
| 模型加载失败 | 检查权重是否完整、版本与声码器是否匹配；不要仅改 `ready` |
| 校验通过但试听失败 | 查看安装包的 `worker.log`，检查播放设备、资源路径和内存 |
| 声音可用但不像 / 发音差 | 改善参考录音与转写，或自行训练模型；导入成功不是音质认证 |

为便于复现和排错，可保存 `validate --python` 的 JSON 输出、公开权重来源、下载文件的 SHA-256（PowerShell `Get-FileHash`）、机器 CPU/RAM 和试听结果。依赖与模型加载校验、实际音频合成、音质评价分别记录。

导入单元测试使用临时占位文件和 mock 运行时，覆盖布局、拒绝执行字段、路径越界、缺失资源、重名、失败清理及写入 `ready` 的条件。实际模型加载、音频合成与音质按上述步骤单独验证。

## 7. 扩展其他引擎

Qwen 路线需要单独安装兼容的 `qwen-tts`、PyTorch、torchaudio 和 Transformers，再完整下载 [Qwen3-TTS Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base)（包括 speech tokenizer），按 [官方安装说明](https://github.com/QwenLM/Qwen3-TTS) 配置 GPU。当前 `voice_worker.py` 固定 `cuda:0` / `bfloat16`，没有 CPU 自动降级；历史本机环境版本也不构成本版完整锁定依赖。

RVC 路线需要可信的外部 RVC 源码、对应 Python 依赖、模型 `.pth`、检索 `.index`、RMVPE/内容编码器资源以及可用的 Edge TTS 网络。`rvc_voice.py` 会导入该源码执行转换，因此不能把随意下载的 RVC 文件夹交给 v1 导入器。

要增加标准导入支持，应在 `voice_pack_manager.py` 为引擎定义纯数据字段、路径边界、资产清单和固定探测器；在 `voice_worker.py` 加载对应配置；为离线/联网行为与依赖写明规范，再加入缺失资源与失败回退测试。不要通过允许包里任意命令来接入。

开发者接口（从 `desktop` 工作目录运行，或已将该目录加入模块路径；普通使用者使用上述统一脚本入口）：

```python
from pathlib import Path
from keypilot.voice_pack_manager import import_voice_pack, validate_voice_pack

report = validate_voice_pack(Path("my-voice"), python=Path(".venv-voice/Scripts/python.exe"))
installed_manifest = import_voice_pack(
    Path("my-voice"), python=Path(".venv-voice/Scripts/python.exe")
)
```

函数错误为 `VoicePackError`（`ValueError` 的子类）；导入返回安装后的 `voice.json`。GUI 在后台线程调用导入，成功后刷新音色目录。CLI 成功退出码为 0，包无效或资源不足为 2。
