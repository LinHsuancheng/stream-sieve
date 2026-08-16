# Stream Sieve

Stream Sieve 是一个面向个人的内容过滤和阅读简报系统。它从用户选择的 RSS、网页和浏览器来源中收集文章，保存到本地 SQLite，按用户的长期利益进行可选评分和分析，再把筛选结果生成 HTML/Markdown 简报并通过邮件发送。

它不是一个通用新闻聚合器，也不是把所有来源机械地转发到邮箱。它的目标是减少信息噪音，把有限的注意力留给真正能改变判断、机会、能力、资源、选择权或风险暴露的内容。

## 为什么这样使用

项目把“内容处理”和“邮件发送”分开：

```text
sieve       抓取、解析、去重、入库
score       可选的 LLM 内容评分
analyze     可选的文章结构化分析
brief       按规则挑选并生成简报
send-email  读取已保存结果并发送邮件
```

评分可以随时开启或关闭，不会阻塞采集；邮件发送也不会自动抓取或打分。这样可以单独重跑评分、替换评分原则、调整邮件数量，或者在没有 LLM 时使用已经保存的评分和分析结果发送确定性简报。

## 项目架构

```text
sources/*.yaml
       │
       ▼
  sieve / pipeline.py ──────► SQLite
       │                         │
       ├── score / llm_scorer.py │
       ├── analyze / analyze.py │
       │                         │
       └─────────────────────────┘
                                 │
                       brief / digest.py
                                 │
                   Markdown + HTML renderer
                                 │
                       send-email / delivery
```

主要目录：

```text
stream_sieve/
  cli.py                  CLI 入口
  pipeline.py             来源发现、抓取、解析和同步
  storage.py              SQLite schema 和数据访问
  models.py               Article、ItemRef 等数据模型
  llm_scorer.py           批量内容评分和评分结果解析
  analyze.py              文章分析和结构化摘要
  digest.py               简报合成和 Markdown 输出
  render/html.py          固定 HTML 模板和渲染器
  source_pool.py          来源质量、字段和标签元数据
  relevance.py            本地关键词预筛选
  browser/                Chrome CDP 浏览器后端
  delivery/               SMTP 和本地文件发送后端

prompts/                  LLM prompt
sources/                  来源定义
configs/                  发送配置和运行配置示例
scripts/                  完整运行、测试和环境检查脚本
```

## 安装

要求：

- Linux 或 WSL
- Python 3.11+
- Google Chrome/Chromium；需要登录的来源使用 Chrome profile
- 如果使用浏览器来源，需要能通过 CDP 连接 Chrome
- 如果评分或生成简报，需要一个 OpenAI-compatible API

创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt

# 安装项目 CLI（editable，全局可用）
.venv/bin/python -m pip install -e .

# 让 stream-sieve 出现在当前 shell 的 PATH 中
source .venv/bin/activate
```

复制环境变量模板：

```bash
cp .env.example .env
```

在 `.env` 中填写 LLM key。支持以下任一变量：

```bash
STREAM_SIEVE_LLM_API_KEY=...
# 或 DEEPSEEK_API_KEY / OPENAI_API_KEY
```

运行环境检查：

```bash
.venv/bin/python scripts/check_phase0.py
```

`.env`、本地 SMTP 配置、SQLite 数据库和虚拟环境都不应提交到 Git。

## 快速开始

### 只采集内容

`sieve` 只抓取并写入 SQLite，不调用 LLM，也不发送邮件：

```bash
.venv/bin/python -m stream_sieve.cli sieve \
  sources/blog-openai-blog.yaml \
  sources/blog-anthropic-news.yaml \
  --db ~/.stream-sieve/stream-sieve.db \
  --limit 10
```

### 可选评分

对尚未评分的文章执行 LLM 评分：

```bash
.venv/bin/python -m stream_sieve.cli score \
  --db ~/.stream-sieve/stream-sieve.db \
  --limit 50 \
  --interests interests.md
```

项目也支持使用 `--field`、`--field-profile`、`--categories` 和来源池对不同领域分别评分。评分规则在 [prompts/score.md](prompts/score.md)，输出协议必须保持英文 JSON 字段，因为代码会直接解析这些字段。

### 可选文章分析

```bash
.venv/bin/python -m stream_sieve.cli analyze \
  --db ~/.stream-sieve/stream-sieve.db \
  --min-score 7 \
  --limit 30
```

分析结果会保存到 SQLite，供后续简报重复使用。

### 预览简报

```bash
.venv/bin/python -m stream_sieve.cli brief \
  --db ~/.stream-sieve/stream-sieve.db \
  --min-score 7 \
  --output /tmp/stream-sieve-brief.md
```

这一步只生成简报，不发送邮件。

### 发送邮件

先复制并填写发送配置：

```bash
cp configs/delivery.gmail.example.yaml configs/delivery.gmail.yaml
```

然后发送：

```bash
.venv/bin/python -m stream_sieve.cli send-email \
  --config configs/delivery.gmail.yaml \
  --db ~/.stream-sieve/stream-sieve.db \
  --min-score 7
```

`send-email` 会根据 score、category limits、source pool 和 delivery 状态选择文章。发送成功后写入 `deliveries`，后续运行默认跳过已经发送的文章。使用 `--resend` 强制重发，使用 `--delivery-key` 为不同邮箱维护独立发送历史。

如果不希望发送阶段调用 LLM 合成简报：

```bash
.venv/bin/python -m stream_sieve.cli send-email \
  --config configs/delivery.gmail.yaml \
  --no-synthesis
```

## 项目 CLI

项目提供三个一级命令：

```text
./stream-sieve sieve
./stream-sieve send-email
./stream-sieve all
```

它们默认读取 [config.yaml](config.yaml)。也可以指定其他运行配置：

```bash
./stream-sieve all configs/runs/full-email-test.example.yaml --dry-run
```

安装 editable CLI 后，项目外也可以使用同样的命令：

```bash
stream-sieve sieve
stream-sieve send-email
stream-sieve all
```

三个命令分别执行：

```text
sieve       只采集并写入 SQLite
send-email  只读取保存的数据并生成/发送邮件
all         执行完整流程
```

`all` 执行：

```text
启动/连接 Chrome CDP
→ sieve 所有配置来源
→ 按 fields 执行 score
→ 分析达到阈值的文章
→ 生成 brief
→ send-email
→ 输出数据库 status
```

### 错误处理

采集和完整运行采用 soft-error 策略：

- 单篇文章抓取或解析失败：跳过该文章，继续当前来源。
- 单个来源失败：记录 `[ERROR]`，跳过该来源，继续其他来源。
- `score`、`analyze`、`brief` 或 `send-email` 阶段失败：记录错误，继续后续阶段。
- 运行结束时输出失败汇总；如果存在失败，进程返回非零状态，方便定时任务监控，但不会输出长 traceback。

因此一次 WSJ 页面连接失败不会阻止其他来源继续采集，也不会阻止后续阶段运行。

只查看将要执行的命令：

```bash
./stream-sieve all --dry-run
```

使用其他运行配置：

```bash
./stream-sieve all configs/runs/full-email-test.example.yaml --dry-run
```

完整运行配置位于 `configs/runs/`。正式运行前应复制示例发送配置为本地配置，并确认 SMTP 信息和 delivery key。

## 来源和配置

每个来源由 `sources/*.yaml` 定义，包含来源类型、URL、解析方式和可选浏览器设置。`sourcepool.yaml` 为来源补充质量层级、主题和 briefing category；这些信息会传给评分、分析和简报阶段。

常用配置文件：

- `config.yaml`：默认完整运行配置
- `configs/runs/*.yaml`：不同运行场景
- `configs/delivery.example.yaml`：本地文件发送示例
- `configs/delivery.gmail.example.yaml`：SMTP/Gmail 示例
- `sourcepool.yaml`：正式来源池
- `sourcepool.debug.yaml`：调试来源池
- `interests.md`：用户偏好和长期关注方向
- `prompts/*.md`：评分、分析和简报 prompt

需要登录的来源使用独立 Chrome profile。`config.yaml` 中的 `browser_boot.user_data_dir` 指向该 profile；不要把 profile、cookie 或认证文件放入 Git。

## 常用命令

```bash
# 查看状态
.venv/bin/python -m stream_sieve.cli status

# 查看文章
.venv/bin/python -m stream_sieve.cli articles --limit 20

# 查看评分和分析
.venv/bin/python -m stream_sieve.cli scores --limit 20
.venv/bin/python -m stream_sieve.cli analyses --limit 20

# 本地关键词预筛选
.venv/bin/python -m stream_sieve.cli rank --interests interests.md

# 浏览器诊断
.venv/bin/python -m stream_sieve.cli browser inspect --url https://www.zhihu.com
```

`sync`、`sync-many` 和 `send` 仍保留为兼容入口；新脚本和文档统一使用 `sieve` 与 `send-email`。

## 测试和诊断

语法检查：

```bash
.venv/bin/python -m compileall -q stream_sieve scripts
```

完整邮件测试脚本：

```bash
cp configs/delivery.gmail.example.yaml configs/delivery.gmail.yaml
scripts/test_full_email_pipeline.sh
```

单来源 WSJ 便捷流程：

```bash
DRY_RUN=1 scripts/run_wsj_pipeline.sh
scripts/run_wsj_pipeline.sh
```

邮件测试会实际发送邮件；只想检查命令时使用 `--dry-run` 或 `DRY_RUN=1`。

## 数据和安全

默认 SQLite 数据库位于：

```text
~/.stream-sieve/stream-sieve.db
```

数据库保存文章、评分、分析和发送记录。它是运行状态，不应提交到 Git。API key、SMTP 密码、Chrome profile 和本地 delivery 配置同样只保存在本机。

## 设计边界

- `sieve` 负责内容进入系统，不负责发送。
- `score` 和 `analyze` 是可选、可重跑的丰富步骤。
- `brief` 负责把数据库内容组织成阅读简报。
- `send-email` 只消费数据库和已有简报结果，不隐式抓取或打分。
- HTML 布局由固定 renderer 控制，LLM 只返回结构化内容。
- LLM 输出协议是项目接口的一部分；修改 prompt 时不要改动 JSON key、字段类型和 category 值。
