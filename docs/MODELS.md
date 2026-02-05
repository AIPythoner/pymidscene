# 模型配置指南 - Model Configuration

PyMidscene 支持多种视觉大模型，本文档介绍各模型的配置方法。

## 支持的模型

| 模型 | 提供商 | 模型家族 | 推荐场景 |
|------|--------|----------|----------|
| doubao-seed-1.6 | 字节跳动/火山引擎 | doubao-vision | 国内用户首选 |
| qwen-vl-max | 阿里云 | qwen2.5-vl | 国内备选 |
| gpt-4-vision | OpenAI | openai | 海外用户 |
| claude-3 | Anthropic | claude | 海外用户 |

## 配置方式

### 方式一：环境变量（推荐）

创建 `.env` 文件：

```bash
# 豆包模型
MIDSCENE_MODEL_NAME=your-endpoint-id
MIDSCENE_MODEL_API_KEY=your-api-key
MIDSCENE_MODEL_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
MIDSCENE_MODEL_FAMILY=doubao-vision
```

代码中加载：

```python
from dotenv import load_dotenv
load_dotenv()

agent = PlaywrightAgent(page)
```

### 方式二：代码配置

```python
import os

os.environ["MIDSCENE_MODEL_NAME"] = "your-endpoint-id"
os.environ["MIDSCENE_MODEL_API_KEY"] = "your-api-key"
os.environ["MIDSCENE_MODEL_BASE_URL"] = "https://..."
os.environ["MIDSCENE_MODEL_FAMILY"] = "doubao-vision"

agent = PlaywrightAgent(page)
```

### 方式三：model_config 参数

```python
config = {
    "MIDSCENE_MODEL_NAME": "your-endpoint-id",
    "MIDSCENE_MODEL_API_KEY": "your-api-key",
    "MIDSCENE_MODEL_BASE_URL": "https://...",
    "MIDSCENE_MODEL_FAMILY": "doubao-vision",
}

agent = PlaywrightAgent(page, model_config=config)
```

## 各模型详细配置

### 豆包 Doubao（火山引擎）

1. 访问 [火山引擎控制台](https://console.volcengine.com/ark)
2. 创建推理接入点，获取 Endpoint ID
3. 获取 API Key

```bash
MIDSCENE_MODEL_NAME=ep-20250122xxxxxx  # 你的 Endpoint ID
MIDSCENE_MODEL_API_KEY=your-api-key
MIDSCENE_MODEL_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
MIDSCENE_MODEL_FAMILY=doubao-vision
```

### 千问 Qwen（阿里云）

1. 访问 [阿里云 DashScope](https://dashscope.console.aliyun.com/)
2. 开通模型服务，获取 API Key

```bash
MIDSCENE_MODEL_NAME=qwen-vl-max
MIDSCENE_MODEL_API_KEY=sk-xxxxxx
MIDSCENE_MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
MIDSCENE_MODEL_FAMILY=qwen2.5-vl
```

### OpenAI GPT-4V

```bash
MIDSCENE_MODEL_NAME=gpt-4-vision-preview
MIDSCENE_MODEL_API_KEY=sk-xxxxxx
MIDSCENE_MODEL_BASE_URL=https://api.openai.com/v1
MIDSCENE_MODEL_FAMILY=openai
```

## 坐标系统差异

不同模型返回的坐标格式不同，PyMidscene 会自动处理：

| 模型家族 | 坐标格式 | 说明 |
|----------|----------|------|
| doubao-vision | 归一化 0-1000 | 需要 `x * width / 1000` |
| qwen2.5-vl | 像素坐标 | 直接使用 |
| openai | 像素坐标 | 直接使用 |
| gemini | [y1, x1, y2, x2] | 需要交换顺序 |

## 常见问题

### Q: 为什么点击位置不准确？

A: 检查 `MIDSCENE_MODEL_FAMILY` 是否正确设置。不同模型返回的坐标格式不同，需要正确的模型家族才能正确转换坐标。

### Q: 如何切换模型？

A: 修改环境变量或 `.env` 文件即可，无需修改代码。
