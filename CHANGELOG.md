# PyMidscene 更新日志

## [0.1.5] - 2026-04-14

### 修复

#### 1. 官方风格 HTML 报告可直接本地打开
- **问题**: 之前 Python 版报告会依赖作者本机的 JS 模板路径，普通用户环境找不到模板时会退化成提示页，或只生成一个 HTML 但缺少运行所需静态资源
- **修复**: 将官方风格报告模板作为 package data 内置到 `pymidscene`
- 运行时改为从包内资源加载报告模板，不再依赖本机 JS 项目路径
- 生成报告时继续注入 `midscene_web_dump` 数据，保持与上游模板兼容
- 保存 official-style 报告时，会把 `static/wasm` 等模板依赖资源一并写入报告目录，避免 HTML 能生成但浏览器加载资源失败
- 如果 official-style 报告生成或保存失败，会自动回退到 Python 原生 HTML 报告，而不是停留在模板加载失败提示页

### 新增

- 新增 `pymidscene.core.report_template_resources`，统一管理 vendored 报告模板与静态资源
- 新增报告相关聚焦测试、打包 smoke 测试和官方风格报告 golden sample 回归样本

## [0.1.4] - 2026-02-27

### 重大变更

#### 1. Gemini 模型改用 google-genai SDK（原生协议）
- **问题**: 之前所有模型统一走 OpenAI 兼容协议（`/v1/chat/completions`），Gemini 中转站实际走的是 Gemini 原生协议（`/v1beta/models/{model}:generateContent`），导致 400/404 错误
- **修复**: 当 `model_family=gemini` 时，自动使用 Google 官方 `google-genai` SDK 调用
- SDK 自动处理：URL 拼接、认证方式、协议格式、重试机制
- 支持：Gemini 官方 API、第三方中转站、反代 —— 只需配置 `MIDSCENE_MODEL_BASE_URL`
- 新增 `_call_with_gemini_sdk()` 方法和 `_convert_messages_to_gemini_contents()` 消息格式转换
- 非 Gemini 模型（豆包、千问等）仍走原有的 OpenAI 兼容 httpx 请求

### 新增

- `google-genai` 加入项目依赖（`pyproject.toml`）
- OpenAI messages 格式自动转换为 Gemini contents 格式（含 base64 图片转 inline_data）

### 配置变更

- Gemini 用户的 `.env` 配置简化，`MIDSCENE_MODEL_BASE_URL` 只需填中转站/API 前缀，无需手动拼版本路径
- 示例：`MIDSCENE_MODEL_BASE_URL=https://code.newcli.com/gemini`

## [0.1.3] - 2026-02-09

### 重大变更

#### 1. ai_act / ai_action 完整实现（plan-execute-replan 循环）
- **之前**: `ai_act` 仅为 stub，`ai_action` 直接代理到 `ai_click`
- **现在**: 完整实现 AI 规划循环，与 JS 版本 `agent.ts aiAct` + `tasks.ts runAction()` 对齐
- AI 截图分析 → 规划动作序列（含 Scroll）→ 执行 → 重新截图 replan → 直到完成
- 支持缓存：首次 AI 规划 → 保存为 YAML workflow；后续直接回放
- 最大重规划次数限制（10 次，对应 JS `replanningCycleLimit`）

#### 2. Planner Prompt 重构为 JSON 格式
- **之前**: YAML 格式的规划输出
- **现在**: JSON 格式，包含 `actions` 数组和 `shouldContinuePlanning` 标志
- 新增 `parse_planning_response()` 解析函数
- `plan_task_prompt()` 支持 `conversation_history` 参数用于 replan 上下文

### 新增

#### 3. 新增 API 方法
- `ai_wait_for(assertion, timeout, interval)` — 轮询等待页面满足条件（对应 JS `aiWaitFor`）
- `ai_scroll(direction, distance, scroll_type, locate_prompt)` — AI 滚动操作（对应 JS `aiScroll`）
- `ai_action` 别名与 `ai_act` 完全等价
- PlaywrightAgent 层同步暴露 `ai_act`、`ai_wait_for`、`ai_scroll` 方法

#### 4. 双向滚动搜索（ai_locate_with_scroll_retry 增强）
- **之前**: 仅向下滚动 3 次
- **现在**: 向下滚动 5 次 + 回到顶部再向下搜索 2 次（覆盖页面上方区域）
- 找到元素后通过 XPath `scrollIntoView` 自动滚动到视口中心

#### 5. XPath scrollIntoView 机制
- 新增 `_scroll_element_into_view_after_locate()` 方法
- 定位到元素后通过 XPath 精确滚动到视口中心（对应 JS `locator.ts getElementInfoByXpath`）
- `AbstractInterface` 新增 `scroll_element_by_xpath_into_view()` 和 `scroll_element_into_view()` 抽象方法

#### 6. 动作执行引擎
- 新增 `_execute_planned_action()` 支持 7 种动作类型：Tap、Input、Hover、Scroll、KeyboardPress、Sleep、Assert
- 新增 `_actions_to_yaml_workflow()` 将动作序列序列化为 YAML 用于缓存
- 新增 `_replay_cached_plan()` 回放缓存的动作序列

#### 7. 小红书上传示例
- 新增 `examples/xhs_upload.py` — 小红书视频上传自动化完整示例
- 演示 `ai_wait_for`、`ai_action`、`ai_assert` 的实际用法

#### 8. 调试定位测试工具
- 新增 `tests/validation/test_debug_locate.py` — 在截图上标出红色框查看 AI 定位精度

### 修复

#### 9. API 请求重试机制
- HTTP 请求新增指数退避重试（429/500/502/503/504），最多重试 3 次
- 解决中转服务临时不可用导致的请求失败

#### 10. ai_assert 提示词增强
- 断言标准改为「屏幕上可见即 pass」，不要求是当前活动页面（与 JS 版本对齐）
- 支持解析 AI 返回的 markdown 代码块包裹的 JSON

#### 11. hover() 支持 scrollIntoView
- 悬停前先将元素滚动到视口中心，与 click/input_text 行为一致

#### 12. scroll() 改用 mouse.wheel
- **之前**: 使用 `window.scrollBy`，对 SPA 内部滚动容器无效
- **现在**: 使用 `mouse.wheel`（与 JS 版本 `base-page.ts` 对齐）
- 默认滚动距离改为视口高度的 70%（之前为 100%）
- 滚动前先移动鼠标到视口中心（对应 JS `moveToPointBeforeScroll`）

---

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
