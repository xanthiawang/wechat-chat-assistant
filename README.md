# 微信聊天助手 · WeChat Chat Assistant

**把本机微信聊天接到一个可以对话、每天发简报的私人助手。**

[下载 v0.1.0 Beta](https://github.com/xanthiawang/wechat-chat-assistant/releases/tag/v0.1.0)
· [安装与恢复](docs/RECOVERY.md) · [隐私与安全](SECURITY.md)

## 能做什么

- 在个人微信的 ClawBot 会话中提问，检索本机已同步的聊天文字。
- 每天北京时间 **09:00 开始生成**前一天的简报，处理完成后发给本人。
- 整理待回复、承诺、日程、科研／项目／商务进展，引用会话和时间。
- 全部可读文本分批处理；明确统计未解析的非文本消息。
- 只读数据库，模型只能调用一个受限历史查询工具。

## 安装

### 双击引导安装

1. 在 Releases 下载 `wechat-chat-assistant-v0.1.0.zip`，解压。
2. 打开 `Install.command`，跟随终端向导。
3. 登录自己的 ChatGPT/Codex 订阅，微信扫码，再给机器人发送“你好”。
4. 完成微信官方备份、保存草稿并正常退出微信；本人明确同意后初始化读取。
5. 确认原版微信正常，向导验证真实数据库、模型检索和完整简报试发，最后启用09:00任务。

这是未签名的终端安装器，macOS可能阻止双击运行；本项目不提供关闭系统安全保护的办法。首次安装需要 [Homebrew](https://brew.sh) 和 Apple Command Line Tools（`xcode-select --install`）。依赖安装可能需要等待或本人操作。

### 一条命令启动向导

在终端下载固定版本的安装脚本；执行前可以打开检查：

```bash
curl -fL https://github.com/xanthiawang/wechat-chat-assistant/releases/download/v0.1.0/install.sh -o /tmp/wechat-assistant-install-v0.1.0.sh && bash /tmp/wechat-assistant-install-v0.1.0.sh
```

脚本只下载固定 `v0.1.0` 发布包并校验内置 SHA256，然后启动同一个向导。
**“一键”指启动引导安装，微信扫码、模型授权和聊天读取授权不能替用户自动完成。**

### 已有 OpenClaw：安装历史查询插件

插件源码在 [`plugin/`](plugin/)。它需要本项目的本机读取适配器和经过真实验证的 `reader-config.json`，不是装上插件就能解密聊天。只在专用 profile 内安装；完整向导会完成依赖、隔离和权限配置。

## 支持范围与费用

| 项目 | 当前 Beta |
|---|---|
| 电脑 | Apple Silicon Mac；不支持Windows、Intel Mac、Rosetta |
| 微信 | Mac微信4.x；底层读取曾在4.1.13验证，上游报告4.1.15；其他版本未验证 |
| 数据 | Mac当前已同步数据库中的文字，不保证覆盖手机／云端全部历史 |
| 非文本 | 图片、语音、附件、卡片/XML暂不解析，只计数 |
| 模型 | 本人的ChatGPT/Codex订阅登录，消耗订阅额度；不保证所有订阅或地区均可用 |
| 定时 | Mac开机联网且后台服务可用；09:00触发，处理需要几分钟 |
| 发送 | 仅发送给主人；不自动回复其他联系人或群聊 |

项目代码免费、MIT开源。订阅本身可能收费，额度和可用模型由提供方决定。
聊天文字会发送到用户授权的OpenAI服务进行总结／问答，**不是完全本地AI**。

## 数据与隔离

- 程序和私人数据：`~/.local/share/wechat-chat-assistant/`。
- 独立 OpenClaw profile：`wechat-chat-assistant`，状态在 `~/.openclaw-wechat-chat-assistant/`。
- 只绑定本机回环地址，安装时选择空闲端口；不开放公网。
- 密钥和聊天不打包、不上传GitHub。私人目录700，敏感文件600。
- 初始化会复制并临时重签名微信副本以获取本人数据库密钥，可能需要手机确认，存在兼容性与账号检测风险。仅在本人明确同意后运行。
- 原版微信不重签名，SIP不改变。正常卸载仅停服务并保留数据。

## 运行与恢复

```bash
# 替换 python3.14 为安装时使用的 Python 3.14+ 路径
python3.14 ~/.local/share/wechat-chat-assistant/app/setup.py doctor
python3.14 ~/.local/share/wechat-chat-assistant/app/setup.py connect
python3.14 ~/.local/share/wechat-chat-assistant/app/setup.py reader
python3.14 ~/.local/share/wechat-chat-assistant/app/setup.py verify
python3.14 ~/.local/share/wechat-chat-assistant/app/setup.py enable
python3.14 ~/.local/share/wechat-chat-assistant/app/setup.py uninstall
```

读取失败不会伪造空简报；发送回执不确定时停止自动重发，先检查微信。
官方微信备份保留原状，但备份完成不等于助手已经能读取它。

## 验证状态

- 核心流程已在作者本人真实微信数据上验证：只读数据库、订阅模型检索、完整文字简报与主人通道发送。
- 发布包完成语法、来源哈希、依赖锁和隐私隔离静态检查。
- **尚未在另一台全新Mac上完成完整安装验收。此版本为Beta，不保证一键成功。**
- 不使用生成／虚构的聊天或统计数据进行功能演示或测试。

维护者：[Zixin Wang](https://github.com/xanthiawang)。
第三方来源及许可证见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
