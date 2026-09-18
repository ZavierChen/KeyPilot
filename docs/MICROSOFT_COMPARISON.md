# 微软助手能力核对与 KeyPilot 的作用

[项目首页](../README.md) · [功能简介](PROJECT_OVERVIEW.md) · [亮点与同类方案](DIFFERENTIATION.md) · [发展路线](ROADMAP.md)

核对日期：2026-09-18。以下依据微软官方支持页、开发文档和发布公告；没有将文档研究写成同机实测。预览与订阅条件按对应功能分别记录，旧公告只用于说明该次发布。

## 项目要实现的体验

**KeyPilot 让 Windows 听懂需求，也执行任务：以 Siri 式交互连接电脑操作与 AI 执行能力，让普通电脑也能拥有自己的个人助手。**

这一目标落实到四个使用结果：按下按键即可表达需求；日常任务直接进入执行；完成后得到界面与语音反馈；模型、服务与声音可以由自己选择。常用操作无需付费云端模型，本地推理与声音可进一步减少持续服务支出。当前已实现单次 Skill 操作流程，正以此为基础规划多步骤 AI 代理。

## 微软目前能做到哪一步

| 产品或功能 | 官方描述的实际能力 | 开放范围与需要分清的条件 |
| --- | --- | --- |
| Windows 个人版 Copilot | 语音对话、文件查找/打开及内容问答、截图与网页理解；设置支持可以引导至相关选项。[Windows 入门页](https://support.microsoft.com/en-us/microsoft-copilot/getting-started-with-copilot-on-windows) | “Hey Copilot”需要主动开启，当前唤醒词为英语；唤醒检测在本机，对话需联网处理。[唤醒词说明](https://support.microsoft.com/en-us/microsoft-copilot/copilot-wake-word-hey-copilot) |
| Copilot Vision 与文字编辑 Actions | 一般 Vision 功能观察共享窗口并指导操作；另有在 Vision 会话中预览、接受文字修改的 Actions 功能。[Vision 支持](https://support.microsoft.com/en-us/microsoft-copilot/using-copilot-vision-with-microsoft-copilot)、[文字编辑公告](https://blogs.windows.com/windows-insider/2025/12/19/copilot-on-windows-new-text-editing-feature-begins-rolling-out-to-windows-insiders/) | 当前 Vision 支持页列 Microsoft 365 Personal / Family / Premium 条件。文字编辑公告是 2025-12-19 的 Insider 分批预览，与长任务 Actions 分开；不能把它描述成所有窗口均可自由操作 |
| Windows Copilot Actions / Agent Workspace | 能在独立 Windows 会话中点击、输入、滚动，操作桌面和网页应用；官方示例包括整理下载目录、分类照片、转换文件及提取 PDF 信息。[功能说明](https://support.microsoft.com/en-us/windows/ai/ai-features/experimental-agentic-features)、[发布示例](https://blogs.windows.com/windows-insider/2025/11/17/copilot-on-windows-copilot-actions-begins-rolling-out-to-windows-insiders/) | 当前支持页仍标为 Windows Insider / Copilot Labs 实验预览，实验开关默认关闭。工作区是执行环境，不能据此推断模型完全离线；所核资料未明确本功能的单独价格 |
| Edge 的 Browse with Copilot | 在浏览器中点击、输入、滚动和切换标签以完成网页任务；原名 Copilot Actions。[当前支持页](https://support.microsoft.com/en-us/microsoft-copilot/browse-with-copilot) | 当前面向美国 Microsoft 365 Premium 订阅者滚动开放，页面仍称 experimental；这是浏览器任务执行，不是任意桌面操作 |
| Windows 设置代理 / Mu | 本地模型理解设置需求，用户点击 Apply 后可执行相应设置变更。[当前设置说明](https://support.microsoft.com/en-us/windows/experience/exploring-windows-settings) | 官方列 Copilot+ PC、语言和地区条件；它与 Copilot 应用中的设置引导不同，也不是通用电脑代理 |
| Copilot Studio computer use | 机构可以给代理配置 Windows 执行机器，通过鼠标键盘完成跨网页与桌面流程。[功能文档](https://learn.microsoft.com/en-us/microsoft-copilot-studio/computer-use) | 2026-05-13 宣布正式可用；需要 Studio 环境、机器与凭据，并按执行步骤计费。它不是普通 Copilot 应用默认附带的功能。[正式发布公告](https://techcommunity.microsoft.com/blog/copilot-studio-blog/computer-using-agents-in-microsoft-copilot-studio-are-now-generally-available/4519427) |

这些资料已经表明微软具备真实的代理执行能力；同时，语音、屏幕指导、桌面代理、浏览器代理和企业编排并不具有相同的使用条件。不能将它们合成一个所有个人用户都已获得的默认体验。地区也需要单独核对：官方普通话和中文语言支持并不代表所有地区可用。[地区与语言支持](https://support.microsoft.com/en-us/microsoft-copilot/supported-regions-and-languages-in-microsoft-copilot)

## KeyPilot 值得做的具体原因

| 对使用者的价值 | KeyPilot 当前的基础 | 后续要继续做好的部分 |
| --- | --- | --- |
| **一句话接到实际操作** | 已有应用/文件入口、音量亮度、设置定位、计时等动作，支持规则和模型选择 Skill 后执行 | 提高自然表达覆盖，把多个动作组织成完整任务并检查结果 |
| **常用路径没有云端模型账单** | 明确的规则操作绕过大模型；本地模型与本地声音可选；基础使用无需模型服务订阅 | 用固定任务集记录本地/云端调用比例与费用，让低成本有可重复的量化证据 |
| **能力与个人体验可以分别升级** | 本地模型门户、兼容 API、操作契约、独立声音配置；模型替换后仍可保留操作映射和音色 | 将经过验证的组合做成 App 内一键选择，降低维护成本 |
| **从现有电脑起步** | 基础规则功能没有专用 NPU 或独立显卡要求，不要求先安装大模型 | 做好安装包、按键注册和硬件适配，让不同品牌及自配电脑都容易使用 |
| **声音与实现方法由自己掌握** | 提供本地语音包规范、校验、导入及可复现源码；作者声音资源留在本机 | 把录音、质量检查、可选制作和导入做成稳定流程 |

这些是产品价值及已有实现，不是“所有竞品都没有”的断言。**项目真正要交付的是一个日常可依赖的语音执行入口：简单事情低成本直接完成，复杂任务接入合适的模型和代理，用户仍保留对能力来源与声音的选择。** 这也是它对没有满意预装助手的整机、自配电脑和希望建立自有助手体验的厂商的意义。

Marvis 转接体现了这条成本路线：选择它的重要原因，是作者使用时每天可获得免费 Token，在额度内补充云端代理能力。Marvis 本身是可执行电脑任务的 AI 代理，KeyPilot 提供日常入口和请求投递；实际赠送规则由服务账户决定，见[接入动机与当前范围](PROJECT_OVERVIEW.md#为什么选择-marvis)。

当前边界集中说明：KeyPilot 使用 Windows `Win+H` 在线听写，尚非全离线语音链路；语音唤醒、零手动配置安装和通用多步骤代理仍未完成。本地 Skill 有执行反馈，但没有覆盖所有动作的独立结果复查；Codex 桥接范围有限，ChatGPT/Marvis 当前主要完成需求投递，不能以“已发送”代替“任务完成”。完整实现与规划分别见[功能说明](PROJECT_OVERVIEW.md)和[路线图](ROADMAP.md)。

## Copilot 键经历说明了什么

作者最初希望重新利用 Copilot 键，因为本机按下只出现搜索。后续 Windows 设置截图确认当前选项为“搜索”，另有“打开应用”；这是已确认的按键配置，不证明 Copilot 未安装、地区不可用或电脑不支持。作者没有实际用过 Copilot，本文比较来自上面的官方资料。

微软提供按键目标配置和第三方应用注册机制。符合打包、签名与应用清单要求的程序，可以成为 Copilot 键 / Win+C 的候选启动目标。因此，KeyPilot 可将正式安装版接入这个系统入口；当前源码启动器和按键监听尚未完成该注册。[按键设置机制](https://learn.microsoft.com/en-us/windows/client-management/manage-windows-copilot#end-user-settings-for-the-copilot-key)、[第三方应用注册规范](https://learn.microsoft.com/en-us/windows/apps/develop/windows-integration/microsoft-copilot-key-provider)

这段经历定义了项目的出发点：**让现有按键真正通向自己的助手，让自然语言真正连接可执行的电脑任务。** 后续的安装、模型、声音和代理扩展，都应以这条使用流程是否顺畅作为判断标准。
