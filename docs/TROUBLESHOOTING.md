# PyMidscene 故障排查指南

本文档记录了 PyMidscene 开发过程中遇到的问题、排查思路和解决方案，供后续维护参考。

---

## 目录

1. [AI 元素定位坐标偏移问题](#1-ai-元素定位坐标偏移问题)
2. [输入框内容未清空问题](#2-输入框内容未清空问题)
3. [AI 响应 JSON 解析失败](#3-ai-响应-json-解析失败)
4. [排查工具和方法](#4-排查工具和方法)

---

## 1. AI 元素定位坐标偏移问题

### 症状
- AI 定位的元素坐标与实际位置偏差 150-270px
- 红框标注在截图上向左下方偏移
- 偏移量与屏幕缩放比例相关

### 排查步骤

1. **检查 AI 原始响应**
```python
# 打印 AI 返回的原始 bbox
print(f"AI 原始 bbox: {response_data['bbox']}")
# 示例: [251, 426, 657, 471] - 这是归一化到 0-1000 的值
```

2. **对比截图尺寸和视口尺寸**
```python
# 如果截图 1280x800，视口也是 1280x800，但坐标偏移
# 说明是坐标归一化问题，不是 DPR 缩放问题
```

3. **检查模型类型**
```python
# 不同模型返回的坐标格式不同
# doubao-vision: 归一化 0-1000
# qwen2.5-vl: 像素坐标
# gemini: [y1, x1, y2, x2] 归一化 0-1000
```

### 根本原因

**Doubao-vision 模型返回的是归一化到 0-1000 的坐标**，需要转换为像素坐标：

```python
# 转换公式
pixel_x = round(normalized_x * width / 1000)
pixel_y = round(normalized_y * height / 1000)
```

### 解决方案

在 `pymidscene/shared/utils.py` 中添加坐标适配函数：

```python
def adapt_doubao_bbox(bbox, width, height):
    """Doubao 模型归一化坐标转换"""
    return (
        round(bbox[0] * width / 1000),
        round(bbox[1] * height / 1000),
        round(bbox[2] * width / 1000),
        round(bbox[3] * height / 1000),
    )

def adapt_bbox(bbox, width, height, model_family):
    """根据模型类型自动选择转换方式"""
    if model_family in ('doubao-vision', 'vlm-ui-tars-doubao'):
        return adapt_doubao_bbox(bbox, width, height)
    elif model_family == 'gemini':
        return adapt_gemini_bbox(bbox, width, height)
    elif model_family == 'qwen2.5-vl':
        return adapt_qwen_bbox(bbox)
    else:
        return normalized_0_1000(bbox, width, height)
```

### 关键文件
- `pymidscene/shared/utils.py` - 坐标转换函数
- `pymidscene/core/agent/agent.py` - 调用 adapt_bbox

### 参考原 JS 项目
- `midscene-main/packages/core/src/common.ts` - `adaptDoubaoBbox` 函数

---

## 2. 输入框内容未清空问题

### 症状
- 调用 `ai_input` 后，新内容追加到原有内容后面
- 输入框中出现重复或混合内容

### 根本原因
原实现直接调用 `keyboard.type(text)`，未清空输入框现有内容。

### 解决方案

在 `pymidscene/web_integration/playwright/page.py` 的 `input_text` 方法中添加清空逻辑：

```python
async def input_text(self, text, x=None, y=None, clear_first=True):
    if x is not None and y is not None:
        await self.page.mouse.click(x, y)
        await asyncio.sleep(0.1)
    
    # 清空输入框（关键修复）
    if clear_first:
        await self.page.keyboard.press("Control+a")
        await asyncio.sleep(0.05)
        await self.page.keyboard.press("Backspace")
        await asyncio.sleep(0.05)
    
    await self.page.keyboard.type(text)
```

### 关键文件
- `pymidscene/web_integration/playwright/page.py`

---

## 3. AI 响应 JSON 解析失败

### 症状
- `safe_parse_json` 返回 None
- 日志显示 "no bbox in response"
- AI 实际返回了有效数据

### 根本原因
AI 返回的 JSON 被 markdown 代码块包裹：
```
```json
{"bbox": [100, 200, 300, 400]}
```
```

### 解决方案

在解析前提取 JSON：

```python
from ...shared.utils import safe_parse_json, extract_json_from_code_block

# 先提取 JSON（处理 markdown 代码块）
json_text = extract_json_from_code_block(result["content"])
response_data = safe_parse_json(json_text)
```

### 关键文件
- `pymidscene/core/agent/agent.py` - ai_locate 方法
- `pymidscene/shared/utils.py` - extract_json_from_code_block

---

## 4. 排查工具和方法

### 4.1 自动化测试脚本

运行完整功能验证：
```bash
cd pymidscene
python tests/validation/test_automation.py
```

测试内容：
- 输入操作验证（通过 JS 事件监听确认）
- 点击操作验证
- Hover 操作验证
- 复选框/单选框操作

### 4.2 坐标诊断方法

在截图上绘制 AI 识别区域和真实区域对比：

```python
from PIL import Image, ImageDraw

# 红色 = AI 识别区域
draw.rectangle([ai_left, ai_top, ai_right, ai_bottom], outline="red", width=3)

# 绿色 = 真实区域
draw.rectangle([true_left, true_top, true_right, true_bottom], outline="lime", width=3)

img.save("compare.png")
```

### 4.3 JS 事件监听验证

在测试页面中添加事件监听确认操作成功：

```javascript
element.addEventListener('input', (e) => {
    console.log(`输入内容: ${e.target.value}`);
    window.testResults[elementId] = e.target.value;
});

element.addEventListener('click', () => {
    console.log(`点击事件触发`);
    window.testResults[elementId] = true;
});
```

Python 端验证：
```python
actual_value = await page.evaluate(f"window.testAPI.getInputValue('{element_id}')")
assert actual_value == expected_value
```

### 4.4 模型坐标格式速查表

| 模型 | bbox 格式 | 坐标系 | 转换函数 |
|------|----------|--------|----------|
| doubao-vision | [x1, y1, x2, y2] | 归一化 0-1000 | `adapt_doubao_bbox` |
| qwen2.5-vl | [x1, y1, x2, y2] | 像素坐标 | `adapt_qwen_bbox` |
| gemini | [y1, x1, y2, x2] | 归一化 0-1000 | `adapt_gemini_bbox` |
| 其他 | [x1, y1, x2, y2] | 归一化 0-1000 | `normalized_0_1000` |

---

## 快速检查清单

遇到定位问题时，按以下顺序排查：

- [ ] 检查 `MIDSCENE_MODEL_FAMILY` 环境变量是否正确设置
- [ ] 打印 AI 原始 bbox 响应，确认格式
- [ ] 确认是否调用了 `adapt_bbox` 进行坐标转换
- [ ] 检查截图尺寸与视口尺寸是否一致
- [ ] 在截图上绘制对比图确认偏移方向

遇到输入问题时：

- [ ] 确认 `clear_first=True`（默认值）
- [ ] 检查元素是否正确获得焦点
- [ ] 使用 JS 事件监听确认输入内容

遇到解析问题时：

- [ ] 打印 AI 原始响应内容
- [ ] 检查是否有 markdown 代码块包裹
- [ ] 确认调用了 `extract_json_from_code_block`
