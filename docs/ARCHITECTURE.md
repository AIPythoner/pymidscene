# 架构设计 - Architecture

本文档描述 PyMidscene 的架构设计，方便开发者理解代码结构和继续开发。

## 项目结构

```
pymidscene/
├── __init__.py              # 包入口，导出主要 API
├── core/                    # 核心模块
│   ├── agent/               # Agent 实现
│   │   ├── agent.py         # 主 Agent 类
│   │   └── task_cache.py    # 缓存系统（XPath 缓存）
│   ├── ai_model/            # AI 模型集成
│   │   ├── __init__.py      # 模型调用入口
│   │   ├── models/          # 具体模型适配器
│   │   │   ├── doubao.py    # 豆包模型
│   │   │   └── qwen.py      # 千问模型
│   │   └── prompts/         # Prompt 模板
│   │       ├── locator.py   # 元素定位 Prompt
│   │       └── extractor.py # 数据提取 Prompt
│   ├── dump.py              # 执行记录和报告生成
│   ├── report_generator.py  # HTML 报告生成器
│   └── types.py             # 类型定义
├── web_integration/         # Web 集成
│   ├── base.py              # 抽象接口定义
│   └── playwright/          # Playwright 适配器
│       ├── agent.py         # PlaywrightAgent
│       └── page.py          # WebPage 适配器
├── shared/                  # 共享工具
│   ├── logger.py            # 日志系统
│   ├── types.py             # 共享类型
│   ├── utils.py             # 工具函数
│   └── env.py               # 环境变量管理
├── android/                 # Android 支持（待开发）
├── ios/                     # iOS 支持（待开发）
└── webdriver/               # Selenium 支持（待开发）
```

## 核心流程

### 1. AI 定位流程

```
用户调用 ai_click("登录按钮")
    ↓
检查缓存 (XPath)
    ↓ (缓存命中)
通过 XPath 获取元素坐标 → 执行点击
    ↓ (缓存未命中)
截图 → 调用 AI 模型 → 解析 bbox
    ↓
坐标转换 (adapt_bbox)
    ↓
提取 XPath 并缓存
    ↓
执行点击
```

### 2. 缓存系统

缓存文件位置：`./midscene_run/cache/{cache_id}.cache.yaml`

缓存格式（与 JS 版本完全兼容）：
```yaml
midsceneVersion: 1.0.0
cacheId: my_task
caches:
  - type: locate
    prompt: 登录按钮
    cache:
      xpaths:
        - /html/body/div[1]/button[1]
```

### 3. 模型适配

不同模型返回的坐标格式不同：

| 模型 | 坐标格式 | 转换方法 |
|------|----------|----------|
| Doubao | 归一化 0-1000 | `x * width / 1000` |
| Qwen | 像素坐标 | 直接使用 |
| Gemini | [y1, x1, y2, x2] | 交换顺序 |

转换逻辑在 `shared/utils.py` 的 `adapt_bbox()` 函数中。

## 扩展指南

### 添加新模型

1. 在 `core/ai_model/models/` 创建新文件
2. 实现模型调用逻辑
3. 在 `shared/utils.py` 添加坐标转换逻辑
4. 在 `shared/env.py` 添加模型家族配置

### 添加新平台（如 Selenium）

1. 在 `webdriver/` 实现 `AbstractInterface`
2. 实现 `screenshot()`, `click()`, `input_text()` 等方法
3. 实现 `get_element_xpath()`, `get_element_by_xpath()` 方法
4. 创建对应的 Agent 封装

## 与 JS 版本的对应关系

| JS 文件 | Python 文件 |
|---------|-------------|
| `packages/core/src/agent/agent.ts` | `core/agent/agent.py` |
| `packages/core/src/agent/task-cache.ts` | `core/agent/task_cache.py` |
| `packages/web-integration/src/playwright/page.ts` | `web_integration/playwright/page.py` |
| `packages/core/src/ai-model/` | `core/ai_model/` |
