# Rikugan（六眼）

<p align="center">
  <i>一个面向 IDA Pro 和 Binary Ninja 的逆向工程智能体。</i><br>
  <i>A reverse-engineering agent for IDA Pro and Binary Ninja.</i>
</p>

<p align="center">
  <a href="README.md"><b>中文</b></a> ｜
  <a href="docs/README.en.md"><b>English</b></a>
</p>

<p align="center">
  <a href="https://rikugan.reversing.codes/docs.html">📖 文档 / Documentation</a> ｜
  <a href="https://rikugan.reversing.codes/ARCHITECTURE.html">🏗️ 架构 / Architecture</a> ｜
  <a href="https://github.com/buzzer-re/Rikugan/issues">🐛 Issues</a>
</p>

![alt text](../assets/binja_showcase.png)

![alt text](../assets/ida_showcase.png)

[文档](https://rikugan.reversing.codes/docs.html) | [架构](https://rikugan.reversing.codes/ARCHITECTURE.html) | [Issues](https://github.com/buzzer-re/Rikugan/issues)

## 安装

自动检测 IDA Pro、Binary Ninja 或两者同时安装。

**Linux / macOS：**
```bash
curl -fsSL https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.sh | bash
```

**Windows（PowerShell）：**
```powershell
irm https://raw.githubusercontent.com/buzzer-re/Rikugan/main/install.ps1 | iex
```

针对特定主机安装、手动设置及配置，请参阅[文档](https://rikugan.reversing.codes/docs.html)。

## 这是又一个 MCP 客户端吗？

不，Rikugan 是一个构建在逆向宿主内部的 ***智能体***。它不依赖 MCP 服务器来与宿主数据库交互，而是拥有自己的智能体循环、上下文管理、角色提示（[源码](../rikugan/agent/system_prompt.py)），以及进程内工具编排层。

智能体循环基于生成器的轮次循环：每条用户消息启动一个流式输出→执行→重复的流水线，LLM 响应逐 token 流式返回，工具调用被拦截并分发。它支持自动错误恢复、运行中用户提问、多步骤工作流的计划模式，以及消息队列——所有这些无需离开反汇编器即可完成。

这个智能体真正 ***活跃*** 在逆向分析中。

- 无需切换到外部 MCP 客户端
- 助手优先，不会替你完成工作（除非你要求）
- 可扩展至多种 LLM 供应商和本地部署（Ollama）
- 快速启用——只需按 Ctrl+Shift+I 即可打开聊天窗口

## 功能特性

**60+ 工具**，涵盖导航、反编译器、反汇编、交叉引用、字符串、注释、类型、脚本以及宿主编译器中间语言/微码操作。智能体在执行脚本前始终请求许可，绝不会执行目标二进制文件。完整工具参考请见[文档](https://rikugan.reversing.codes/docs.html)。

**探索**——灵感来源于代码智能体的工作方式，但应用于二进制文件。编排器映射二进制文件结构（导入、导出、字符串、关键函数），然后生成独立的子智能体并行分析。每个子智能体汇报结果，编排器综合形成完整分析。

|![alt text](../assets/subagents_example_3.png)|
|:--:|
|编排器并行派生子智能体|

**自然语言补丁**（实验性功能）——`/modify` 让你用自然语言描述所需的修改。Rikugan 会探索二进制文件，构建上下文，然后应用补丁。

|![alt text](../assets/maze_solve.gif)|
|:--:|
|`/modify 让这个迷宫游戏变简单，让我可以穿墙`|

**反混淆**（实验性功能，Binary Ninja）——`/deobfuscation` 技能启动计划模式，识别并移除控制流平坦化、不透明谓词、MBA 表达式和垃圾代码，使用编译器中间语言读写原语实现。

|![](../assets/cff_remove_example.gif)|
|:--:|
|工作流速度提升约 3 倍，原始流程约 4 分 30 秒|

**记忆**——分析结果保存在数据库旁边的 `RIKUGAN.md` 文件中，跨会话持久化。

**技能 & MCP**——内置 12 项技能，支持自定义技能和 MCP 服务器集成。可重用在 Claude Code 和 Codex 中使用的技能和 MCP 服务器。

### 配置文件

配置文件让你能够根据分析需求自定义智能体。你可以精细控制 LLM 可读取的数据、限制其可使用的工具，并定义自定义规则来过滤数据。

![alt text](../assets/profile.png)

## 推荐供应商

| 供应商 | 说明 |
|----------|-------|
| **Claude Opus 4.6** | 整体最佳。推荐使用 Claude Pro/Max 计划的 OAuth 方式，而非 API 密钥。 |
| **Claude Sonnet 4.6** | 性价比高。两款 Anthropic 模型均支持提示缓存。 |
| **MiniMax M2.5 / Highspeed** | 本地测试中与 Opus 相当。限制宽松，成本低廉。 |
| **Gemini 2.5 / 3 / 3.1 Pro** | 效果不错，但幻觉率高于 Anthropic/MiniMax。 |
| **Kimi 2.5** | 编码能力强，但在复杂逆向工程任务中尚不够严谨。 |
| **LLAMA 70B / GPT 120B OSS** | 有趣但尚未达到逆向工程的生产就绪水平。 |

同时支持任何兼容 OpenAI 的端点和 Ollama 本地模型。

## 系统要求

- IDA Pro 9.0+（含 Hex-Rays 反编译器）或 Binary Ninja（UI 模式）
- Python 3.10+
- 至少一个 LLM 供应商
- Windows、macOS 或 Linux

> **IDA Pro + Python >= 3.14：** Shiboken 存在已知的 UAF 漏洞。Rikugan 包含一个变通方案，但 Python 3.10 仍然是最安全的选择。参见[上游报告](https://community.hex-rays.com/t/ida-9-3-b1-macos-arm64-uaf-crash/646)。

## 结语

如果你去年问我如何看待 AI 进行逆向工程，我可能会说"不可能——AI 会产生幻觉，而逆向工程不像写代码那么简单"。但今年，当我看到实际能达成的成果时，我彻底改变了想法。AI 已不再是 2023 年的 ChatGPT，它已经完全不同了。

正因如此，我决定今年投入时间研究这个方向。用智能体编程能做的事情令人惊叹——学习那些以前"没时间"学习的课题，速度快得不真实。

Rikugan 只是我过去三个月构建的众多项目之一。第一个版本在一夜之间完成，两天内就同时支持了 IDA 和 Binary Ninja，三天后基本就是你现在看到的样子，此后只做了小幅调整。

这仍是一个持续改进的项目，还有很多方面有待提升。我尽力确保它不会成为又一个 AI 粗制滥造的项目，但我知道还有很大的成长空间。希望你用它做有意义的事。如果发现 bug、有建议或想要提升生活质量的功能，欢迎提出 issue。
