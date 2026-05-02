# deepxiv-sdk

**DeepXiv 是一个专为 agent 设计的论文搜索与渐进式阅读工具。**

安装完 `pip` 包即可直接使用，CLI 会在首次调用时自动申请 token 并保存，不需要你先折腾额外配置。

- **📚 API 文档**: [https://data.rag.ac.cn/api/docs](https://data.rag.ac.cn/api/docs)
- **🎥 演示视频**: [![Watch Demo](https://img.shields.io/badge/YouTube-Watch%20Demo-red)](https://youtu.be/atr71CbQybM)
- **📄 技术报告**: [![arxiv](https://img.shields.io/badge/arXiv-2603.00084-b31b1b)](https://arxiv.org/abs/2603.00084)
- **📖 English Docs**: [README.md](README.md)

## DeepXiv 是什么

DeepXiv 围绕 agent 最关键的两类论文工作流构建：

1. **搜索 + 渐进式内容访问**
2. **热点发现 + 热度信号**

它的核心思想不是一上来就盲读全文，而是让 agent 根据 token 预算和任务价值，按层读取内容。

## 快速开始

```bash
pip install deepxiv-sdk
```

首次使用时，deepxiv 会自动注册一个免费 token，并保存到 `~/.env`：

```bash
deepxiv search "agentic memory" --limit 5
```

如果你想安装完整能力，包括 MCP 和内置 research agent：

```bash
pip install "deepxiv-sdk[all]"
```

## CLI First 工作流

CLI 是 DeepXiv 的主入口。DeepXiv 的目标，是让 agent 像真正做研究的人一样工作：先搜、再筛、再精读最值钱的部分。

```bash
deepxiv search "agentic memory" --limit 5
deepxiv paper 2603.21489 --brief
deepxiv paper 2603.21489 --head
deepxiv paper 2603.21489 --section Analysis
```

渐进式阅读里最核心的是三把刀：

- `--brief`：先判断这篇 paper 值不值得继续看
- `--head`：快速掌握结构、章节和 token 分布
- `--section`：只读最值钱的部分，比如 `Introduction`、`Method`、`Experiments`

这就是 DeepXiv 的核心设计：agent 不应该无脑加载 full paper，除非任务真的需要。

## CLI 功能

### 1. 论文搜索与阅读

```bash
deepxiv search "transformer" --limit 10
deepxiv paper 2409.05591 --brief
deepxiv paper 2409.05591 --head
deepxiv paper 2409.05591 --section Introduction
deepxiv paper 2409.05591
```

### 2. 热点与热度信号

真正做研究的人，不只要“找得到”，还要知道“现在什么最值得看”。

```bash
deepxiv trending --days 7 --limit 30
deepxiv paper 2409.05591 --popularity
```

- `trending` 用社交信号找出最近最热的论文
- `--popularity` 给出单篇 paper 的传播指标，比如 views、tweets、likes、replies

### 3. Web Search

```bash
deepxiv wsearch "karpathy"
deepxiv wsearch "karpathy" --json
```

说明：

- `deepxiv wsearch` 调用 DeepXiv 的 web search 接口
- 每次 `wsearch` 会消耗 **20 limit**
- 注册 token 默认每天有 **10,000 limit**，大致相当于每天可用 **500 次 web search**

### 4. 基于 Semantic Scholar ID 的元数据读取

```bash
deepxiv sc 258001
deepxiv sc 258001 --json
```

`deepxiv sc` 可以基于 Semantic Scholar paper ID 获取元数据。

说明：

- 当你的工作流已经持有 Semantic Scholar ID 时，这个命令会很有用
- DeepXiv **很快会提供 Semantic Scholar 搜索服务**，直接返回 Semantic Scholar ID

### 5. 生物医学论文

```bash
deepxiv pmc PMC544940 --head
deepxiv pmc PMC544940
```

### 6. bioRxiv & medRxiv 预印本

> ⚠️ **Beta**：bioRxiv 和 medRxiv 功能目前正在测试优化中。
> 如需使用，请直接从源码安装：
> ```bash
> pip install git+https://github.com/qhjqhj00/deepxiv_sdk.git
> ```

```bash
# 搜索
deepxiv search "protein design" --biorxiv --limit 5
deepxiv search "Alzheimer" --medrxiv --date-from 2024-01

# 通过 DOI 获取单篇论文
deepxiv biorxiv 10.1101/2021.02.26.433129
deepxiv biorxiv 10.1101/2021.02.26.433129 --format text
deepxiv biorxiv 10.1101/2021.02.26.433129 --section Introduction,Methods
deepxiv biorxiv 10.1101/2021.02.26.433129 --roc --roc-num 5

deepxiv medrxiv 10.1101/2025.08.11.25333149
deepxiv medrxiv 10.1101/2025.08.11.25333149 --format text

# 也可以在 paper 命令上加 --biorxiv / --medrxiv flag
deepxiv paper 10.1101/2021.02.26.433129 --biorxiv
deepxiv paper 10.1101/2021.02.26.433129 --biorxiv --section Introduction
```

## Example Agent Workflows

### Workflow 1：跟踪近期热点论文

```bash
deepxiv trending --days 7 --limit 30 --json
```

然后 agent 可以：

1. 对每篇论文跑 `--brief`
2. 对最值得看的几篇跑 `--head`
3. 只读取关键 section
4. 自动生成一份 report，而不需要手动翻几十篇 paper

这个 workflow 已经写成可复用 skill，可直接使用：[skills/deepxiv-trending-digest/SKILL.md](skills/deepxiv-trending-digest/SKILL.md)

### Workflow 2：进入一个新研究方向

```bash
deepxiv search "agentic memory" --date-from 2026-03-01 --limit 100 --format json
```

然后 agent 可以：

1. 批量 brief 候选论文
2. 优先保留带 GitHub 的论文
3. 用 `--head` 定位实验章节
4. 读取 `Experiments` / `Results`
5. 把数据集、指标和分数整理成 baseline table

这个 workflow 也已经写成可复用 skill：[skills/deepxiv-baseline-table/SKILL.md](skills/deepxiv-baseline-table/SKILL.md)

## 内置 Deep Research Agent

如果你不想自己拼工作流，CLI 里已经内置了一个 research agent。

```bash
pip install "deepxiv-sdk[all]"
deepxiv agent config
deepxiv agent query "What are the latest papers about agent memory?" --verbose
```

如果你已经有自己的 agent 系统，也可以直接接入 DeepXiv CLI skill，保留自己的 orchestration。

## Agent 集成

DeepXiv 设计上就适合接入 Codex、Claude Code、OpenClaw 以及类似的 agent runtime。

### MCP Server

添加到 Claude Desktop MCP 配置文件：

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

**Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

**Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "deepxiv": {
      "command": "deepxiv",
      "args": ["serve"],
      "env": {
        "DEEPXIV_TOKEN": "your_token_here"
      }
    }
  }
}
```

### CLI Skill

```bash
mkdir -p $CODEX_HOME/skills
ln -s "$(pwd)/skills/deepxiv-cli" $CODEX_HOME/skills/deepxiv-cli
```

对于不支持原生 skill 的框架，可以直接把 [skills/deepxiv-cli/SKILL.md](skills/deepxiv-cli/SKILL.md) 当作操作指令加载。

## Python 使用

```python
from deepxiv_sdk import Reader

reader = Reader()

results = reader.search("agent memory", size=5)
brief = reader.brief("2409.05591")
head = reader.head("2409.05591")
intro = reader.section("2409.05591", "Introduction")

web = reader.websearch("karpathy")
sc_meta = reader.semantic_scholar("258001")
```

## Roadmap

DeepXiv 的目标，是逐步成为一个 **亿级 academic paper data interface**。

路线图是：

1. **arXiv 全量覆盖 + T+1 自动更新**
2. **anyXiv 覆盖**，包括 bioRxiv、medRxiv 等
3. **全量开放获取（OA）文献覆盖**

在元数据层，DeepXiv 会越来越多地使用 **Semantic Scholar metadata 作为基础元数据骨架**，并持续扩展覆盖面和元数据质量。

## 当前覆盖范围

- ✅ **arXiv** - 当前主要数据源
- ✅ **PubMed Central (PMC)** - 生物医学与生命科学
- 🧪 **bioRxiv / medRxiv** - 生物学 & 医学预印本 *（Beta，需从源码安装）*
- 🔄 **Semantic Scholar 元数据接入** - 作为基础元数据层持续扩展

> DeepXiv 专注于开放获取文献，让 agent 能基于可直接访问的论文数据工作，而不是被订阅墙卡住。

## 完整 API 参考

### 搜索与查询

```python
reader.search(query, size=10, search_mode="hybrid", categories=None, min_citation=None)
reader.websearch(query)            # Web 搜索（每次消耗 20 limit）
reader.semantic_scholar(sc_id)     # 通过 Semantic Scholar ID 查询元数据
reader.head(arxiv_id)              # 论文元数据与章节概览
reader.brief(arxiv_id)             # 快速摘要（标题、TLDR、关键词、引用数、GitHub 链接）
reader.section(arxiv_id, section)  # 读取特定章节
reader.raw(arxiv_id)               # 完整论文
reader.preview(arxiv_id)           # 论文预览（约 10k 字符）
reader.json(arxiv_id)              # 完整结构化 JSON
```

### PMC（生物医学论文）

```python
reader.pmc_head(pmc_id)            # PMC 论文元数据
reader.pmc_full(pmc_id)            # 完整 PMC 论文 JSON
```

### bioRxiv / medRxiv *（Beta）*

> 需从源码安装后方可使用。

```python
reader.biomed_search(query, source="biorxiv", top_k=10)   # 搜索预印本
reader.biomed_data(source_id, source="biorxiv")           # 通过 DOI 获取元数据
reader.biomed_data(source_id, source="biorxiv", data_type="section", section_names=["Introduction"])
reader.biomed_data(source_id, source="medrxiv", data_type="roc", roc_num=5)
```

### Agent（可选）

```python
from deepxiv_sdk import Agent

agent = Agent(api_key="your_openai_key", model="gpt-4")
answer = agent.query("最近关于 agent memory 的论文有哪些？")
print(answer)
```

## Token 管理

deepxiv 支持 4 种方式配置 token：

**1. 自动注册（推荐）** - 首次使用时自动创建并保存
```bash
deepxiv search "agent"
```

**2. 使用 config 命令**
```bash
deepxiv config --token YOUR_TOKEN
```

**3. 环境变量**
```bash
export DEEPXIV_TOKEN="your_token"
```

**4. 命令行参数**
```bash
deepxiv paper 2409.05591 --token YOUR_TOKEN
```

**提高日限额**：默认 10,000 请求/天。需要更高限额，请访问 [https://data.rag.ac.cn/register](https://data.rag.ac.cn/register)。

### 免费测试论文

这些论文无需 token 即可访问：

**arXiv**: `2409.05591`, `2504.21776`

**PMC**: `PMC544940`, `PMC514704`

## MCP 工具

使用 MCP Server 时可用的工具：

| 工具 | 说明 |
|------|------|
| `search_papers` | 搜索 arXiv 论文 |
| `get_paper_brief` | 快速摘要 |
| `get_paper_metadata` | 完整元数据 |
| `get_paper_section` | 读取特定章节 |
| `get_full_paper` | 完整论文 |
| `get_paper_preview` | 论文预览 |
| `get_pmc_metadata` | PMC 论文元数据 |
| `get_pmc_full` | 完整 PMC 论文 |

## Agent 使用（可选）

内置的 ReAct agent 可以自动搜索论文、读取内容并进行多轮推理：

```python
from deepxiv_sdk import Agent

agent = Agent(
    api_key="your_deepseek_key",
    base_url="https://api.deepseek.com/v1",
    model="deepseek-chat"
)

answer = agent.query("比较 transformer 和 attention mechanism 的关键想法")
print(answer)
```

或者通过 CLI：

```bash
deepxiv agent config  # 配置 LLM API
deepxiv agent query "最近关于 agent memory 的论文有哪些？" --verbose
```

## 错误处理

deepxiv 提供了具体的异常类型：

```python
from deepxiv_sdk import (
    Reader,
    AuthenticationError,  # 401 - 无效或过期的 token
    RateLimitError,       # 429 - 达到日限额
    NotFoundError,        # 404 - 论文未找到
    ServerError,          # 5xx - 服务器错误
    APIError              # 其他 API 错误
)

try:
    paper = reader.brief("2409.05591")
except AuthenticationError:
    print("请更新你的 token")
except RateLimitError:
    print("已达到日限额")
except NotFoundError:
    print("论文未找到")
except APIError as e:
    print(f"API 错误: {e}")
```

## 常见问题

**Q: 我需要 token 才能使用吗？**
A: 不一定。部分论文无需 token 即可访问，但大多数完整功能需要 token。首次使用时 CLI 会自动注册。

**Q: 搜索最多返回多少结果？**
A: 每次最多 100 条。更大的结果集请用 `offset` 做分页。

**Q: 如何处理超时？**
A: `Reader` 默认会自动重试（指数退避）。你也可以自定义：

```python
reader = Reader(timeout=120, max_retries=5)
```

**Q: agent 支持哪些模型？**
A: 支持任何 OpenAI 兼容 API，例如 OpenAI、DeepSeek、OpenRouter、本地 Ollama 等。

## 示例

查看 [examples/](examples/) 目录：

- `quickstart.py` - 5 分钟快速开始
- `example_reader.py` - Reader 基础使用
- `example_agent.py` - Agent 使用
- `example_advanced.py` - 高级模式
- `example_error_handling.py` - 错误处理示例

## 许可证

MIT License，见 [LICENSE](LICENSE)

## 支持

- 🐛 **GitHub Issues**: [https://github.com/qhjqhj00/deepxiv_sdk/issues](https://github.com/qhjqhj00/deepxiv_sdk/issues)
- 📚 **API 文档**: [https://data.rag.ac.cn/api/docs](https://data.rag.ac.cn/api/docs)
- 📧 **更高限额申请**: [https://data.rag.ac.cn/register](https://data.rag.ac.cn/register)
