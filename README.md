# EET-China News Scraper

一个使用 Playwright 和 BeautifulSoup 爬取 EET电子工程专辑 新闻的工具。

## 功能

- **爬取新闻列表**：获取首页或指定页数的新闻列表
- **爬取新闻详情**：抓取每篇文章的正文/作者等信息（默认启用）
- **Qwen 处理**：对每篇新闻输出产业链单标签分类 + 中文客观摘要（优先 1 句，允许 1-3 句），并写入 `jsonl`

## 安装依赖

```bash
uv sync
```

## 使用方法

### 1. 环境变量

- `OPENAI_API_KEY`：必填
- `OPENAI_BASE_URL`：可选；默认 `https://dashscope.aliyuncs.com/compatible-mode/v1`

### 2. 端到端：爬取 + Qwen 处理 + 输出 jsonl

默认 headful（因为某些环境下 headless 不可用），输出 `out.jsonl`：

```bash
python main.py --pages 2 --limit 20 --model qwen-plus --out out.jsonl
```

如需启用 headless：

```bash
python main.py --pages 2 --limit 20 --model qwen-plus --out out.jsonl --headless
```

## 命令行参数

- `--pages N`：爬取的页数（默认：1）
- `--limit N`：最多处理多少篇新闻（默认：20）
- `--out PATH`：输出 `jsonl` 路径（默认：`out.jsonl`）
- `--model NAME`：模型名（默认：`qwen-plus`）
- `--delay SECONDS`：页面加载后等待的秒数（默认：0.5）
- `--timeout-ms MS`：导航超时时间，单位毫秒（默认：20000）
- `--max-retries N`：LLM 调用重试次数（默认：3）
- `--headless`：以无头模式运行浏览器（默认：非无头模式）

## 数据结构

### NewsItem

列表中的每条新闻：

- `title`：新闻标题
- `url`：新闻链接
- `date`：发布日期（可选）

### NewsContent

爬取的完整新闻内容：

- `title`：新闻标题
- `url`：新闻链接
- `date`：发布日期
- `content`：文章正文内容
- `author`：作者信息（可选）
- `source`：新闻来源（固定为"EET-China"）

## 示例输出

输出为 `jsonl`（每行一个 JSON 对象），示例：

```json
{"title":"...","url":"...","date":"...","author":"...","source":"EET-China","content":"...","category":"设备","summary_zh":"...","model":"qwen-plus","created_at":"2026-01-12T00:00:00+00:00","llm_base_url":"https://dashscope.aliyuncs.com/compatible-mode/v1"}
```

## 开发说明

- 依赖：`beautifulsoup4`、`playwright`、`openai`
- 如遇到 Playwright 报错缺浏览器，可执行：

```bash
python -m playwright install chromium
```

- 运行单测：

```bash
python -m unittest discover -s tests -p "test_*.py"
```
