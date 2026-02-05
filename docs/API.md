# PyMidscene API 文档

PyMidscene 是一个 AI 驱动的浏览器自动化框架，提供智能的元素定位、操作和数据提取能力。

**版本**: 0.1.0
**Python 版本**: 3.10+

---

## 目录

- [快速开始](#快速开始)
- [核心类](#核心类)
  - [Agent](#agent)
  - [WebPage](#webpage)
- [AI 方法](#ai-方法)
  - [ai_locate()](#ai_locate)
  - [ai_click()](#ai_click)
  - [ai_input()](#ai_input)
  - [ai_query()](#ai_query)
  - [ai_assert()](#ai_assert)
- [缓存系统](#缓存系统)
- [执行记录](#执行记录)
- [类型定义](#类型定义)
- [配置选项](#配置选项)
- [最佳实践](#最佳实践)

---

## 快速开始

### 安装

```bash
# 克隆项目
git clone https://github.com/yourusername/pymidscene.git
cd pymidscene

# 安装依赖
pip install -e .

# 安装 Playwright 浏览器
playwright install chromium
```

### 基础示例

```python
import asyncio
from playwright.async_api import async_playwright
from pymidscene.core.agent import Agent
from pymidscene.web_integration.playwright import WebPage

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        # 创建 Agent
        agent = Agent(
            interface=WebPage(page),
            model="qwen-vl-max",
            cache_id="my_test"
        )

        # 访问网页
        await page.goto("https://www.baidu.com")

        # AI 自动化操作
        await agent.ai_input("搜索框", "Python 教程")
        await agent.ai_click("搜索按钮")

        # 提取数据
        result = await agent.ai_query({
            "title": "页面标题，字符串",
            "count": "搜索结果数量，数字"
        })
        print(result['data'])

        await browser.close()

asyncio.run(main())
```

---

## 核心类

### Agent

**完整路径**: `pymidscene.core.agent.Agent`

AI 驱动的自动化 Agent，整合了 AI 模型、缓存系统和浏览器控制。

#### 构造函数

```python
Agent(
    interface: AbstractInterface,
    model: str = "qwen-vl-max",
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    cache_id: Optional[str] = None,
    cache_strategy: str = "read-write",
    cache_dir: Optional[str] = None,
    enable_recording: bool = False,
    **model_kwargs
)
```

#### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `interface` | `AbstractInterface` | - | 设备接口（如 WebPage） |
| `model` | `str` | `"qwen-vl-max"` | AI 模型名称 |
| `api_key` | `Optional[str]` | `None` | API 密钥（优先从环境变量读取） |
| `base_url` | `Optional[str]` | `None` | API 基础 URL |
| `cache_id` | `Optional[str]` | `None` | 缓存标识符 |
| `cache_strategy` | `str` | `"read-write"` | 缓存策略：`read-only`、`read-write`、`write-only` |
| `cache_dir` | `Optional[str]` | `None` | 缓存目录（默认 `.midscene/cache/`） |
| `enable_recording` | `bool` | `False` | 是否启用执行记录 |
| `**model_kwargs` | `dict` | - | 其他模型参数（如 `temperature`、`max_tokens`） |

#### 示例

```python
# 基础用法
agent = Agent(
    interface=WebPage(page),
    model="qwen-vl-max"
)

# 完整配置
agent = Agent(
    interface=WebPage(page),
    model="qwen-vl-max",
    api_key="your-api-key",
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    cache_id="production_test",
    cache_strategy="read-write",
    enable_recording=True,
    temperature=0.1,
    max_tokens=8192
)
```

#### 属性

| 属性 | 类型 | 说明 |
|------|------|------|
| `interface` | `AbstractInterface` | 设备接口 |
| `model` | `QwenVLModel` | AI 模型实例 |
| `model_name` | `str` | 模型名称 |
| `task_cache` | `Optional[TaskCache]` | 缓存管理器 |
| `recorder` | `Optional[ExecutionRecorder]` | 执行记录器 |
| `enable_recording` | `bool` | 是否启用记录 |

---

### WebPage

**完整路径**: `pymidscene.web_integration.playwright.WebPage`

Playwright Page 的适配器，提供统一的浏览器控制接口。

#### 构造函数

```python
WebPage(
    page: PlaywrightPage,
    wait_for_navigation_timeout: Optional[int] = None,
    wait_for_network_idle_timeout: Optional[int] = None
)
```

#### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `page` | `PlaywrightPage` | - | Playwright 的 Page 对象 |
| `wait_for_navigation_timeout` | `Optional[int]` | `10000` | 导航超时（毫秒） |
| `wait_for_network_idle_timeout` | `Optional[int]` | `10000` | 网络空闲超时（毫秒） |

#### 示例

```python
from playwright.async_api import async_playwright
from pymidscene.web_integration.playwright import WebPage

async with async_playwright() as p:
    browser = await p.chromium.launch()
    page = await browser.new_page()

    # 创建 WebPage 适配器
    web_page = WebPage(
        page,
        wait_for_navigation_timeout=5000,
        wait_for_network_idle_timeout=10000
    )

    # 使用适配器
    screenshot = await web_page.screenshot()
    await web_page.click(640, 360)
```

#### 方法

| 方法 | 说明 |
|------|------|
| `screenshot(full_page=False)` | 获取页面截图（Base64） |
| `get_size()` | 获取页面尺寸 |
| `click(x, y)` | 点击坐标 |
| `input_text(text, x, y)` | 输入文本 |
| `hover(x, y)` | 悬停 |
| `scroll(x, y)` | 滚动 |
| `key_press(key)` | 按键 |
| `wait_for_navigation()` | 等待导航完成 |
| `wait_for_network_idle()` | 等待网络空闲 |

---

## AI 方法

### ai_locate()

使用 AI 定位页面元素。

#### 签名

```python
async def ai_locate(
    self,
    prompt: str,
    use_cache: bool = True
) -> Optional[LocateResultElement]
```

#### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `prompt` | `str` | - | 元素描述（自然语言） |
| `use_cache` | `bool` | `True` | 是否使用缓存 |

#### 返回值

`Optional[LocateResultElement]` - 定位结果，包含：
- `description`: 元素描述
- `center`: 中心点坐标 `(x, y)`
- `rect`: 矩形区域 `{left, top, width, height}`

#### 示例

```python
# 基础用法
element = await agent.ai_locate("登录按钮")
if element:
    print(f"找到元素，位置: {element.center}")
    print(f"区域: {element.rect}")

# 禁用缓存
element = await agent.ai_locate("动态内容", use_cache=False)

# 中文描述
element = await agent.ai_locate("页面右上角的用户头像")

# 英文描述
element = await agent.ai_locate("search input field")
```

#### 注意事项

- 返回 `None` 表示未找到元素
- 支持中英文混合描述
- 自动使用缓存加速重复定位
- 会记录到执行日志（如果启用）

---

### ai_click()

使用 AI 定位并点击元素。

#### 签名

```python
async def ai_click(
    self,
    prompt: str
) -> bool
```

#### 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `prompt` | `str` | 元素描述 |

#### 返回值

`bool` - 是否成功点击

#### 示例

```python
# 点击按钮
success = await agent.ai_click("提交按钮")
if success:
    print("点击成功！")

# 点击链接
await agent.ai_click("查看更多")

# 点击图标
await agent.ai_click("搜索图标")
```

#### 工作流程

1. 调用 `ai_locate()` 定位元素
2. 获取元素中心点坐标
3. 调用 `interface.click()` 执行点击
4. 等待导航和网络空闲

---

### ai_input()

使用 AI 定位并输入文本。

#### 签名

```python
async def ai_input(
    self,
    prompt: str,
    text: str
) -> bool
```

#### 参数

| 参数 | 类型 | 说明 |
|------|------|------|
| `prompt` | `str` | 元素描述 |
| `text` | `str` | 要输入的文本 |

#### 返回值

`bool` - 是否成功输入

#### 示例

```python
# 输入搜索关键词
await agent.ai_input("搜索框", "Python 教程")

# 输入用户名和密码
await agent.ai_input("用户名输入框", "admin")
await agent.ai_input("密码输入框", "password123")

# 输入多行文本
await agent.ai_input("备注框", "第一行\n第二行\n第三行")
```

#### 工作流程

1. 调用 `ai_locate()` 定位输入框
2. 点击输入框获取焦点
3. 输入文本
4. 等待网络空闲

---

### ai_query()

使用 AI 从页面提取结构化数据。

#### 签名

```python
async def ai_query(
    self,
    data_demand: Union[Dict[str, str], str],
    use_cache: bool = False
) -> Dict[str, Any]
```

#### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `data_demand` | `Union[Dict[str, str], str]` | - | 数据需求描述 |
| `use_cache` | `bool` | `False` | 是否使用缓存 |

#### 返回值

`Dict[str, Any]` - 包含以下字段：
- `data`: 提取的数据（根据需求结构化）
- `thought`: AI 的思考过程（可选）
- `errors`: 错误信息列表（可选）

#### 示例

**字典格式**（推荐）：
```python
# 提取多个字段
result = await agent.ai_query({
    "title": "页面标题，字符串类型",
    "price": "商品价格，数字类型",
    "in_stock": "是否有货，布尔值",
    "reviews": "评论数量，整数"
})

print(result['data'])
# {'title': '商品名称', 'price': 99.99, 'in_stock': True, 'reviews': 1234}

# 提取列表数据
result = await agent.ai_query({
    "titles": "搜索结果的前5个标题，字符串列表"
})

print(result['data']['titles'])
# ['结果1', '结果2', '结果3', '结果4', '结果5']
```

**字符串格式**：
```python
# 简单查询
result = await agent.ai_query("获取页面标题")
print(result['data'])
```

#### 类型提示

在描述中明确指定数据类型可以提高准确性：

| 类型 | 描述示例 |
|------|---------|
| 字符串 | `"页面标题，字符串类型"` |
| 数字 | `"商品价格，数字类型"` |
| 整数 | `"评论数量，整数"` |
| 布尔值 | `"是否有货，布尔值"` |
| 列表 | `"搜索结果标题列表"` |
| 对象 | `"用户信息对象，包含姓名和邮箱"` |

---

### ai_assert()

使用 AI 断言页面状态。

#### 签名

```python
async def ai_assert(
    self,
    assertion: str,
    message: str = ""
) -> bool
```

#### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `assertion` | `str` | - | 断言描述 |
| `message` | `str` | `""` | 自定义错误消息 |

#### 返回值

`bool` - 断言是否通过

#### 异常

- `AssertionError` - 断言失败时抛出

#### 示例

```python
# 基础断言
try:
    await agent.ai_assert("页面显示登录成功提示")
    print("断言通过")
except AssertionError as e:
    print(f"断言失败: {e}")

# 自定义错误消息
await agent.ai_assert(
    "页面显示了至少3个搜索结果",
    message="搜索结果数量不足"
)

# 多个断言
await agent.ai_assert("导航栏显示用户名")
await agent.ai_assert("购物车图标显示数量为2")
await agent.ai_assert("页面没有显示错误提示")
```

#### 常见断言场景

```python
# 验证页面状态
await agent.ai_assert("页面加载完成")
await agent.ai_assert("没有显示加载动画")

# 验证内容存在
await agent.ai_assert("页面显示了搜索结果")
await agent.ai_assert("标题中包含关键词'Python'")

# 验证元素状态
await agent.ai_assert("提交按钮是可点击的")
await agent.ai_assert("表单验证全部通过")

# 验证数量
await agent.ai_assert("显示了至少10个商品")
await agent.ai_assert("购物车中有3件商品")
```

---

## 缓存系统

PyMidscene 提供智能缓存系统，减少 API 调用，提高执行速度。

### 缓存策略

| 策略 | 说明 | 适用场景 |
|------|------|---------|
| `read-write` | 读取并更新缓存（默认） | 开发和调试 |
| `read-only` | 只读缓存，不写入 | CI/CD 环境 |
| `write-only` | 只写缓存，不读取 | 强制重新生成缓存 |

### 基础用法

```python
# 启用缓存
agent = Agent(
    interface=web_page,
    cache_id="my_test",
    cache_strategy="read-write"
)

# 只读模式（CI/CD）
agent = Agent(
    interface=web_page,
    cache_id="ci_test",
    cache_strategy="read-only"
)

# 只写模式（强制重新生成）
agent = Agent(
    interface=web_page,
    cache_id="rebuild",
    cache_strategy="write-only"
)
```

### 缓存统计

```python
# 获取缓存统计
stats = agent.get_cache_stats()

if stats:
    print(f"缓存 ID: {stats['cache_id']}")
    print(f"总记录数: {stats['total_records']}")
    print(f"已匹配: {stats['matched_records']}")
    print(f"命中率: {stats['matched_records'] / stats['total_records'] * 100:.1f}%")
    print(f"策略: {stats['strategy']}")
```

### 缓存文件

缓存默认保存在：
```
.midscene/cache/<cache_id>.cache.yaml
```

示例缓存文件：
```yaml
caches:
  - type: locate
    prompt: 搜索框
    cache:
      bbox: [100, 200, 300, 250]
  - type: locate
    prompt: 搜索按钮
    cache:
      bbox: [400, 200, 500, 250]
```

### 最佳实践

1. **开发阶段**：使用 `read-write` 策略
2. **CI/CD**：使用 `read-only` 策略，确保一致性
3. **缓存失效**：页面布局变化时，使用 `write-only` 重新生成
4. **缓存隔离**：不同环境使用不同的 `cache_id`

---

## 执行记录

PyMidscene 可以记录完整的执行过程，用于调试和报告。

### 启用执行记录

```python
agent = Agent(
    interface=web_page,
    model="qwen-vl-max",
    enable_recording=True
)
```

### 导出执行记录

```python
# 执行自动化操作
await agent.ai_locate("搜索框")
await agent.ai_click("搜索按钮")
await agent.ai_query({"title": "页面标题"})

# 导出为 JSON
if agent.recorder:
    json_report = agent.recorder.to_json()

    # 保存到文件
    with open("execution_report.json", "w", encoding="utf-8") as f:
        f.write(json_report)

    print("执行记录已保存")
```

### 记录内容

执行记录包含：

- **任务信息**：类型、参数、状态
- **截图**：执行前后的页面截图（Base64）
- **AI 使用**：tokens 消耗、耗时、模型名称
- **执行结果**：输出数据、错误信息
- **时间戳**：精确到毫秒

### 示例记录

```json
{
  "logTime": 1706000000.123,
  "name": "Agent Execution",
  "description": "Automated execution with qwen-vl-max",
  "tasks": [
    {
      "type": "locate",
      "param": "搜索框",
      "status": "finished",
      "recorder": [
        {
          "type": "screenshot",
          "ts": 1706000000.456,
          "screenshot": "iVBORw0KGgoAAAANS...",
          "timing": "before"
        }
      ],
      "usage": {
        "prompt_tokens": 1000,
        "completion_tokens": 50,
        "total_tokens": 1050,
        "time_cost": 2.3,
        "model_name": "qwen-vl-max"
      },
      "output": {
        "description": "搜索框",
        "center": [640, 360],
        "rect": {"left": 500, "top": 340, "width": 280, "height": 40}
      }
    }
  ]
}
```

---

## 类型定义

### LocateResultElement

元素定位结果。

```python
@dataclass
class LocateResultElement:
    description: str              # 元素描述
    center: Tuple[float, float]   # 中心点坐标 (x, y)
    rect: Rect                    # 矩形区域
```

### Rect

矩形区域定义。

```python
class Rect(TypedDict):
    left: float
    top: float
    width: float
    height: float
    zoom: Optional[float]
```

### Size

页面尺寸定义。

```python
class Size(TypedDict):
    width: float
    height: float
    dpr: Optional[float]  # 设备像素比
```

---

## 配置选项

### 环境变量

PyMidscene 支持通过环境变量配置：

```bash
# 千问 API 配置
export MIDSCENE_QWEN_API_KEY="your-api-key"
export MIDSCENE_QWEN_BASE_URL="https://dashscope.aliyuncs.com/compatible-mode/v1"

# 日志级别
export MIDSCENE_LOG_LEVEL="DEBUG"  # DEBUG, INFO, WARNING, ERROR
```

### 模型参数

```python
agent = Agent(
    interface=web_page,
    model="qwen-vl-max",
    temperature=0.1,      # 温度（0-1）
    max_tokens=8192,      # 最大 tokens
    top_p=0.95,          # Top-p 采样
)
```

### 超时配置

```python
web_page = WebPage(
    page,
    wait_for_navigation_timeout=5000,    # 导航超时 5秒
    wait_for_network_idle_timeout=10000  # 网络空闲超时 10秒
)
```

---

## 最佳实践

### 1. 元素定位

✅ **推荐**：
```python
await agent.ai_locate("登录按钮")
await agent.ai_locate("页面右上角的用户头像")
await agent.ai_locate("第一个搜索结果的标题")
```

❌ **避免**：
```python
await agent.ai_locate("按钮")  # 太模糊
await agent.ai_locate("div")   # 使用技术术语
```

### 2. 数据提取

✅ **推荐**：
```python
# 明确类型
result = await agent.ai_query({
    "title": "页面标题，字符串",
    "price": "商品价格，数字",
    "count": "评论数量，整数"
})
```

❌ **避免**：
```python
# 类型不明确
result = await agent.ai_query({
    "title": "标题",
    "price": "价格"
})
```

### 3. 错误处理

✅ **推荐**：
```python
try:
    element = await agent.ai_locate("登录按钮")
    if element:
        await agent.ai_click("登录按钮")
    else:
        print("未找到登录按钮")
except Exception as e:
    print(f"操作失败: {e}")
```

### 4. 使用缓存

✅ **推荐**：
```python
# 开发时使用缓存
agent = Agent(
    interface=web_page,
    cache_id="dev_test",
    cache_strategy="read-write"
)

# CI/CD 使用只读缓存
agent = Agent(
    interface=web_page,
    cache_id="ci_test",
    cache_strategy="read-only"
)
```

### 5. 等待策略

✅ **推荐**：
```python
await agent.ai_click("提交按钮")
await asyncio.sleep(2)  # 等待页面加载
await agent.ai_assert("显示成功提示")
```

---

## 常见问题

### Q: 如何提高定位准确性？

A: 使用更具体的描述：
```python
# 好
await agent.ai_locate("页面顶部导航栏的登录按钮")

# 一般
await agent.ai_locate("登录按钮")
```

### Q: 如何处理动态内容？

A: 禁用缓存：
```python
element = await agent.ai_locate("实时股价", use_cache=False)
```

### Q: 如何调试失败的操作？

A: 启用执行记录和 DEBUG 日志：
```python
from pymidscene.shared.logger import logger
logger.set_level("DEBUG")

agent = Agent(
    interface=web_page,
    enable_recording=True
)
```

### Q: 如何减少 API 调用成本？

A: 使用缓存系统：
```python
agent = Agent(
    interface=web_page,
    cache_id="production",
    cache_strategy="read-write"
)
```

---

## 更多资源

- [快速开始指南](../QUICKSTART.md)
- [示例代码](../examples/)
- [GitHub 仓库](https://github.com/yourusername/pymidscene)
- [问题反馈](https://github.com/yourusername/pymidscene/issues)

---

**最后更新**: 2026-01-22
**文档版本**: 1.0.0
