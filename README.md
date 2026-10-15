# 微信聊天助手 · WeChat Chat Assistant

**把本机微信聊天接到一个可以对话、每天发简报的私人助手。**

[下载 v0.1.0 Beta](https://github.com/xanthiawang/wechat-chat-assistant/releases/tag/v0.1.0)
· [安装与恢复](docs/RECOVERY.md) · [隐私与安全](SECURITY.md)

## 能做什么

- 在个人微信的 ClawBot 会话中提问，检索本机已同步的聊天文字。
- 主分支每天北京时间 **08:40 提前生成、09:00 尝试投递**前一天的简报；失败通知本人。
- 整理待回复、承诺、日程、科研／项目／商务进展，引用会话和时间。
- 全部可读文本分批处理；明确统计未解析的非文本消息。
- 只读微信源数据库；模型可查询历史和维护本机、带来源的记忆。
- 主分支新增持续记忆：按联系人检索语气、关联修改后的真实回复、维护带来源的关系候选。v0.1.0发布包尚不包含此功能。

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
| 定时 | Mac开机联网且后台服务可用；主分支08:40准备、09:00投递，离线或未准备好时不能保证准点 |
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

## 主分支持续学习（2026-10-14）

采用本机SQLite，无常驻图数据库、向量库或本地大模型。首次索引最近14天可读文字，之后每次处理至多3000条新记录。晨报08:40生成、09:00只投递经过哈希核对的已准备文本。独立学习任务每天05:30、11:30、17:30、23:30运行，单次上限4分钟；08:00–10:00避让晨报，晨报正在处理时跳过。每次增量同步后更新最多120条真实本人语气样本，再提取关系候选。每次关系提取至多最近24小时80条文字、12个候选。事实附消息来源，模型推断标为candidate。缓存可能因撤回、删除或编辑过时，回复前核对实时history。

回复前助手检索同一联系人的本人表达，先记录immutable draft_id。独立学习检查草稿后30分钟内同一联系人的首条本人消息，排除竞争草稿、已记录来源和原样生成文本；核对实时数据库后记录为修改候选。你也可以说“这条是我改过的回复，记住这个改法”，明确关联真实source。原样发送的助手草稿排除。本人发出不证明原创，观察到的修改保留为候选，尚未验证首次真实人工修改回流。

私人SQLite、草稿、关系和学习样本保留本机memory目录，GitHub仅通用代码。语义提取和问答仍使用已授权的模型服务，相关文字发给该服务；本地存储不等于完全本地推理。已有技能的方法已适配到docs/SOUL.md，不执行继承的外部账号、目录或WeFlow脚本。
# 本机待办与早报

当前源码支持在账户绑定的本机 SQLite 中保存有来源的待办，区分本人行动、等待对方、待确认。
已导入事项可在主人微信会话说“查看待办”“完成 T001”“恢复 T001”（替换实际编号）。
直接命令 `/todo list`、`/todo done T001`、`/todo reopen T001`、`/todo cancel T001` 无需模型。
完成反馈必须来自当前主人消息，使用精确编号或唯一完整标题；模糊表述先确认。
完成保留审计历史，从后续提醒移除；可查看已完成。不会自动从会议材料或推测中标记完成。
09:00投递时读取任务状态并生成独立确定性提醒，无需模型、同步聊天或关系学习。
聊天简报准备失败不会阻止待办提醒；两者分别记录回执，结果不明时不盲目重发。
电脑需开机联网；同一日首次投递快照之后的修改反映在下一次提醒中。
任务内容、来源文件、关系画像与回执均留本机，不进入GitHub；这些功能位于当前源码，旧发布包未必包含。
