# Repository Guidelines

## Project Overview
This is a Python news scraper for EET-China (电子工程专辑) that extracts news articles and their full content using Playwright for browser automation and BeautifulSoup for HTML parsing.

## Project Structure & Module Organization
- `main.py` - Entry point containing all scraping logic, data models, and CLI interface
- `pyproject.toml` - Project metadata and Python dependencies managed with uv
- `README.md` - User documentation in Chinese
- `AGENTS.md` - This guide for agentic coding agents
- `tests/` - Add test files here when introduced (e.g., `tests/test_scraper.py`, `tests/test_parsing.py`)

## Build, Test, and Development Commands

### Environment Setup
```bash
# Install dependencies
uv sync

# Create and activate virtual environment (alternative)
uv venv .venv && source .venv/bin/activate
```

### Running the Application
```bash
# Basic news list scraping
uv run python main.py

# Scrape multiple pages
uv run python main.py --pages 3

# Fetch full article content
uv run python main.py --fetch-content

# Combined: scrape 2 pages, fetch content for first 10 articles
uv run python main.py --pages 2 --fetch-content --limit 10
```

### Testing Commands (when tests are added)
```bash
# Run all tests
pytest

# Run single test file
pytest tests/test_scraper.py

# Run specific test function
pytest tests/test_scraper.py::test_parse_news_items

# Run with coverage
pytest --cov=main tests/

# Run with verbose output
pytest -v
```

### Code Quality Commands (when configured)
```bash
# Format code (if black is added)
black main.py

# Lint code (if ruff is added)
ruff check main.py

# Type checking (if mypy is added)
mypy main.py
```

## Coding Style & Guidelines

### Import Organization
- Standard library imports first, grouped by category
- Third-party imports second (beautifulsoup4, playwright, requests)
- Local imports third (none currently)
- Use `from __future__ import annotations` for forward references
- Import specific classes/functions when possible: `from bs4 import BeautifulSoup`

### Code Formatting & Style
- Use 4-space indentation (PEP 8 standard)
- Maximum line length: 88 characters (Black standard)
- Use f-strings for string formatting
- Prefer type hints for all function parameters and return values
- Use dataclasses for simple data containers (`NewsItem`, `NewsContent`)

### Naming Conventions
- Functions and variables: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE` (e.g., `BASE_URL`, `DEFAULT_USER_AGENT`)
- Private functions: prefix with underscore if not part of public API

### Type Hints
- Use `Optional[T]` for nullable values
- Use `List[T]`, `Iterable[T]` for collections
- Use `tuple[Type1, Type2]` for tuple return types
- Import from `typing` module as needed

### Error Handling
- Use specific exception handling (`PlaywrightTimeoutError`)
- Include descriptive error messages with context
- Return `None` for expected failures (e.g., timeout, parsing errors)
- Use print statements for user-facing error reporting (current pattern)

### Function Design
- Keep functions focused and single-purpose
- Separate I/O operations from parsing logic
- Use keyword-only arguments for optional parameters with `*`
- Include comprehensive docstrings for complex functions
- Use dataclasses for structured return values

### Web Scraping Best Practices
- Always set appropriate user agents and headers
- Include delays between requests to be respectful
- Handle timeouts gracefully
- Use multiple CSS selectors as fallbacks for robust parsing
- Clean HTML by removing script/style tags before text extraction
- Use `urljoin()` for resolving relative URLs

### Constants and Configuration
- Define URLs and user agents as module-level constants
- Use sensible defaults for timeouts and delays
- Make browser configuration consistent across functions
- Use locale and viewport settings for realistic browsing

## Testing Guidelines

### Test Structure
- Place tests in `tests/` directory with `test_*.py` naming
- Mirror the main module structure in test organization
- Use descriptive test names that explain the scenario

### Testing Approach
- Use `pytest` as the testing framework
- Mock network calls for deterministic testing
- Test parsing functions with sample HTML fixtures
- Test error handling paths (timeouts, malformed HTML)
- Use fixtures for common test data (NewsItem, NewsContent)

### Test Data Management
- Store sample HTML responses in `tests/fixtures/`
- Create test data for different article formats
- Test edge cases (missing dates, authors, content)
- Validate URL handling and joining

## Dependencies & Package Management
- Use `uv` for package management
- Add dependencies with `uv add <package>` (do not edit pyproject.toml manually)
- Current dependencies: `beautifulsoup4>=4.12.0`, `playwright>=1.57.0`, `requests>=2.32.0`
- Keep dependencies pinned to minimum required versions
- Document any new dependencies in this AGENTS.md file

## Development Workflow
1. Make changes to code
2. Test manually with `uv run python main.py`
3. Add tests if functionality is new or changed
4. Run test suite if tests exist
5. Update documentation if needed

## Commit & Pull Request Guidelines
- Use clear, imperative commit messages (e.g., "Add article content parsing")
- Include testing notes in PR descriptions
- Document any breaking changes or new requirements
- Reference relevant issues if they exist

## Security & Performance Notes
- Never commit API keys or credentials
- Use appropriate timeouts for network operations
- Consider rate limiting when making many requests
- Validate and sanitize extracted content
- Use headless mode for production/CI environments

## Debugging & Development Tips
- Use `--dump-html` flag to save HTML for debugging parsing issues
- Set `headless=False` to watch browser behavior during development
- Use print statements for progress tracking (current pattern)
- Test with different article formats and edge cases
- Consider adding logging for better debugging in production

## Future Improvements
- Add proper logging configuration
- Implement caching for fetched content
- Add configuration file support
- Create proper test suite with fixtures
- Add code formatting and linting tools
- Consider async/await for concurrent fetching