# EET-China News Tracker

一个用于长期追踪半导体产业链信息的工具：

- Playwright 抓取 EET电子工程专辑新闻
- LLM（OpenAI 兼容接口，默认 DashScope/Qwen）做单标签分类 + 中文客观摘要
- 本地 SQLite 持久化（去重 + review 状态 + 可编辑）
- review 完成后生成全年周度汇总 `report.html`

## 安装依赖

```bash
uv sync
```

如遇到 Playwright 缺浏览器，可执行：

```bash
python -m playwright install chromium
```

## 环境变量

- `OPENAI_API_KEY`：必填（用于 `llm` / `run`）
- `OPENAI_BASE_URL`：可选；默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`

## 数据存储

默认使用 `data/semi_weekly.db`（SQLite）。仓库已在 `.gitignore` 忽略 `data/`，建议作为本地长期数据保存。

## 推荐工作流（每周）

1) 同步 + 抓正文 + 跑 LLM（默认只抓 1 页列表；`--limit` 只作用于 fetch/llm）：

```bash
uv run python main.py run --db data/semi_weekly.db --pages 1 --limit 20 --model qwen-plus
```

2) Web 界面 review（推荐，支持内联编辑 + 高亮 pending）：

```bash
uv run uvicorn web_review:app --reload
```

打开：`http://127.0.0.1:8000/?db=data/semi_weekly.db&year=2026`

3) 生成全年周报（只包含已 review 的条目）：

```bash
uv run python report.py --db data/semi_weekly.db --out report.html --year 2026
```

## 命令说明

### 1) `sync`

仅抓取新闻列表并入库（按 `url` 去重，新条目自动标记为 `pending`）：

```bash
uv run python main.py sync --db data/semi_weekly.db --pages 1
```

### 2) `fetch`

仅抓取正文（只处理 DB 里 `content` 为空的条目）：

```bash
uv run python main.py fetch --db data/semi_weekly.db --limit 20
```

### 3) `llm`

仅对“已抓正文但还没跑过 LLM”的条目做分类+摘要：

```bash
uv run python main.py llm --db data/semi_weekly.db --limit 20 --model qwen-plus
```

## 测试

```bash
python -m unittest discover -s tests -p "test_*.py"
```
