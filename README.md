# PyMidscene

<p align="center">
  <img src="https://midscenejs.com/midscene_with_text_light.png" alt="Midscene Logo" width="300">
</p>

<p align="center">
  <strong>Python SDK for Midscene.js - AI-powered UI automation using natural language</strong>
</p>

<p align="center">
  <a href="https://github.com/AIPythoner/pymidscene/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python"></a>
  <a href="https://midscenejs.com"><img src="https://img.shields.io/badge/docs-midscenejs.com-green.svg" alt="Docs"></a>
</p>

<p align="center">
  <a href="#features">Features</a> |
  <a href="#installation">Installation</a> |
  <a href="#quick-start">Quick Start</a> |
  <a href="#documentation">Documentation</a> |
  <a href="./README_CN.md">中文文档</a>
</p>

---

## What is PyMidscene?

PyMidscene is a Python port of [Midscene.js](https://midscenejs.com) - an AI-powered UI automation framework. It allows you to control web browsers using natural language instead of CSS selectors or XPath.

**No more fragile selectors!** Just describe what you want to click, type, or extract:

```python
# Instead of: page.click("#submit-btn-primary")
await agent.ai_click("the blue Submit button")

# Instead of: page.fill("input[name='email']", "test@example.com")  
await agent.ai_input("email input field", "test@example.com")

# Extract structured data with natural language
result = await agent.ai_query({
    "title": "the page title",
    "price": "the product price as a number"
})
```

## Features

- **Natural Language Automation** - Describe elements in plain English/Chinese, no selectors needed
- **Multi-Model Support** - Works with Doubao, Qwen, GPT-4V, Claude, and other vision LLMs
- **Playwright Integration** - Seamless integration with Playwright for web automation
- **XPath Caching** - Smart caching system compatible with Midscene.js format
- **Visual Reports** - Generate beautiful HTML reports for debugging and sharing
- **Type-Safe** - Full type hints for excellent IDE support

## Installation

```bash
pip install pymidscene

# Install Playwright browsers
playwright install chromium
```

Or with Poetry:

```bash
poetry add pymidscene
playwright install chromium
```

## Quick Start

### 1. Set up your API key

```bash
# For Doubao (recommended for Chinese users)
export MIDSCENE_MODEL_NAME="doubao-seed-1-6-251015"
export MIDSCENE_MODEL_API_KEY="your-api-key"
export MIDSCENE_MODEL_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export MIDSCENE_MODEL_FAMILY="doubao-vision"

# For Qwen
export MIDSCENE_MODEL_NAME="qwen-vl-max"
export MIDSCENE_MODEL_API_KEY="your-api-key"
export MIDSCENE_MODEL_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export MIDSCENE_MODEL_FAMILY="qwen2.5-vl"
```

### 2. Write your automation script

```python
import asyncio
import os
from playwright.async_api import async_playwright
from pymidscene import PlaywrightAgent

async def main():
    # Configure model (or use environment variables)
    os.environ["MIDSCENE_MODEL_NAME"] = "doubao-seed-1-6-251015"
    os.environ["MIDSCENE_MODEL_API_KEY"] = "your-api-key"
    os.environ["MIDSCENE_MODEL_BASE_URL"] = "https://ark.cn-beijing.volces.com/api/v3"
    os.environ["MIDSCENE_MODEL_FAMILY"] = "doubao-vision"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # Create agent with optional caching
        agent = PlaywrightAgent(page, cache_id="my_task")

        # Navigate to page
        await page.goto("https://www.example.com")

        # Use natural language to interact
        await agent.ai_click("the search box")
        await agent.ai_input("search input", "Python automation")
        await agent.ai_click("search button")

        # Extract data
        result = await agent.ai_query({
            "results_count": "number of search results",
            "first_title": "title of the first result"
        })
        print(f"Found: {result}")

        # Assert page state
        await agent.ai_assert("search results are displayed")

        # Generate visual report
        report_path = agent.finish()
        print(f"Report saved to: {report_path}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## Documentation

### Core API

| Method | Description |
|--------|-------------|
| `ai_click(description)` | Click an element described in natural language |
| `ai_input(description, text)` | Type text into an input field |
| `ai_locate(description)` | Locate an element and return its coordinates |
| `ai_query(schema)` | Extract structured data from the page |
| `ai_assert(assertion)` | Assert that a condition is true |
| `finish()` | Generate HTML report and return the path |

### Supported Models

| Model | Family | Provider |
|-------|--------|----------|
| doubao-seed-1-6-251015 | doubao-vision | Bytedance/Volcano |
| qwen-vl-max | qwen2.5-vl | Alibaba |
| gpt-4-vision-preview | openai | OpenAI |
| claude-3-opus | claude | Anthropic |

### Cache System

PyMidscene uses XPath-based caching compatible with Midscene.js:

```yaml
# midscene_run/cache/my_task.cache.yaml
midsceneVersion: 1.0.0
cacheId: my_task
caches:
  - type: locate
    prompt: the login button
    cache:
      xpaths:
        - /html/body/div[1]/button[1]
```

This means:
- Cache files are interchangeable between JS and Python versions
- XPath-based caching works across different window sizes
- Cache invalidation happens automatically when elements move

## Examples

Check out the [examples/](examples/) directory:

- `basic_usage.py` - Getting started
- `login_demo.py` - Login automation with visual report
- `login_demo.html` - Test page for login demo

## Project Structure

```
pymidscene/
├── pymidscene/           # Main package
│   ├── core/             # Core automation logic
│   │   ├── agent/        # Agent implementation
│   │   ├── ai_model/     # AI model integration
│   │   └── dump.py       # Report generation
│   ├── web_integration/  # Browser integrations
│   │   └── playwright/   # Playwright adapter
│   └── shared/           # Shared utilities
├── examples/             # Usage examples
├── tests/                # Test suite
└── docs/                 # Documentation
```

## Related Projects

This is the Python implementation of [Midscene.js](https://midscenejs.com).

- [Midscene.js](https://github.com/web-infra-dev/midscene) - Original JavaScript version
- [Official Documentation](https://midscenejs.com)
- [Awesome Midscene](https://midscenejs.com/awesome-midscene) - Community projects

## Contributing

Contributions are welcome! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
# Development setup
git clone https://github.com/AIPythoner/pymidscene.git
cd pymidscene
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black pymidscene tests
```

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Acknowledgments

- [Midscene.js](https://github.com/web-infra-dev/midscene) - The original JavaScript framework by Bytedance
- [Playwright](https://playwright.dev/) - Browser automation library

---

<p align="center">
  Made with love by the PyMidscene community
</p>
