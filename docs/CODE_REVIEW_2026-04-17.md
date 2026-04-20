# pymidscene 代码审查报告

**审查日期**: 2026-04-17
**审查对象**: `pymidscene/` (Python 移植版本)
**对照基准**: `midscene-main/` (Midscene.js 官方源码)
**审查范围**: 已实现模块的行为对齐与 Bug 排查(不涉及尚未移植的 Android/iOS/CLI/WebDriver)

---

## 1. 执行摘要

本次审查以并行方式对 5 个子系统(Core Agent、Task Cache + Service Caller、Prompts、Playwright 集成、Models + Utils + Types + Env)逐文件对照 JS 源做行级比对。整体结论:

- **主体 API 可跑通**:Playwright 路径下的 `ai_click/ai_input/ai_locate/ai_query/ai_assert/ai_act` 等"Happy Path"在 Doubao/Qwen2.5-VL 上基本能工作,最近的 `b41af58` 也确实修掉了一个坐标转换 bug。
- **但与 JS 版本的行为契约已出现系统性偏差**:Planner 的 Prompt 与输出 Schema 完全不同;UI-TARS 支持形同虚设;qwen3-vl 会被当作 qwen2.5-vl 处理导致点击坐标错乱;HiDPI 屏幕所有坐标都会系统性偏移;Cache YAML 与 JS 不可互换;`ExecutionDump` 不是 JS 报告格式的超集。
- **公共 API 方法覆盖约 55-60%**:除已知未移植的 `ai_action` / `ai_wait_for` 外,`ai_tap / ai_hover / ai_boolean / ai_number / ai_string / ai_ask / ai_right_click / ai_double_click / ai_keyboard_press / describe / verifyLocator / runYaml / evaluateJavaScript / setAIActContext / destroy / flushCache / getActionSpace` 等同样缺失。
- **环境变量契约部分破裂**:`MIDSCENE_MODEL_MAX_TOKENS / MIDSCENE_RUN_DIR / MIDSCENE_REPLANNING_CYCLE_LIMIT / MIDSCENE_CACHE_MAX_FILENAME_LENGTH / MIDSCENE_FORCE_DEEP_THINK / MIDSCENE_LANGSMITH_DEBUG / MIDSCENE_LANGFUSE_DEBUG` 等在 Python 端未被识别。

**结论**:不建议宣称"与 midscene.js 功能对齐"。当前状态更接近"midscene.js 的 Python 灵感复刻",在未修复 §4 中的 Critical 项之前,混合 JS/Python 部署会产生静默错误。

---

## 2. 严重程度约定

| 级别 | 含义 |
|---|---|
| **Critical** | 导致静默错误结果、数据丢失、跨语言互操作断裂、或整个模型家族失能 |
| **High** | 关键功能缺失或行为与文档/JS 不一致,用户可感知 |
| **Medium** | 边界行为差异,特定场景下触发问题 |
| **Low** | 样式/性能/可维护性类,不影响正确性 |

---

## 3. Critical 问题清单(优先修复)

### C1. Planner Prompt 与响应 Schema 完全背离 JS
- **位置**:`pymidscene/core/ai_model/prompts/planner.py:12-77` ↔ `midscene-main/packages/core/src/ai-model/prompt/llm-planning.ts:148-302`
- **JS 契约**:XML 流(`<thought><note><log><error><action-type><action-param-json><complete-task success>`)、每次只规划**一个**动作、`actionSpace` 由运行期 `DeviceAction[]` 动态渲染、locate 参数里携带 `bbox` 字段给 VLM。
- **Python 契约**:硬编码 6 个动作(Tap/Input/Hover/KeyboardPress/Scroll/Sleep)、要求模型**一次返回 3 个动作**的 JSON `{actions:[{type,param,thought}], shouldContinuePlanning}`、locate 只传 `prompt`、无 bbox。
- **影响**:任何用 midscene 官方 Prompt 训练/微调过的 VLM(Doubao-vision、qwen-vl、UI-TARS)几乎必定回 XML,Python 的 `parse_planning_response` 一律抛 `Failed to parse planning response`;同时丢失 bbox 快速通道 → 每次点击多走一次 locator 调用,token 成本与延迟翻倍。

### C2. UI-TARS 动作解析与坐标转换全部缺失
- **位置**:`pymidscene/core/ai_model/models/doubao.py:118-194`、`pymidscene/core/ai_model/prompts/__init__.py`(无 `ui-tars-planning`)↔ `midscene-main/packages/core/src/ai-model/ui-tars-planning.ts:42-310`
- **JS 行为**:解析 `Thought:/Action:` 文本、`<bbox>x1 y1 x2 y2</bbox>` → 中心 `(x,y)`、处理 `finished/drag/hotkey/scroll`、剔除 `[EOS]` 与 `Reflection:` 段。
- **Python 行为**:只有 `preprocess_doubao_bbox_json`(空格换逗号),完全不识别 UI-TARS 语法。
- **影响**:`MODEL_FAMILY=vlm-ui-tars*` 配置下任意 `ai_act` 都产出空动作,用户可能以为"AI 什么都没做"却看不到错误。

### C3. qwen3-vl 被当作 qwen2.5-vl 处理 → 点击坐标错乱
- **位置**:`pymidscene/core/ai_model/models/qwen.py:108` 硬写 `model_family="qwen2.5-vl"`
- **JS 行为**:按 `MIDSCENE_MODEL_FAMILY` / `MIDSCENE_USE_QWEN3_VL` 分支,qwen3-vl 走 0-1000 归一化坐标(见 `common.ts:225-229` 默认分支)。
- **Python 后果**:qwen3-vl 返回归一化坐标,却被 `adapt_qwen2_5_bbox`(utils.py:314-336)当作像素直通 → 所有点击坐标被缩小到 `width/1000` 的位置,实际点中页面左上角一小块。

### C4. HiDPI 屏幕下所有坐标系统性偏移(DPR 恒为 None)
- **位置**:`pymidscene/web_integration/playwright/page.py:86, 92` 返回 `dpr: None`;`pymidscene/core/agent/agent.py:509-510` 用 viewport 尺寸当图像尺寸传入 `adapt_bbox`
- **JS 行为**:`base-page.ts:316-327` 始终读 `window.devicePixelRatio`,下游 rect 运算用 `viewportSize.dpr` 校正。
- **影响**:Mac Retina / Windows 200% 缩放 / 手机 DPR=2~3 的屏幕上,AI 返回的 bbox(是基于 JPEG/PNG 像素)被错误地按 CSS 像素解释,点击坐标偏移 50% 或更多。该问题与 C3 会叠加。

### C5. Cache YAML 与 JS 不可互换
- **位置**:`pymidscene/core/agent/task_cache.py:58`(`MIDSCENE_VERSION = "1.0.0"`, 硬编码常量)、`:87`(MD5 前 8 位作文件名 hash)、`:181-183`(`json.dumps(sort_keys=True)` + 字符串相等)、`:277-282`(未迁移 `xpaths` 字段)
- **JS 参照**:`task-cache.ts:49, 242-249`(最低版本 `0.16.10`,低于则警告丢弃)、`:82`(`generateHashId`)、`:135`(`isDeepStrictEqual`)、`:138-146`(`xpaths → cache.xpaths` 迁移)。
- **多重后果**:
  1. Python 写的 `midsceneVersion: "1.0.0"` **低于** JS 最低支持版本 `0.16.10`,JS 读到会整份丢弃并告警。
  2. 长 cacheId 的文件名 hash 两边不同 → 同一用例产出**两份 cache 文件**。
  3. Python 查找只用 `prompt` 字面相等,JS 用 `TUserPrompt` 对象深比,混合使用时命中率暴跌。
  4. 老版 JS 的 `xpaths` 顶层字段在 Python 中直接被丢弃。

### C6. `ExecutionDump` / 报告格式不是 JS 超集
- **位置**:`pymidscene/core/types.py:179-208`(`to_dict`/`from_dict` 带 `# ... 其他字段` 占位注释,`from_dict` 返回空 `tasks=[]`),`pymidscene/core/agent/agent.py` 无 `appendExecutionDump` 的 per-runner dedupe(JS 用 `executionDumpIndexByRunner: WeakMap`,见 `agent.ts:506-522`)。
- **影响**:Python 产出的 `.web-dump.json` 缺 `ScreenshotItem` 还原、timing、hit_by、usage 等字段;replan 重试会重复 append 同一 runner 的 dump 记录。下游可视化报告、CI 集成工具不能直接解析 Python 产物。

### C7. `ai_act` 缓存命中路径不写 report
- **位置**:`pymidscene/core/agent/agent.py:1022-1048` 仅调 `_replay_cached_plan`
- **JS 参照**:`agent.ts:913-923` 命中后先 `loadYamlFlowAsPlanning`(向报告写入 yaml 快照)再 `runYaml`
- **影响**:cache 命中的执行在 report 里**完全看不见**,"为什么这次跑了 10 秒却一条记录都没有"的排查盲区。

### C8. `ai_assert` 丢弃 `keepRawResponse` 契约
- **位置**:`pymidscene/core/agent/agent.py:879-976` 硬抛 `AssertionError`
- **JS 参照**:`agent.ts:1174-1248`,当 `opt.keepRawResponse=true` 时**返回** `{pass, thought, message}` 而不是抛异常;还支持 `domIncluded / screenshotIncluded`。
- **影响**:任何"断言但不中断,拿回结果自行决定"的 JS 测试脚本移植过来会直接崩。

### C9. 环境变量契约多处破裂
- **Python 未识别但 JS 认可的关键环境变量**(不完全列表):
  - `MIDSCENE_MODEL_MAX_TOKENS` / `OPENAI_MAX_TOKENS`(qwen.py:33 硬编码 4096)
  - `MIDSCENE_RUN_DIR`(`task_cache.py:107` 固定 `./midscene_run/cache`)
  - `MIDSCENE_CACHE_MAX_FILENAME_LENGTH`(task_cache.py:57 硬编码 200)
  - `MIDSCENE_REPLANNING_CYCLE_LIMIT`(agent.py:1051 硬编码 `max_replan_cycles=10`,JS 默认 20,UI-TARS 40,AutoGLM 100)
  - `MIDSCENE_FORCE_DEEP_THINK`(doubao.py 未读取)
  - `MIDSCENE_LANGSMITH_DEBUG` / `MIDSCENE_LANGFUSE_DEBUG`(可观测性静默禁用)
  - `MIDSCENE_DEBUG_MODE` / `MIDSCENE_DEBUG_MODEL_PROFILE` / `MIDSCENE_DEBUG_MODEL_RESPONSE`
  - `MIDSCENE_USE_QWEN3_VL`(与 C3 联动)
- **Python 多出但 JS 没有的变量**:`MIDSCENE_USE_ANTHROPIC`(constants.py:61)
- **Python `MODEL_FAMILY_VALUES`(constants.py:69-79)与 JS 不一致**:多出 `openai / claude`,缺失 `glm-v / auto-glm / auto-glm-multilingual / gpt-5`。`validate_model_family` 将拒绝合法 JS 配置并接受非法家族名。

### C10. 流式响应回调契约不兼容
- **位置**:`pymidscene/core/ai_model/service_caller.py:273-287` 传 `on_chunk(str)`
- **JS 参照**:`service-caller/index.ts:336-362` 传 `CodeGenerationChunk{content, accumulated, reasoning_content, isComplete, usage}`,并会合成最终完成帧(附 usage 估算)。
- **影响**:任何共享编排层(如 JS 的 recorder/LangChain 适配)无法复用 Python 产出的流。

---

## 4. High 问题清单

### H1. `ai_locate` Cache 键与返回形态错位
- Python `agent.py:397-434` 只查 `xpaths[0]`,JS `task-cache.ts:193` 遍历整个 `xpaths[]` 做 fallback;Python 返回 `LocateResultElement`,JS 返回 `{rect, center, dpr?}`。

### H2. `ai_wait_for` 默认值/异常吞噬
- 位置:`agent.py:1395-1447`。默认 `timeout=30` 秒 / `interval=2`,JS 是 `timeoutMs=15000 / checkIntervalMs=3000` 且强制 `interval≤timeout`。`except (AssertionError, Exception)` 把 `httpx.ConnectError`、`TimeoutError`、`asyncio.CancelledError` 都当"断言未过",把模型离线/网络故障静默转成长时间轮询。

### H3. `_execute_planned_action` 把失败记成已执行
- `agent.py:1144` 在调用底层动作**之前**就 `all_executed_actions.append(action)`;`:1391-1393` 捕获 Exception 返回 False。下一轮 replan 读到的 conversation_history 里会包含"已执行"的失败动作,AI 会基于错误状态继续规划。

### H4. `ai_act` 空计划当成功
- `agent.py:1124-1130`:AI 连续返回空 actions 两次后 break 并 `return True`。JS 在此抛 `TaskExecutionError`。

### H5. `ai_act` YAML 包装层缺失
- `agent.py:1213-1244` 直接把动作列表 yaml dump,JS(`agent.ts:948-965`)包一层 `MidsceneYamlScript{tasks:[{name, flow: yamlFlow}]}`。缓存产物不可被 JS `runYaml` 消费,且 Python 读回时 `_replay_cached_plan` 会命中 `"Cached workflow is not a list"` 分支(`agent.py:1263`)。

### H6. `clearInput` 在 macOS 上会误删单字符
- `page.py:265-276` 恒用 `Ctrl+A, Backspace`。JS `base-page.ts:481-504` 按 `process.platform` 分支,macOS 用 `Meta+a`。Python 在 Mac 上 `Ctrl+A` 把光标移到行首,Backspace 只删一个字符。

### H7. `keyboard.type` 无 delay → React/受控输入丢字
- `page.py:279` `keyboard.type(text)`;JS `base-page.ts:447` 用 `{delay: 80}`。

### H8. `click/hover/input_text` 三处重复实现"滚动+重取中心"
- `page.py:132-184, 211-255, 292-330`:每个动作内部再调 `elementFromPoint` → `scrollIntoView` → 重新取中心。与 agent 层已有的 `scroll_element_by_xpath_into_view`(`agent.py:672-680`)叠加,最终 `elementFromPoint` 可能解析到覆盖层/父节点,点错目标。JS 的 `mouse.click` 只接受坐标直接点,scroll 是正交步骤。

### H9. 关键方法缺失(除 `ai_action`/`ai_wait_for` 外)
| JS 方法 | Python 状态 |
|---|---|
| `aiTap / aiRightClick / aiDoubleClick` | 缺失 |
| `aiHover / aiKeyboardPress`(公开 API) | 缺失(只在内部调度里有) |
| `aiBoolean / aiNumber / aiString / aiAsk` | 缺失 |
| `describeElementAtPoint / verifyLocator` | 缺失 |
| `runYaml / evaluateJavaScript` | 缺失 |
| `setAIActContext / freezePageContext / unfreezePageContext` | 缺失 |
| `recordToReport / logScreenshot / flushCache / destroy` | 缺失 |
| `getActionSpace / getUIContext` | 缺失 |
| `addDumpUpdateListener` 系列 | 缺失 |

### H10. 关键 Prompt 文件缺失
- `describe.ts`(元素描述,locate cache 命名需要)
- `llm-section-locator.ts`(大页面二段定位)
- `order-sensitive-judge.ts`(序数描述不缓存)
- `ui-tars-planning.ts`(见 C2)

### H11. `service_caller` 多项能力缺失
- 无 SOCKS 代理;无 `deepThink` 家族映射(qwen3-vl `enable_thinking` / doubao `thinking.type` / gpt-5 `reasoning.effort`);无 AutoGLM 专用 `top_p/frequency_penalty`;无 `createOpenAIClient` 钩子;错误不再包装 troubleshooting URL。流式 retry 会重放副作用型 `on_chunk`。

### H12. 截图格式差异
- Python PNG + 纯 base64(`page.py:108-114`);JS JPEG q=90 + `data:image/jpeg;base64,` 前缀。下游 prompt/recorder 期望 data-URL 会解析失败,且 PNG 体积更大 → 多花 token 与时延。

---

## 5. Medium 问题选摘

- **M1. Locator 生成的 XPath 单一且脆弱**:`page.py:520-539` 只生成一个 `tag[n]` 路径;JS 由 `midscene_element_inspector.getXpathsByPoint` 返回多条候选(`base-page.ts:190-196`),命中率显著更低。
- **M2. `resize_image_base64` 丢 MIME 与 data URL**(`utils.py:120-154`)。
- **M3. `calculate_hash` 用 MD5**(`utils.py:20-22`),JS 用 sha256;跨语言 cache key 不对齐。
- **M4. `preprocess_doubao_bbox_json` 正则在循环里重新全扫**(`doubao.py:215-217`),大响应 O(n²)。
- **M5. `ai_scroll` scrollType 未做 legacy 归一化**:JS 会把 `once → singleAction`、`untilBottom → scrollToBottom` 做别名映射;Python 未映射,`"untilBottom"` 会静默走 else 分支。
- **M6. `ai_scroll(locate_prompt=...)` 绕开 `buildDetailedLocateParam`**,丢 deepThink/DPR 修正。
- **M7. `_call_with_httpx` 每轮重开 `httpx.Client`,且不捕获 `ConnectionError/ReadTimeout` → 不重试**(`agent.py:321-343`)。
- **M8. `is_qwen_vl` 判断过宽**:`service_caller.py:247-255` 子串 `"qwen" and "vl"` 会把 `vl_high_resolution_images=true` 错发给 qwen3-vl / qwen-vl-plus,部分服务端会 400。
- **M9. `ai_input` 不支持 `mode: replace|clear|typeOnly|append`**;总是 replace;不接受数字。
- **M10. `ai_query` 走自写 XML prompt 而非 `createTypeQueryExecution`**,事件流少一个"after 截图"。
- **M11. `afterInvokeAction` 等效钩子缺失**:`input_text/hover/scroll` 之后都不等待 `waitForNavigation + waitForNetworkIdle`,下一帧截图可能拍在导航中。
- **M12. `point_to_bbox`**(utils.py:171-194)对所有输入一律限幅到 1000,像素空间调用者超 1000 会被错误裁切(与 JS 行为一致但 docstring 误导)。
- **M13. `task_cache` plan 与 locate 顺序不排序**(`:345-357`),JS `task-cache.ts:325-334` 会排序,导致 round-trip 产生无意义 diff。

---

## 6. Low / 可维护性

- 六行以内重复代码:`preprocess_doubao_bbox_json` 在 `doubao.py` 与 `shared/utils.py:88-104` 各有一份,易漂移。
- `WebUIContext` 作为方法内局部类每次创建(`page.py:64-68`)。
- `cache_strategy` 校验缺失(`agent.py:99-105`),JS 会验证枚举值。
- `ai_action = ai_act` 在类体里赋值(`agent.py:1211`),不是方法绑定,子类覆写 `ai_act` 时 `ai_action` 不随动。

---

## 7. 跨语言互操作性清单(关键)

| 共享契约 | 是否互通 | 原因 |
|---|---|---|
| `.midscene.yaml` cache | ❌ | C5:版本、hash、比较算法、xpaths 迁移均不同 |
| `.web-dump.json` 报告 | ❌ | C6:`ExecutionDump.to_dict` 字段残缺 |
| `MIDSCENE_*` 环境变量集 | ⚠️ | C9:核心一致,但数条 Python 未识别 |
| Streaming 回调 shape | ❌ | C10 |
| Playwright 截图格式 | ❌ | H12 (PNG vs JPEG data-URL) |
| Prompt / 模型输出 schema | ❌ | C1, C2 |

---

## 8. 修复优先级建议

**P0(阻塞正确性,建议立即修)**
1. C3 — `QwenVLModel.model_family` 改由配置驱动(或直接按 `MIDSCENE_USE_QWEN3_VL` 分流到归一化路径)。**一行改动能避免大面积误点击**,建议放在第一位。
2. C4 — `WebPage.get_size` 返回真实 `devicePixelRatio`;`agent.py:509-510` 把图像尺寸改为截图实际像素 × DPR。
3. C5 — `MIDSCENE_VERSION` 改为从 `pyproject.toml` 读取 semver;hash 换 sha256;查找改深比。
4. C1 — 要么把 Planner 迁到 JS 的 XML 契约并接 `actionSpace`,要么在 README 明确声明"我们用自有的 JSON 动作 schema,不兼容 midscene 官方 Prompt"。

**P1(关键功能性)**
5. C2 — UI-TARS 解析器;否则在 `ModelConfig` 层拒绝 `vlm-ui-tars*` 并报错,避免静默空动作。
6. C7, C8, H3, H4, H5 — 修正 `ai_act` / `ai_assert` 行为与 JS 对齐。
7. H6, H7, H8, H11 — Playwright 动作层修正(mac clearInput、type delay、去双滚动、afterInvokeAction 钩子)。
8. C9 — 补齐关键环境变量读取;`MODEL_FAMILY_VALUES` 与 JS 对齐。

**P2(功能补齐)**
9. H9 — 补齐缺失的公共 `ai_*` 方法。
10. H10 — 补齐 `describe / section-locator / order-sensitive-judge` prompts。
11. C6 / C10 — 报告与流式回调契约对齐。

**P3(可维护性)**
12. 抽掉 Playwright 动作三处重复的滚动逻辑;`preprocess_doubao_bbox_json` 单点化;`WebUIContext` 顶层化。

---

## 9. 审查方法与覆盖说明

- 以 `AGENTS.md` 中声明"已移植"的模块为审查对象,共 5 个子系统并行审查。
- 每条发现均附两侧 `file:line` 引用,便于定位。
- 未审查(按项目声明本就未移植):`ai_action`、`ai_wait_for` 骨架完整度、Puppeteer / Selenium / Android / iOS / CLI 目录、CLI、Evaluation、Visualizer、Bridge、Playground。
- **上报局限**:本报告基于静态对照,未运行两边 e2e 比对(如需 e2e,可另起 Playwright + 固定 VLM 录制重放)。

---

## 附录 A:参与审查的文件清单

- `pymidscene/core/agent/{agent.py, task_cache.py}`
- `pymidscene/core/ai_model/{service_caller.py, prompts/*.py, models/*.py}`
- `pymidscene/web_integration/{base.py, playwright/{agent.py, page.py}}`
- `pymidscene/shared/{utils.py, env/{constants.py, model_config_manager.py}}`
- `pymidscene/core/types.py`

对应 JS 源:
- `midscene-main/packages/core/src/agent/{agent.ts, task-builder.ts, tasks.ts, task-cache.ts, utils.ts, ui-utils.ts}`
- `midscene-main/packages/core/src/ai-model/{index.ts, llm-planning.ts, ui-tars-planning.ts, inspect.ts, service-caller/index.ts, prompt/*.ts}`
- `midscene-main/packages/web-integration/src/{web-page.ts, web-element.ts, utils.ts, playwright/{index.ts, page.ts, ai-fixture.ts}, puppeteer/base-page.ts}`
- `midscene-main/packages/core/src/{utils.ts, types.ts, common.ts}`
- `midscene-main/packages/shared/src/env/{constants.ts, types.ts}`
