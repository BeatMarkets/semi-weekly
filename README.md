# EET-China News Scraper

一个使用 Playwright 和 BeautifulSoup 爬取 EET电子工程专辑 新闻的工具。

## 功能

- **爬取新闻列表**：获取首页或指定页数的新闻列表
- **爬取新闻详情**：获取特定新闻的完整内容、作者信息等

## 安装依赖

```bash
uv sync
```

## 使用方法

### 1. 爬取新闻列表

获取首页的所有新闻：

```bash
uv run python main.py
```

爬取多页新闻（例如3页）：

```bash
uv run python main.py --pages 3
```

### 2. 爬取新闻详情内容

获取首页新闻列表，并爬取每篇文章的完整内容：

```bash
uv run python main.py --fetch-content
```

限制只爬取前 5 篇文章的详情内容：

```bash
uv run python main.py --fetch-content --limit 5
```

结合多页和详情爬取：

```bash
uv run python main.py --pages 2 --fetch-content --limit 10
```

## 命令行参数

- `--pages N`：爬取的页数（默认：1）
- `--delay SECONDS`：页面加载后等待的秒数（默认：0.5）
- `--timeout-ms MS`：导航超时时间，单位毫秒（默认：20000）
- `--headless`：以无头模式运行浏览器（默认：非无头模式）
- `--dump-html FILE`：将首页 HTML 保存到指定文件用于调试
- `--fetch-content`：爬取每篇新闻的完整内容
- `--limit N`：限制爬取内容的新闻数量（仅与 `--fetch-content` 配合使用）

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

新闻列表输出：

```
01. 图赏|CES展上的三代酷睿Ultra笔记本：899克、双屏、游戏本...... (2026-01-09)
    https://www.eet-china.com/news/202601094157.html
02. 谷歌云副总裁跳槽英伟达，担任首位CMO (2026-01-09)
    https://www.eet-china.com/news/202601093048.html
...
```

新闻详情输出：

```
================================================================================
01. 图赏|CES展上的三代酷睿Ultra笔记本：899克、双屏、游戏本......
发布时间: 2026-01-09
作者: 黄烨锋
链接: https://www.eet-china.com/news/202601094157.html
================================================================================
[完整的文章正文内容...]
```

## 开发说明

- 项目使用 `uv` 作为包管理器
- 主要依赖：`beautifulsoup4`、`playwright`、`requests`
- 核心函数位置见 [main.py](main.py)
  - `parse_news_items()`：解析新闻列表
  - `extract_article_content()`：提取文章详情
  - `fetch_news_content()`：爬取单篇文章
  - `fetch_news_contents()`：批量爬取文章详情
