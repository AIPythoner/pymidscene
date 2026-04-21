# PyMidscene 移植进度

本文档记录从 [Midscene.js](https://github.com/web-infra-dev/midscene) 移植到 Python 的进度，方便后续继续使用 AI 辅助翻译。

---

## 📊 总体进度

| 模块 | 状态 | 说明 |
|------|------|------|
| Core Agent | ✅ 完成 | 核心自动化逻辑 |
| AI Model 调用 | ✅ 完成 | Doubao, Qwen 支持 |
| 缓存系统 | ✅ 完成 | XPath 缓存，与 JS 兼容 |
| Playwright 集成 | ✅ 完成 | Web 自动化 |
| 报告生成 | ✅ 完成 | HTML 可视化报告 |
| Android | ✅ 完成 | `pymidscene.android` (adbutils + ADBKeyboard) |
| iOS | ✅ 完成 | `pymidscene.ios` (WebDriverAgent HTTP) |
| Selenium | 📝 待开发 | 占位文档已创建 |

---

## 📁 JS 与 Python 文件对应关系

这是最重要的参考，帮助 AI 快速定位需要翻译的文件。

### Core 模块

| JS 文件 (packages/core/src/) | Python 文件 (pymidscene/core/) | 状态 |
|------------------------------|--------------------------------|------|
| `agent/agent.ts` | `agent/agent.py` | ✅ |
| `agent/task-cache.ts` | `agent/task_cache.py` | ✅ |
| `ai-model/service-caller.ts` | `ai_model/service_caller.py` | ✅ |
| `ai-model/prompt/*.ts` | `ai_model/prompts/*.py` | ✅ |
| `types.ts` | `types.py` | ✅ |
| `utils.ts` | `shared/utils.py` | ✅ |

### Web Integration 模块

| JS 文件 (packages/web-integration/src/) | Python 文件 | 状态 |
|-----------------------------------------|-------------|------|
| `playwright/page.ts` | `web_integration/playwright/page.py` | ✅ |
| `playwright/agent.ts` | `web_integration/playwright/agent.py` | ✅ |
| `puppeteer/*.ts` | - | ❌ 未移植 |

### 待移植模块

| JS 模块 | Python 目标位置 | 优先级 |
|---------|-----------------|--------|
| `packages/web-integration/src/puppeteer/` | `web_integration/puppeteer/` | 低 |
| `packages/android/` | `android/` | ✅ **已完成** |
| `packages/ios/` | `ios/` | ✅ **已完成** |
| `packages/visualizer/` | - | 低 (可复用 JS 版) |

---

## 🎯 核心 API 对照

| JS API | Python API | 状态 |
|--------|------------|------|
| `agent.aiLocate(desc)` | `agent.ai_locate(desc)` | ✅ |
| `agent.aiClick(desc)` | `agent.ai_click(desc)` | ✅ |
| `agent.aiInput(desc, text)` | `agent.ai_input(desc, text)` | ✅ |
| `agent.aiQuery(schema)` | `agent.ai_query(schema)` | ✅ |
| `agent.aiAssert(assertion)` | `agent.ai_assert(assertion)` | ✅ |
| `agent.aiAction(prompt)` | `agent.ai_action(prompt)` | ❌ 待移植 |
| `agent.aiWaitFor(condition)` | - | ❌ 待移植 |

---

## 🔧 模型支持状态

| 模型 | JS 版本 | Python 版本 | 说明 |
|------|---------|-------------|------|
| Doubao Vision | ✅ | ✅ | 0-1000 归一化坐标 |
| Qwen VL | ✅ | ✅ | 标准像素坐标 |
| OpenAI GPT-4V | ✅ | ⚠️ 部分 | 需要测试 |
| Claude | ✅ | ⚠️ 部分 | 需要测试 |
| Gemini | ✅ | ⚠️ 部分 | 坐标格式 [y1,x1,y2,x2] |

---

## 📝 移植注意事项

### 1. 坐标系统差异

不同模型返回不同格式的坐标，转换逻辑在 `shared/utils.py`:

```python
def adapt_bbox(bbox, width, height, model_family):
    if model_family == "doubao-vision":
        # 归一化 0-1000 -> 像素
        return adapt_doubao_bbox(bbox, width, height)
    elif model_family == "gemini":
        # [y1,x1,y2,x2] -> [x1,y1,x2,y2]
        return adapt_gemini_bbox(bbox, width, height)
    else:
        return bbox
```

### 2. 缓存格式

Python 版本已与 JS 版本缓存格式对齐：

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

### 3. 异步 API

Python 使用 `async/await`，与 JS 类似：

```python
# Python
async def main():
    await agent.ai_click("按钮")

# JS
async function main() {
    await agent.aiClick("按钮");
}
```

---

## 🚀 后续移植建议

### 优先级 1：完善现有功能
- [ ] 添加 `ai_action()` 方法（复杂多步操作）
- [ ] 添加 `ai_wait_for()` 方法（等待条件）
- [ ] 完善 OpenAI/Claude 模型支持

### 优先级 2：新平台支持
- [ ] Selenium WebDriver 集成
- [ ] Android (Appium) 支持
- [ ] iOS 支持

### 优先级 3：工具链
- [ ] CLI 命令行工具
- [ ] YAML 工作流支持
- [ ] pytest 插件

---

## 📞 参考资源

- **JS 源码**: https://github.com/web-infra-dev/midscene
- **官方文档**: https://midscenejs.com
- **Python 仓库**: https://github.com/AIPythoner/pymidscene

---

**最后更新**: 2025-02-05
