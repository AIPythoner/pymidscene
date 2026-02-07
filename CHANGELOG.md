# PyMidscene 更新日志

## [0.1.2] - 2026-02-07

### 重大变更

#### 1. 移除 Anthropic 模型支持
- 删除 `anthropic.py` 适配器
- 清理 `__init__.py`、`agent.py` 中所有 Anthropic/Claude 相关引用
- `prompts/common.py` 移除 claude/openai 模型家族类型

#### 2. API 调用层重构：用 httpx 替代 OpenAI SDK
- **问题**: OpenAI SDK 对 `base_url` 的处理方式与反代不兼容，导致 Gemini 反代返回 404
- **修复**: 参考 `GeminiHttpClient`，改用 httpx 直接发送 HTTP 请求，完全掌控 URL 拼接
- **智能 URL 构造**: 用正则 `/v\d+$/` 自动判断 base_url 是否已含版本路径
  - 官方 API（`/v1`、`/v3` 结尾）→ 直接拼 `/chat/completions`
  - 反代（无版本路径）→ 自动补 `/v1/chat/completions`
- **兼容**: 豆包官方、千问官方、OpenAI 官方、Gemini 反代、任意 OpenAI 格式反代

### 修复

#### 3. 坐标处理全面对齐 JS 版本
- **adapt_bbox 参数修复**: 新增 `right_limit`、`bottom_limit` 参数，修复 `model_family` 被误传为 `right_limit` 导致的类型错误
- **adapt_doubao_bbox 修复**:
  - 支持字符串数字列表 `["500", "300", "600", "400"]`
  - 支持字符串数组 `["123 222", "789 100"]`
  - 支持 2/3/4/5/6/7/8 长度的 bbox 格式
  - 八点格式改为取第 0,1,4,5 个点（与 JS 版本对齐，之前错误地取外接矩形）
  - 中心点默认 bbox 尺寸改为 `DEFAULT_BBOX_SIZE=20`（半径 10，之前硬编码为 5）
  - 添加边界检查 `max(0,...)` 和 `min(width/height,...)`
- **bbox_description 对齐**: 只保留 gemini 的特殊分支，其他模型统一描述

#### 4. 点击/输入坐标偏移问题
- **问题**: `scrollIntoView` 滚动后元素的视口坐标变了，但仍用旧坐标点击，导致点偏
- **修复**: 滚动后通过 `getBoundingClientRect()` 重新计算元素在视口中的实际坐标

### 新增

#### 5. 元素自动居中显示
- 点击/输入前总是调用 `scrollIntoView({ behavior: 'instant', block: 'center' })`
- 元素不在视口时先粗略滚动到大致位置，再精确居中
- 与 JS 版本 `getElementInfoByXpath` 的滚动逻辑完全对齐

#### 6. 滚动重试机制
- 新增 `ai_locate_with_scroll_retry()` 方法
- 元素定位失败时自动向下滚动 500px 并重试，最多 3 次
- 第一次尝试使用缓存，后续重试自动禁用缓存
- `ai_click` 和 `ai_input` 默认启用滚动重试（可通过 `enable_scroll_retry=False` 关闭）

#### 7. 通用工具函数补全
- `normalize_bbox_input()` - 处理嵌套数组 `[[x,y,w,h]]`
- `point_to_bbox()` - 点坐标转 bbox
- `is_ui_tars()` - UI-TARS 模型判断
- `preprocess_doubao_bbox_json()` - 豆包空格分隔坐标预处理
- `normalize_json_object()` - 去除 key/value 前后空格
- `fill_bbox_param()` - 处理 Qwen 的 `bbox_2d` 幻觉问题
- `adapt_qwen2_5_bbox()` - Qwen 2.5 绝对像素坐标处理
- `adapt_gemini_bbox()` - Gemini `[y1,x1,y2,x2]` 格式处理
- `normalized_0_1000()` - 通用 0-1000 归一化坐标转换
- `adapt_bbox_to_rect()` - bbox 转 Rect 对象

#### 8. JSON 解析增强
- `safe_parse_json_with_repair` 新增 `model_family` 参数
- 支持点坐标格式 `(x,y)` 匹配
- 集成 `preprocess_doubao_bbox_json` 豆包特殊处理
- 集成 `normalize_json_object` 规范化

#### 9. 测试脚本
- 新增 `test_scroll_logic.py` 滚动行为验证脚本

---

## [0.1.1] - 2024-02-03

### 修复

#### 1. AI 元素定位坐标转换问题
- **问题**: Doubao-vision 模型返回的 bbox 坐标是归一化到 0-1000 的值，直接使用导致定位偏移 150-270px
- **原因**: Python 版本缺少原 JS 项目的 `adaptDoubaoBbox` 坐标转换逻辑
- **修复**: 新增 `adapt_bbox()` 系列函数，根据模型类型自动转换坐标
- **文件**: `pymidscene/shared/utils.py`, `pymidscene/core/agent/agent.py`

#### 2. 输入框未清空问题
- **问题**: `ai_input` 输入文本时未清空原有内容，导致文本追加而非替换
- **修复**: 添加 `Ctrl+A` + `Backspace` 清空逻辑
- **文件**: `pymidscene/web_integration/playwright/page.py`

#### 3. JSON 代码块解析问题
- **问题**: AI 返回的 JSON 被 markdown 代码块包裹（```json ... ```），解析失败
- **修复**: 在解析前调用 `extract_json_from_code_block()` 提取 JSON
- **文件**: `pymidscene/core/agent/agent.py`

### 新增

- `adapt_bbox()` - 根据模型类型自动选择坐标转换方式
- `adapt_doubao_bbox()` - Doubao 模型归一化坐标转换 (0-1000 -> 像素)
- `adapt_qwen_bbox()` - Qwen 模型坐标处理
- `adapt_gemini_bbox()` - Gemini 模型特殊格式处理 ([y1,x1,y2,x2])
- `normalized_0_1000()` - 通用归一化坐标转换
- 完整自动化测试脚本 `tests/validation/test_automation.py`

### 测试结果

| 功能 | 状态 |
|------|------|
| 输入操作 | ✅ 100% |
| 点击操作 | ✅ 100% |
| Hover操作 | ✅ 100% |

---

## [0.1.0] - 初始版本

- 基础 PlaywrightAgent 实现
- AI 元素定位、点击、输入、查询、断言功能
- 执行报告生成
