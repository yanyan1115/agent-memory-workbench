# Agent Memory Workbench

[English](README.md) | [简体中文](README.zh-CN.md)

面向 AI Agent 的可审计、文件优先记忆基础设施。

一个 Agent 醒来的时候，并不知道自己记得什么。他得先搜一遍，翻出几条结果，才敢说“我记得”。这套架构把两类记忆分开：开机那一刻要用到的少量事实与规则直接加载，其余细节留给检索。

Agent Memory Workbench 并不是又一次让检索成为记忆中心的尝试。它是一套可以长期维护的分层、可审计架构：持久化 Markdown 记录、轻量热索引、可复核的准入流程、树形导航、可选混合检索、完整性检查，以及安全的跨主机运行方式。

## 为什么

Agent 的活动上下文、会话检查点、对话记录和长期记忆解决的是不同问题。本项目只负责长期记忆；它不替代模型的上下文管理器，也不把自动生成的摘要冒充成权威对话记录。

核心原则：

- Markdown 是权威来源；索引与向量均可重建。
- `MEMORY.md` 是人工维护的轻量热索引，不是完整记忆库。
- 候选信息经过复核后，才成为正式记忆。
- private 记忆默认不进入远程 embedding 或搜索。
- 当前指令、权限与运行状态始终优先于旧记忆。
- 多写入者共享同一个锁域；网络故障时降级为只读。
- 自动召回是可选、受限、不受信任且 fail-open 的适配器。

## 工作方式

### 让新记忆有意识地进入

- 新信息先进入 inbox，而不是直接成为正式记忆。
- 人或 Agent 复核并 promote 有价值的候选；低价值内容可以丢弃，不会悄悄变成永久上下文。

### 启动时已经知道重要的事

- `MEMORY.md` 是适合启动时加载的轻量热索引。每条 pointer 只保留一个有用钩子，并受 200 字符硬预算约束。
- 热索引、自动生成的区域索引、领域 hub 与可选 skills 组成可导航的树；经过校验的 Wiki 链接可以直接连接相关记忆。
- 高频、漏一次代价很大的规则可以进入 skill，并让 skill 描述充当低噪音召回触发器；低频事实仍保留在 Markdown 中，只在需要时打开。

### 需要时才翻找细节

- `memsearch` 将关键词搜索与可选的 Gemini 或 OpenAI-compatible embedding 结合。Markdown 始终是权威来源；没有 API 或向量缓存时，关键词搜索仍可独立工作。
- `memory-recall` 是可选的消息网关适配器，带有时间、长度和 fail-open 限制；不启用它也不影响工作台的完整使用。
- 向量 overlap 复核会找出可能重复或互相矛盾的记忆。相似度只是人工复核的线索，绝不是自动合并或删除的许可。

### 让记忆库长期保持健康

- `memoryctl`：初始化、校验、生成索引、暂存、promote 与 archive 记忆。
- 200 字符热索引硬预算、断链检查、Wiki 链接与标题锚点校验。
- 要求说明原因的更新，以及仅记录 hash 的生命周期审计轨迹。
- `memory-mirror`：经过校验、不可变的只读回退版本。
- NFSv4-over-SSH 部署指南，让多台主机共享一份权威存储。
- 离线 `unittest` 测试集，覆盖隐私与陈旧缓存回归。

## 安装

当前版本支持 POSIX 系统上的 Python 3.10+。

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

## 快速开始

```bash
memoryctl init ./memory

printf '%s\n' 'Use the release checklist before publishing.' > /tmp/body.md
memoryctl candidate --root ./memory \
  --name release-checklist \
  --description 'Release validation conventions.' \
  --type reference \
  --source manual \
  --source-agent example-agent \
  --body-file /tmp/body.md

memoryctl promote --root ./memory \
  inbox/public/release-checklist.md --to active \
  --reason 'Reviewed and approved'
memoryctl doctor --root ./memory
memsearch search --root ./memory 'release validation'
```

关键词搜索不需要 API 或语义缓存。使用 Gemini 语义搜索：

```bash
export EMBEDDING_API_KEY='set this outside shell history'
memsearch index --root ./memory --provider gemini
memsearch search --root ./memory --provider gemini 'release validation'
```

语义缓存默认位于 `$XDG_STATE_HOME/agent-memory-workbench` 或 `~/.local/state/agent-memory-workbench`，处在记忆仓库之外；其中不保存记忆正文的明文。

索引和查询 private 记忆都必须显式 opt-in：

```bash
memsearch index --root ./memory --provider gemini --include-private
memsearch search --root ./memory --provider gemini --include-private 'query'
```

启用前，请确认当前部署可以接受将 private 文本发送给所选的远程 embedding 服务商。

## 记忆布局

```text
memory/
├── MEMORY.md                 # 人工维护的热索引 pointer
├── active/                   # 当前有效的正式公开记忆
├── archive/                  # 正式公开历史记忆
├── private/                  # 正式私密记忆
├── inbox/
│   ├── public/               # 尚未复核的公开候选
│   └── private/              # 尚未复核的私密候选
└── .memory-workbench.lock    # 共享锁域
```

`active/INDEX.md`、`archive/INDEX.md` 与 `private/INDEX.md` 均为自动生成文件，禁止手工编辑。

`memoryctl doctor` 会检查 schema、重复 identity、文件名与 name 是否一致、生成索引是否陈旧、热索引是否断链、热索引单行 200 字符预算、Wiki 链接目标，以及 Wiki 标题锚点。

修改时明确说明原因，并复核不含正文的审计轨迹：

```bash
memoryctl update --root ./memory release-checklist \
  --body-file ./revised.md \
  --reason 'Corrected the release evidence'
memoryctl audit --root ./memory
```

完成语义索引后，可以检查跨文件的高相似度 chunk：

```bash
memsearch overlap --root ./memory --threshold 0.90
```

## 文档

- [架构](docs/architecture.md)
- [数据模型与生命周期](docs/data-model.md)
- [隐私与威胁模型](docs/privacy-and-security.md)
- [可选自动召回](docs/automatic-recall.md)
- [跨主机 NFSv4 over SSH](docs/deployment/nfs-over-ssh.md)
- [Agent Memory skill 模板](docs/memory-skill-template.md)
- [安全策略](SECURITY.md)
- [贡献者](CONTRIBUTORS.md)

## 起源

这套架构来自 Cora、Claude 与 South 在长期真实使用中的共同迭代。Cora 确立并持续校准架构方向，又推动这套私人实践走向开源；Claude 参与演进了记忆库、Memory skill、热索引预算、低噪音召回、inbox、树形 hub、doctor 与 overlap 工作流；South 综合不同实现，完成了公开版架构审计、隐私复核、代码、测试、文档与发布。完整署名见 [CONTRIBUTORS.md](CONTRIBUTORS.md)。

使用 skill 承载可按需加载的长期规则，这一形态参考了对 Codex Desktop 原生记忆行为的转述；本项目未参考 Codex 源码。把 skill 描述本身作为召回触发条件，是本项目自己的设计。

## 测试

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## 项目状态

版本 `0.2.0` 是一套保守的参考实现。它有意不从完整对话记录中自动提取记忆，也不自动解决记忆冲突；这些操作高度依赖判断，应当保持可复核。

## License

MIT
