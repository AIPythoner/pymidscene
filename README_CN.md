# PyMidscene

<p align="center">
  <img src="https://midscenejs.com/midscene_with_text_light.png" alt="Midscene Logo" width="300">
</p>

<p align="center">
  <strong>Midscene.js 的 Python SDK - 使用自然语言进行 AI 驱动的 UI 自动化</strong>
</p>

<p align="center">
  <a href="https://github.com/AIPythoner/pymidscene/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue.svg" alt="License"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python"></a>
  <a href="https://midscenejs.com"><img src="https://img.shields.io/badge/docs-midscenejs.com-green.svg" alt="Docs"></a>
</p>

<p align="center">
  <a href="#特性">特性</a> |
  <a href="#安装">安装</a> |
  <a href="#快速开始">快速开始</a> |
  <a href="#文档">文档</a> |
  <a href="./README.md">English</a>
</p>

---

## 什么是 PyMidscene？

PyMidscene 是 [Midscene.js](https://midscenejs.com) 的 Python 版本 - 一个 AI 驱动的 UI 自动化框架。它允许你使用自然语言而不是 CSS 选择器或 XPath 来控制浏览器。

**告别脆弱的选择器！** 只需描述你想要点击、输入或提取的内容：

```python
# 不再需要: page.click("#submit-btn-primary")
await agent.ai_click("蓝色的提交按钮")

# 不再需要: page.fill("input[name='email']", "test@example.com")  
await agent.ai_input("邮箱输入框", "test@example.com")

# 使用自然语言提取结构化数据
result = await agent.ai_query({
    "title": "页面标题",
    "price": "商品价格，数字类型"
})
```

## 特性

- **自然语言自动化** - 用中文/英文描述元素，无需选择器
- **多模型支持** - 支持豆包、千问、GPT-4V、Claude 等视觉大模型
- **Playwright 集成** - 与 Playwright 无缝集成进行网页自动化
- **XPath 缓存** - 与 Midscene.js 格式兼容的智能缓存系统
- **可视化报告** - 生成精美的 HTML 报告用于调试和分享
- **类型安全** - 完整的类型提示，提供优秀的 IDE 支持

## 安装

```bash
pip install pymidscene

# 安装 Playwright 浏览器
playwright install chromium
```

或使用 Poetry：

```bash
poetry add pymidscene
playwright install chromium
```

## 快速开始

### 1. 配置 API 密钥

```bash
# 豆包模型（推荐国内用户使用）
export MIDSCENE_MODEL_NAME="doubao-seed-1-6-251015"
export MIDSCENE_MODEL_API_KEY="your-api-key"
export MIDSCENE_MODEL_BASE_URL="https://ark.cn-beijing.volces.com/api/v3"
export MIDSCENE_MODEL_FAMILY="doubao-vision"

# 千问模型
export MIDSCENE_MODEL_NAME="qwen-vl-max"
export MIDSCENE_MODEL_API_KEY="your-api-key"
export MIDSCENE_MODEL_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"
export MIDSCENE_MODEL_FAMILY="qwen2.5-vl"
```

### 2. 编写自动化脚本

```python
import asyncio
import os
from playwright.async_api import async_playwright
from pymidscene import PlaywrightAgent

async def main():
    # 配置模型（或使用环境变量）
    os.environ["MIDSCENE_MODEL_NAME"] = "doubao-seed-1-6-251015"
    os.environ["MIDSCENE_MODEL_API_KEY"] = "your-api-key"
    os.environ["MIDSCENE_MODEL_BASE_URL"] = "https://ark.cn-beijing.volces.com/api/v3"
    os.environ["MIDSCENE_MODEL_FAMILY"] = "doubao-vision"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # 创建 agent，可选启用缓存
        agent = PlaywrightAgent(page, cache_id="my_task")

        # 导航到页面
        await page.goto("https://www.baidu.com")

        # 使用自然语言进行交互
        await agent.ai_click("搜索输入框")
        await agent.ai_input("搜索框", "Python 自动化")
        await agent.ai_click("百度一下按钮")

        # 提取数据
        result = await agent.ai_query({
            "results_count": "搜索结果数量",
            "first_title": "第一条结果的标题"
        })
        print(f"结果: {result}")

        # 断言页面状态
        await agent.ai_assert("页面显示了搜索结果")

        # 生成可视化报告
        report_path = agent.finish()
        print(f"报告已保存到: {report_path}")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
```

## 文档

### 核心 API

| 方法 | 描述 |
|------|------|
| `ai_click(description)` | 使用自然语言描述点击元素 |
| `ai_input(description, text)` | 在输入框中输入文本 |
| `ai_locate(description)` | 定位元素并返回坐标 |
| `ai_query(schema)` | 从页面提取结构化数据 |
| `ai_assert(assertion)` | 断言某个条件为真 |
| `finish()` | 生成 HTML 报告并返回路径 |

### 支持的模型

| 模型 | 模型家族 | 提供商 |
|------|----------|--------|
| doubao-seed-1-6-251015 | doubao-vision | 字节跳动/火山引擎 |
| qwen-vl-max | qwen2.5-vl | 阿里巴巴 |
| gpt-4-vision-preview | openai | OpenAI |
| claude-3-opus | claude | Anthropic |

### 缓存系统

PyMidscene 使用与 Midscene.js 兼容的基于 XPath 的缓存：

```yaml
# midscene_run/cache/my_task.cache.yaml
midsceneVersion: 1.0.0
cacheId: my_task
caches:
  - type: locate
    prompt: 登录按钮
    cache:
      xpaths:
        - /html/body/div[1]/button[1]
```

这意味着：
- 缓存文件可在 JS 和 Python 版本之间互换使用
- 基于 XPath 的缓存在不同窗口大小下都能正常工作
- 当元素移动时会自动使缓存失效

## 示例

查看 [examples/](examples/) 目录：

- `basic_usage.py` - 入门示例
- `login_demo.py` - 带可视化报告的登录自动化
- `login_demo.html` - 登录演示的测试页面

## 相关项目

本项目是 [Midscene.js](https://midscenejs.com) 的 Python 实现。

- [Midscene.js](https://github.com/web-infra-dev/midscene) - 原版 JavaScript 版本
- [官方文档](https://midscenejs.com)
- [Awesome Midscene](https://midscenejs.com/awesome-midscene) - 社区项目

## 贡献

欢迎贡献！请查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解指南。

```bash
# 开发环境设置
git clone https://github.com/AIPythoner/pymidscene.git
cd pymidscene
pip install -e ".[dev]"

# 运行测试
pytest

# 格式化代码
black pymidscene tests
```

## 许可证

MIT License - 详见 [LICENSE](LICENSE) 文件。

## 致谢

- [Midscene.js](https://github.com/web-infra-dev/midscene) - 字节跳动开发的原版 JavaScript 框架
- [Playwright](https://playwright.dev/) - 浏览器自动化库

---

<p align="center">
  由 PyMidscene 社区用 ❤️ 打造
</p>
