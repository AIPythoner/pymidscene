# PyMidscene 更新日志

## [Unreleased]

## [0.5.1] - 2026-06-16

感知层(insight / extraction / locate)JS 保真对齐第一批。对前几轮未专门审过的
感知侧做对抗审查(24 发现 / 16 确认),先修一批清晰、低风险的真实差异。两个动
locate 主链路的大项(deepThink 两段式 section-zoom、auto-glm locate 分支)留待
下一轮单独做。

### Fixed

- **数据提取解析** `parse_xml_extraction_response` 从裸 `json.loads` 改为复用
  `safe_parse_json_with_repair`(去 markdown 代码块围栏 + json_repair 修复 + 递归
  trim,对齐 JS safeParseJson)—— 此前模型把 JSON 包在代码块里或带尾逗号会直接
  报错,而 JS 能恢复
- **`ai_boolean` / `ai_number` / `ai_string`** 的 demand 从 `{value: "boolean — …"}`
  改成 `{result: "Boolean, …"}`(对齐 JS createTypeQueryTask,也与 extractor 系统
  prompt 里的示例一致)—— 此前 prompt 示例用 `result` 键、代码却取 `value`,模型
  照示例回 `result` 时会取不到值
- locate / 规划截图的 `image_url` 补 `detail: "high"`(对齐 JS,避免供应商默认
  `auto` 降采样削弱定位精度)
- `ai_locate` 在模型返回 `{"bbox": [], "errors": [...]}` 时把"为什么没找到"带进
  日志/记录(对齐 JS service.locate 的 errorLog),不再塌成通用 "no bbox"
- `extract_data_prompt` 始终输出 `<PageDescription>` 块(对齐 JS,空也带)

### Notes(留待下一轮)

- **deepThink 两段式 section-zoom 定位**(AiLocateSection → 裁剪 → 带偏移重定位)
  在 Python 尚未实现;`section_locator.py` 的 prompt 已就位但未接线。这是动 locate
  主链路的较大特性,单独一轮做。
- **auto-glm 作为 insight/locate 模型**时 `ai_locate` 缺专用分支(auto-glm 是
  Android 规划模型,作 web grounding 少见);helper 已就位,与 deepThink 同轮接线。

## [0.5.0] - 2026-06-16

把 **默认 LLM 规划器**从 JSON 批量动作契约重写成 Midscene.js 现行的 **XML 单动作
契约**(finding [17])。这是对核心 agentic 循环的较大行为变更(故升 minor),公开
API 不变(`ai_act(task) -> bool`),旧缓存仍可回放。实现后经 4 维对抗审查(17 发现
/ 8 确认),修完全部确认项再发布。仅影响默认规划器;UI-TARS、auto-glm 各自的
规划器与执行器、动作集、缓存格式均不变。

### Changed

- **默认规划器:JSON 批量 → XML 单动作契约**(对齐 JS `llm-planning.ts` /
  `tasks.ts`):
  - 每轮只规划 **一个** 动作,执行后重新截图再规划,直到模型返回
    `<complete-task success="true|false">`;不再"一次规划至多 3 个动作"
  - 模型用 XML 标签返回 `<thought>/<note>/<log>/<error>/<action-type>/`
    `<action-param-json>/<complete-task>`;`<error>` 与 `success="false"` → 抛错
  - 新的**对话历史**:每轮把当前截图 + 模型上一轮的原始 XML 追加进多轮消息
    (只保留最近 2 张截图,更早降级为占位文本);`<note>` 让模型把信息带到
    后续步骤(截图会被裁掉)
  - `parse_planning_response` 现解析 XML(`extract_xml_tag` + complete-task
    正则);action-param-json 复用 `safe_parse_json_with_repair`(json_repair +
    doubao/UI-TARS bbox 预处理,与 JS safeParseJson 一致)
  - `ai_act` 拆分:默认走 `_ai_act_xml_loop`,UI-TARS/auto-glm 走
    `_ai_act_legacy_loop`(原批量循环原样保留),之后共用缓存写入 + 报告收尾

### Fixed

- 规划动作 `LongPress`、`Assert` 此前不在 `_FLOW_KEY_BY_ACTION_TYPE` 映射里 →
  成功执行后被静默丢出缓存 YAML,回放缺步骤/漏断言。现两者都能进/出缓存往返
- 默认规划器解析 action-param-json 现走 `safe_parse_json_with_repair`,LLM 常见的
  尾逗号/单引号/缺括号可被修复(此前手搓的弱解析会直接报错并把任务判失败)
- complete-task `success` 改为精确小写比较(对齐 JS `=== 'true'`)
- 对话历史截图裁剪的内层遍历方向、`_readable_time` 的格式后缀对齐 JS

### Docs

- README 增加 **CLI** 一节(`pymidscene` 跑 YAML 脚本)+ 补全示例索引(android/ios/cli)
- CONTRIBUTING 增加"发布到 PyPI"的维护者步骤(build / twine check / 干净环境冒烟 / upload / tag)

### Chore

- 发版就绪:`python -m build` 干净产出 wheel+sdist(报告模板资源已打包、无多余文件),
  `twine check` 通过,全新 venv 安装后 `import` / `pymidscene --help` / 报告生成冒烟均过
- `pyproject.toml` 增加 `[tool.poetry.urls]`(Source / Changelog / Issues)

## [0.4.0] - 2026-06-16

新增 `pymidscene` 命令行:用自然语言 YAML 脚本驱动 web / Android / iOS 自动化,
对齐 Midscene.js 的 `@midscene/cli`(命令面 + YAML 脚本/flow 执行契约)。实现后经
4 维度对抗审查(36 发现 / 21 确认),修完全部确认项随特性一起发布。

### Added

- **`pymidscene` CLI**(`pymidscene <script.yaml>` 或 `python -m pymidscene.cli`),
  新增 `[tool.poetry.scripts]` 入口:
  - 三种脚本选取:位置参数(文件/目录/glob)、`--files a.yaml b.yaml`、
    `--config suite.yaml`(索引 yaml 的 `files:` 列表;相对 glob 相对 config 目录)
  - 标志:`--concurrent`、`--continue-on-error`、`--headed`、`--keep-window`、
    `--share-browser-context`、`--summary`、`--dotenv-override/-debug`,以及
    `--web.* / --android.* / --ios.*` 点号命名空间目标覆盖
  - YAML 脚本:`web|android|ios|interface`(+ 废弃 `target`=web)+ `config`/`agent`
    + `tasks[].flow[]`;`${VAR}` 环境插值、数字 deviceId 自动加引号、`target`→`web`
  - flow 步骤:`ai/aiAction`、`aiTap/aiHover/aiRightClick/aiDoubleClick/aiClearInput`、
    `aiInput`(新旧式 + mode)、`aiKeyboardPress`(可选 locate 先聚焦)、`aiScroll`、
    `aiAssert`、`aiQuery/aiNumber/aiString/aiBoolean/aiAsk/aiLocate`、`aiWaitFor`
    (毫秒)、`sleep`、`javascript`、`aiDragAndDrop/LongPress/Swipe`(`ai_locate` 桥接
    坐标)、`launch/runAdbShell/runWdaRequest`
  - 批量编排:asyncio 并发(信号量)、`continueOnError` 首错即停后续记 `notExecuted`、
    per-file 结果增量写 `--output` JSON、汇总索引 JSON + 退出码(全成功=0,否则=1)
  - `--share-browser-context` 跨 web 文件共享同一 **context**(共享 cookie/会话)
  - `examples/cli/`(web / android / suite 示例)+ `docs/CLI.md`

### Notes(与 JS 的有意取舍)

- `--web.* / --android.*` 目标覆盖只在脚本声明了同类目标(或无目标)时叠加,不会给
  一个 android 脚本平白塞 web 块再报 "multiple targets"(比 JS 更宽松)。
- 批量里某个 yaml 解析失败记为该文件 `failed` 并继续其余文件(退出码仍 1),而非整批
  抛错中止。`--files` 匹配 0 个文件时退出码 1(fail-loud,JS 为 0)。
- summary 的 `generatedAt` 用确定性 ISO-8601(JS 用 locale 字符串)。
- `serve`(本地静态服务器)与 `bridgeMode`(Chrome 扩展桥)暂不支持。

## [0.3.7] - 2026-06-16

回归/集成自审: 对前六轮重度修改的热点路径做对抗验证自审, 修掉 9 个改动引入或
互相干扰的回归; 另清两个 Android 小 bug。

### Fixed

**UI-TARS 执行集成回归(第五轮改动引入):**

- **UI-TARS Input / Scroll 动作此前把模型的 `thought`(推理文本)塞进 param.prompt** → 执行器把它当元素描述去 `ai_locate`/`ai_input`:
  - type/Input: 本应往已聚焦元素直接输入, 却对推理句做一次必然失败的定位 → 输入失败 → 多余 replan
  - scroll/Scroll: 本应滚整个视口, 却对推理句做一次多余的 ai_locate
  现 UI-TARS 各动作 param 不再带 `prompt`(对齐 JS), Tap/DoubleClick/RightClick 用 locate.center 直点

**调用/解析回归:**

- **family / deepThink / vl_high_resolution 请求参数此前在 live 路径完全不生效** —— 这些只在 `service_caller.call_ai` 里整形, 而 agent 实际走 `_call_with_httpx`(从不调 call_ai)。现 `_call_with_httpx` 也应用: qwen2.5-vl 高分辨率、auto-glm 采样参数、`MIDSCENE_FORCE_DEEP_THINK` 驱动的家族 thinking 参数
- `ai_assert` 在模型返回 JSON 数组时 `AttributeError` 崩溃(第六轮 extract_json 支持顶层数组后暴露) → 现非 dict 一律按解析失败处理
- `_call_with_httpx` 对 `content==null`(部分 OpenAI 兼容端点的过滤/工具响应)此前让 None 流进 `safe_parse_json` 抛 `TypeError`; 现规整为 "" (与原生路径一致)
- 规划响应 `"param": null` 此前 `.get("param", {})` 返回 None → 各执行分支 AttributeError 被吞成失败; 现统一规整为 `{}`
- `get_default_run_manager` 单例缓存键用 `str(Path)` 与原始字符串比较, Windows / 带尾斜杠输入下反复重建单例; 改用 Path 规范化比较

**Android(清理小遗留):**

- 只设 `MIDSCENE_ADB_REMOTE_PORT` 不设 host 时端口此前被静默忽略; 现只给 port 时 host 回落本机
- `clear_input` 改为交替 DEL(67)+FORWARD_DEL(112)各 100 次(对齐 appium-adb clearTextField), 此前 MOVE_END+批量 DEL 在多行输入框里清不干净行后文本

第六轮审查:首次系统审查 config / 非 OpenAI 调用路径 / 支撑层(env 配置解析、
Gemini/Anthropic 原生调用、deep_think 与家族专用参数、element_marker、
run/log、JSON 修复)。25 条经对抗验证确认的发现, 修复如下。

### Fixed

**调用路径(确定性 / 硬失败):**

- **Gemini/Anthropic 原生路径此前不发 temperature** → 用各 provider 的服务端默认(约 1.0)采样, VLM 坐标/JSON 输出不确定、不可复现。现都发 `temperature`(默认 0, 对齐 JS 给所有 provider 发 temperature=0)
- **gpt-5 deepThink 此前把 `reasoning` 当顶层 kwarg 传给 OpenAI SDK** → 该 SDK 无此参数, 每次 gpt-5 deep_think 调用都 `TypeError` 硬失败。现经 `extra_body` 传入(落到 JSON body 顶层, 与 JS 一致)
- Gemini/Anthropic 原生路径补上重试(对齐 JS: retry_count+1 次, 间隔 retry_interval)与空响应报错(`empty content from AI model`); 此前两条路径完全无重试、空响应静默返回 ""
- Gemini 系统提示改走 `system_instruction`(而非折叠进 user turn 产生两个连续 user 轮次)

**deep_think / 家族参数:**

- qwen3-vl `enable_thinking` 此前嵌在多余的 `config` 包装里; 现直接放 `extra_body` 顶层(对齐 JS 展开后的 wire 格式)
- `vl_high_resolution_images` 此前因模型名兜底会误加到 qwen3-vl / qwen-vl-max 上; 现严格按 `family == 'qwen2.5-vl'` 触发(对齐 JS)
- 显式设了 deepThink 但 family 不支持时给出可见 warning(对齐 JS), 不再静默

**env / 配置解析:**

- default intent 下补回三个 legacy 兜底: `MIDSCENE_OPENAI_SOCKS_PROXY` / `MIDSCENE_OPENAI_HTTP_PROXY` / `MIDSCENE_OPENAI_INIT_CONFIG_JSON`(对齐 JS)
- 非法 `MIDSCENE_MODEL_INIT_CONFIG_JSON` 改为抛错(快速失败, 对齐 JS), 不再静默忽略
- 负数 retry_count/interval 改为抛错(此前被同一 try/except 吞掉); timeout 用 `int(float())` 接受小数字符串(对齐 JS `Number()`)

**run / log:**

- `MidsceneRunManager` 此前忽略 `MIDSCENE_RUN_DIR`, 导致 report/dump 与 cache 落在不同根目录; 现读取该变量(对齐 JS), 并在 run 目录写自包含 `.gitignore`, run 目录创建失败时回落临时目录
- 报告文件名前缀支持 `MIDSCENE_REPORT_TAG_NAME`(对齐 JS getReportFileName)
- 日志时间戳从单个 aware 时刻派生(此前 `datetime.now()` 取样三次 + 死代码 `or "+00:00"`)

**JSON 修复:**

- 顶层数组(`[{...},{...}]`)此前被贪婪对象匹配截成第一个对象 → 现数组感知提取, 多元素完整解析
- 空/纯空白内容改为报解析失败(此前 json_repair 返回空串让调用方拿到 "")
- 修复结果只接受 dict/list 形态; 非 JSON 散文经 json_repair 还原成裸标量时视为失败兜底, 不再返回标量

**报告:**

- HiDPI 截图 CSS 归一化失败时改为报错(此前静默降级 → 模型坐标与点击/标注错位 dpr 倍, 每次点击都偏)

### Notes（确认存在但有意不改）

- httpx(OpenAI 兼容)路径仍仅在 temperature>0 时发送: 这是为兼容拒绝 temperature 的推理模型的有意取舍(原生路径已补 temperature=0)
- UI-TARS model_description 字符串与 JS 不同(报告显示用, Python 从 family 派生); MIDSCENE_FORCE_DEEP_THINK 的作用域、MidsceneLogManager(基本未用)未改

第五轮审查:首次系统性对照 JS 审查此前未覆盖的 model / coordinate / prompt /
parser 层（坐标适配、AI service caller、UI-TARS 与 auto-GLM 解析器、prompts、
Doubao/Qwen 模型）。29 条经对抗验证确认的发现, 修复如下。

### Fixed

**坐标（每个 misclick 一类模型家族 → 最高优先级）:**

- **UI-TARS 坐标 off-by-1000**: `_parse_start_box` 此前对 0-1000 网格坐标不除以 1000(旧的 `if 0<=x<=1` 启发式对真实整数输入永不触发), 每个 UI-TARS Tap/DoubleClick/RightClick/Drag 点都偏离约 1000 倍。现严格复刻 `@ui-tars/action-parser` + `getPoint`: 所有 box 数字除以 1000、取前两个 × 屏幕尺寸; 内联 `<bbox>` 路径同样修正
- **所有 bbox 适配器改用 round-half-up**(`js_round`, 对齐 JS `Math.round`): Python 内置 `round` 是 banker's rounding, 在奇数宽视口上每个落在 .5 的坐标都与 JS 差 1px
- **未配置 model_family 时按模型名推断**: qwen3-vl(归一化 0-1000)用户没设 family 标志时此前被当成 qwen2.5-vl(像素)、每次点击错位; 现 qwen3 名字 → qwen3-vl(保留 Qwen-first 的 qwen2.5-vl 默认)
- Doubao 字符串数组项(如 `["940 445 969 490"]`)现只取前两个数字(对齐 JS, 当中心点处理), 而非展开成 4-值矩形; 8-角分支键于原始输入长度
- `adapt_bbox_to_rect` / `format_bbox` 保证宽高至少为 1(对齐 JS `adaptBboxToRect`), 退化的零面积 bbox(元素定位成一点)不再产生 width/height==0

**auto-GLM:**

- **Swipe→Scroll 方向此前两轴都与 JS 相反**(手指上滑本应"内容下移"却给出相反方向): 现 `absDeltaY>absDeltaX` 判主轴, `deltaY>0→up / deltaX>0→left`, 与 JS 一致
- Swipe 距离改用 round 且去掉 50px 下限(短滑动此前最多过冲 2.5 倍); 并附带从起点算的 `locate`, 使滚动从被滑动的元素/内部容器开始而非整个视口
- `AUTO_GLM_COORDINATE_MAX` 999 → 1000(对齐 JS 除以 1000); Back/Home 改发设备无关动作(执行器路由到原生 back/home, web 回落 history.back)
- 完整移植 JS 的中文 plan prompt(19 条规则)与两个 locate prompt; 此前被大幅截断

**UI-TARS 解析:**

- 多动作解析对齐 JS: 取最后一个 `Action:`/`Action：`(支持全角冒号)之后的内容、按空行切分多个动作块、每块不再要求 `Action:` 前缀; 单个 thought 共享给所有动作
- hotkey 键名经别名表归一化(`ctrl c`→`Control+c`, `page down`→`PageDown`), 而非原样透传

**AI service caller:**

- **max_tokens 此前硬编码 4096** 且 `MIDSCENE_MODEL_MAX_TOKENS` / `OPENAI_MAX_TOKENS` 从不读取 → 默认把大响应截断成不完整 JSON 解析失败。现读取这两个环境变量, 未配置时省略该字段(OpenAI 兼容路径)由 provider 用其默认上限; Anthropic 必填路径未配置时用 8192
- 流式调用移出重试循环(对齐 JS): 流式中途失败重试会向消费者重复推送增量
- 失败统一包成带模型名 + troubleshooting URL 的错误(对齐 JS), 不再裸抛 OpenAI/httpx 异常; 流式现在也对 reasoning-only 增量推送 chunk

### Notes（确认存在但有意不改）

- planner prompt 用 JSON 批量动作而非 JS 的 XML 单动作契约: Python 的 prompt+parser 内部自洽, 重写为 XML 契约是大规模架构改动, 暂保留
- UI-TARS `type` content 的 `\n` 仍materialize为真实换行(JS 保留字面 `\n`): Python 行为对实际输入更合理

第四轮审查收尾:报告元素详情面板、报告体积、LongPress 动作链路、Android 启动/截图健壮性。

### Fixed

**报告:**

- **Insight / Locate 任务写入 `task.log`(JS `ServiceDump` 结构)**:查看器的元素详情面板(detail-side)从 `log.matchedElement` 读取数据 —— 此前 Python 从不写 `log`,该面板永远为空。Locate 带 `userQuery.element`/`matchedElement`/`matchedRect`,Assert 带 `assertion`/`assertionPass`/`assertionThought`,Query 类带 `dataDemand`/`data`,`taskInfo` 含耗时/rawResponse/usage
- **移除 `markedScreenshot` 字段**:JS 查看器无任何消费方,此前每个定位步骤白白多存一整张带标注的 base64 截图(报告体积显著下降);顶层 `matchedElement` 保留向后兼容

**动作链路:**

- **LongPress 全链路打通**:执行器新增 LongPress 分支(路由到各平台 `long_press`,Android 2000ms / iOS 1000ms / web 500ms 默认值);`WebPage.long_press` 按 JS base-page.ts:671-695 实现(duration 夹在 300-600ms);auto-GLM 规划出的 "Long Press" 不再被降级成 Tap(移动端长按与点按是完全不同的交互);通用 planner prompt 向 AI 暴露 LongPress 动作

**Android:**

- **launch() 失败不再静默成功**:`am start`/`monkey` 出错时打印到 stdout 但 exit code 为 0,现解析输出中的 Error/Exception 等标志并抛错(对齐 JS 的 "Failed to launch" 包装);"Warning: Activity not started"(app 已在前台)正确视为成功;URI 启动加 `-W` 等待;monkey 启动失败(无 LAUNCHER category)fallback 到 `am start -a MAIN -c LAUNCHER`
- **截图加 PNG 魔数校验**(对齐 JS device.ts:917-946):screencap 失败返回错误文本时显式报错;adbutils 截图传 `error_ok=False`,不再在失败时静默返回纯黑图

第三轮审查修复:清掉 0.3.2 审查中确认的遗留问题(架构级 + 行为发散 + 报告)。

### Fixed

**core:**

- **AI 调用不再阻塞事件循环**:所有规划/定位/断言/查询的同步 SDK·httpx 调用(含重试 sleep)改经 `asyncio.to_thread` 在工作线程执行;此前在 async 方法里直接同步调用,多 Agent / 嵌入 web 服务时整个 loop 被挂住数十秒
- **按意图选择模型配置**:规划走 `INTENT_PLANNING`、定位/断言/查询/ask 走 `INTENT_INSIGHT`(对齐 JS);此前全链路只用 default,`MIDSCENE_PLANNING_*` / `MIDSCENE_INSIGHT_*` 配置静默失效
- **缓存 updateOrAppend 语义**(对齐 JS `updateOrAppendCacheRecord`):locate/plan 缓存命中但失效时,重新定位/规划的结果**原地更新**旧记录;此前只会追加,坏记录永远排在前面、`.cache.yaml` 跨运行膨胀
- ai_act 同批动作中某个失败即中断本批进入 replan(后续动作往往依赖前一步结果),一次 ai_act 内累计失败超 5 次整体报错(对齐 JS `errorCountInOnePlanningLoop`);此前失败后继续执行同批剩余动作且无熔断
- 规划响应连续解析失败改为抛错(对齐 JS);此前静默降级为一次 ai_click 并报告"成功"
- ai_assert 提示词对齐 JS 的中性布尔判定;此前放宽为"屏幕任意位置可见即通过",侧边栏菜单里出现关键词也会让断言假阳性通过
- ai_locate 的 bbox 模型适配失败按"定位失败"处理(return None);此前回退用原始值 → 抛未捕获 ValueError 或把 0-1000 归一化坐标当像素误点
- ai_wait_for 轮询间隔扣除断言调用耗时(对齐 JS);此前实际周期 = AI 耗时 + interval,窗口内检查次数偏少易误报超时
- 规划动作 Input 允许空字符串 value("清空输入框",对齐 JS);此前空串被当参数缺失拒绝
- 缓存加载校验版本下限 0.16.10(对齐 JS),拒绝旧版坐标式缓存
- 执行器新增 Navigate / Reload / GoBack 动作分支(web 走新增的 `WebPage.navigate/reload/go_back`,移动端回落 `launch`/`back`)

**web (Playwright):**

- **popup 处理(forceSameTabNavigation,默认开启,对齐 JS `forceClosePopup`)**:点击 `target=_blank` 链接开新 tab 时,自动关闭新 tab 并在当前 tab 打开其 URL;此前 agent 截图仍是旧 tab,后续动作全部脱靶
- `key_press` 热键归一化(对齐 JS `normalizeKeyInputs`):接受 "ctrl + a" / "meta a" / "Ctrl+A" 等规划器输出并转成 Playwright 认可的组合键;此前直接抛 "Unknown key"
- 默认超时对齐 JS shared/constants:navigation 10s→5s、network idle 10s→2s
- 移除 JS 没有的 `_ensure_in_viewport` 附加行为:模型输出的本就是视口截图坐标,该函数触发时把视口坐标当文档坐标 scrollTo 反而点错;点击/悬停/拖拽现直接使用原始坐标(缓存命中路径已由 0.3.2 的 scrollIntoView 兜底)
- 拖拽节拍对齐 JS(move→200ms→down→300ms→20 步插值→500ms→up→200ms);此前 10 步、无停顿,拖拽排序/HTML5 DnD 类页面成功率低

**报告:**

- `SessionRecorder` 改持有独立的报告生成器实例;此前模块级单例在多线程/多 Agent 下互相覆盖会话状态,且最后一份报告的全部 base64 截图常驻内存
- `finish()` 幂等:重复调用(如手动 finish 后 `async with` 退出再触发)返回上次报告路径;此前每次都生成一份新报告文件
- 保存报告不再构建两次完整 HTML(此前先 generate 后丢弃、save 内部再 generate,大报告内存峰值与 CPU 翻倍)
- 任务时间戳使用步骤真实开始时间 + 耗时;此前全部取"报告生成时刻",timeline 视图所有任务堆叠在同一时间点
- static 资源物化容忍并发写(已存在且大小一致跳过;写失败但文件已存在视为成功),避免多 Agent 并发 save 时 Windows 上 PermissionError

第二轮审查修复:覆盖 core/web 自动化主链路与 HTML 报告生成链路(对照 JS 源的保真度 + 质量审查)。

### Fixed

**core / 缓存互通(与 JS 版缓存互通是硬性要求):**

- **plan 缓存改写为 JS 兼容的 `MidsceneYamlScript` 格式**(`{tasks:[{name, flow:[{aiTap: '', locate: ...}]}]}`,对齐 agent.ts:948-957 + buildYamlFlowFromPlans);此前写入裸列表,JS 读不了。读取侧同时兼容旧版 Python 裸列表格式
- **读到无法解析的缓存(如 JS 写入的)不再把 ai_act 判为失败** —— 回放失败(解析不了/动作失败)一律回退 AI 规划;此前直接 `return False`,命中一条 JS 格式缓存就让任务挂掉
- **缓存文件名与 JS 完全对齐**:非法字符清洗照搬 `replaceIllegalPathCharsAndSpace`(`[:*?"<>|# ]` → `-`);超长名 hash 逐位复刻 `generateHashId`(sha256 hex → a-z 映射取前 5 位);此前同一 cache_id 在两种语言下生成不同文件名,互通等于没有
- **write-only 缓存模式每次 flush 指数级重复记录** —— 已落盘的增量现在会从内存清掉
- locate 缓存命中后先把元素 scrollIntoView 再取 rect/center(对齐 JS `getElementInfoByXpath`);此前元素在视口外时 bounding_box 的视口相对坐标会换算错位、点错元素
- UI-TARS / auto-GLM 跳过 plan 缓存读写(对齐 agent.ts:901-907):它们产出的是截图绝对坐标,不可跨次回放

**core / ai_act 失败路径(消除"假成功"):**

- 超过重规划上限改为抛 RuntimeError;此前返回 True 且把执行到一半的动作序列固化进缓存
- 重规划上限对齐 JS:默认 20、UI-TARS 40、auto-GLM 100,支持 `MIDSCENE_REPLANNING_CYCLE_LIMIT` 环境变量;此前硬编码 10 且无配置出口
- 空动作 + `shouldContinuePlanning=false` 视为正常完成(对齐 JS);此前"有弹窗就关掉"这类条件任务在无弹窗时会多烧 2 次规划后抛错

**web / 滚动与等待:**

- `PlaywrightAgent.ai_wait_for(timeout=30)`(秒)此前按位置参数传给 core 的毫秒参数,实际只等 30ms
- `PlaywrightPage` 新增 `scroll_until_top/bottom/left/right`(mouse.wheel ±9999999 + 起点语义,对齐 base-page.ts:521-539):能滚动指针下方的内部滚动容器,且保留 AI 定位的起始元素;此前 web 的 scrollTo* 走 `window.scrollTo` 只能滚主文档、丢弃定位起点
- 规划执行器的 Scroll 动作:`untilLeft/untilRight` 现路由到 `scroll_until_left/right`(此前被降级为"向下滚一次");locate 到的元素中心作为滚动起点传入(此前完全忽略);未指定距离时用 interface 默认值(web 视口 70%,对齐 JS),此前硬编码 500px
- 滚动前的鼠标定位实现 JS `everMoved` 语义:只有鼠标从未移动过才移到视口中心,hover 某容器后滚动现在滚的是那个容器

**HTML 报告(与打包的 JS 查看器的格式契约):**

- **script 注入转义对齐 JS `escapeScriptTag`**:所有 `<`/`>` → `__midscene_lt__`/`__midscene_gt__`(查看器解析前无条件还原)。此前只替换字面量 `</script>`,dump 中出现 `</Script >` 等变体或 `<` 序列会把整页打碎;且查看器的无条件 unescape 与 Python 的不转义不对称,可能悄悄损坏数据
- **task status 归一化为 finished/failed/pending**:"success (cached)" 等带注记状态此前落入 pending,JS 查看器把这类步骤渲染成"未完成"并注入 "unknown error" 回放帧;缓存来源改经 hitBy 表达
- **hitBy 结构对齐 JS `{from: 'Cache', context: {...}}`**(前端精确匹配大写 'Cache');此前扁平小写结构导致 cache 徽标永不显示
- **subType 用显式映射表替代 capitalize()**:`rightClick→RightClick`、`keyboardPress→KeyboardPress`、`waitFor→WaitFor` 等;此前 "Rightclick"/"Waitfor" 与前端精确匹配不符,丢图标和回放指针动效;hover/rightClick/doubleClick/keyboardPress 等正确归入 Action Space
- Assert/Query 任务的 param 字段名对齐 `extractInsightParam`(`param.assertion`/`param.dataDemand`);此前 Insight 行 subtitle 空白
- 模型名/耗时写入 `task.usage.model_name`/`time_cost`(前端实际读取位置),`modelBriefs` 从步骤实际用到的模型收集;此前报告里模型显示 Unknown

### Chore

- 删除报告生成器中无消费方的顶层字段依赖说明;测试 `_extract_midscene_dump` 同步 unescape;新增全量转义回归测试

本次为 Android / iOS 移植的审查修复版:对照 JS 源做了一轮移植保真度 + 代码质量审查,修掉一批"静默失效"类 bug。

### Fixed

- **core: `ai_scroll` 在 Android/iOS 上多处静默 no-op**
  - `scrollToTop/Bottom/Left/Right` 现直接路由到设备原生 `scroll_until_*`(并把 AI 定位到的元素中心作为手势起点传入);此前经 `evaluate_javascript` 转译,`scrollToLeft/Right` 完全不可达
  - 带 `locate_prompt` 的单次滚动现从元素中心做原生手势:`AndroidDevice.scroll` / `IOSDevice.scroll` 新增 `start_point` 参数(Android 侧移植了 JS `calculateScrollEndPoint` 的边界裁剪 + 50px 最小手势距离);此前走 `document.elementFromPoint().scrollBy()` 脚本,被移动端忽略且报告"成功"
  - Playwright 路径改为直接传 `starting_point`(mouse.wheel 起点),不再注入 JS
- **Android: 自定义 adb 路径完全不生效** —— `MIDSCENE_ADB_PATH` / `android_adb_path` 此前写入无消费者的 `ADB_PATH` 环境变量;现写 adbutils 实际读取的 `ADBUTILS_ADB_PATH`
- **Android: 未装 ADBKeyboard 时非 ASCII 输入静默丢失** —— 广播成功判定此前只要输出含 "Broadcast completed" 即视为成功(`am broadcast` 在无接收者时也输出该字样),永远不会走 `input text` fallback 也不警告;现仅认 `result=-1`。同时改用 ADBKeyboard 官方推荐的 `ADB_INPUT_B64` base64 通道,避免非 ASCII 明文穿越 adb shell 引号转义不可靠
- Android: `always-yadb` / `yadb-for-non-ascii` IME 策略分支输入后此前跳过收键盘;现同样尊重 `auto_dismiss_keyboard`(对齐 JS)
- Android: `hide_keyboard` 对未知 `keyboard_dismiss_strategy` 取值此前按 back-first;现对齐 JS 按默认 esc-first
- Android: 所有 `adb shell` 调用加 60s 默认超时(对齐 appium-adb `adbExecTimeout`);此前设备 offline/卡死会永久挂起协程
- Android: `async with AndroidAgent(...)` 退出时现调用 `device.destroy()` 释放 ADB 连接(与 `IOSAgent` 对齐)
- **iOS: DPR 获取失败改为抛错**(对齐 JS assert);此前静默回退 1.0,在 2x/3x 屏上截图与坐标换算全部错位且无显式失败
- iOS: `launch(url)` 打开 URL 后补上 JS 版默认的 2s 稳定等待,避免紧接着的截图/操作拿到加载中的过渡画面
- iOS: `IOSAgent` 此前无条件覆盖 device 级 `app_name_mapping`,导致 `IOSDeviceOpt(app_name_mapping=...)` 被丢弃;现叠加合并
- iOS: `IOSDevice.clear_input` 返回类型与 Android 统一为 `None`
- Android/iOS Agent: `ai_wait_for(timeout=30, interval=2)`(单位秒)此前按位置参数传给 core 的 `timeout_ms/check_interval_ms`,实际只等 30ms;现走 core 的秒兼容关键字参数
- webdriver: `create_session` 收到非 JSON 响应时现抛可读的 `WebDriverError`,此前是 `AttributeError`

### Chore

- 新增仓库根 `.gitattributes`,把 `pymidscene/resources/report_template/**` 标为 `linguist-vendored`,避免 GitHub "Languages" 统计被巨大的预构建报告模板(从 JS `@midscene/visualizer` 继承的单文件 React bundle)拉偏为以 HTML 为主。
- 删除 `IOSWebDriverClient._normalize_key_name` 死代码;`tests/core/test_agent_scroll_routing.py` 新增 ai_scroll 路由回归测试;Android/iOS 设备测试补充 start_point 手势与 ADBKeyboard fallback 断言

## [0.3.0] - 2026-04-21

### 新增

- **Android 平台支持** (`pymidscene[android]`)
  - 基于 `adbutils` 的 `AndroidDevice`(实现 `AbstractInterface`),无需 Appium
  - `AndroidAgent` 组合式封装,暴露全部 `ai_*` 方法及 Android 专属 `back / home / recent_apps / launch / run_adb_shell / pull_down / pull_up / long_press / drag_and_drop / key_press`
  - 非 ASCII 文本走 ADBKeyboard(IME 策略 `adb-keyboard / always-yadb / yadb-for-non-ascii`,通过 `MIDSCENE_ANDROID_IME_STRATEGY` 或 `AndroidDeviceOpt.ime_strategy` 配置)
  - 169 条中文/英文应用名 → package 映射(`DEFAULT_APP_NAME_MAPPING`),支持 `launch("小红书")` 自动解析为 `com.xingin.xhs`
  - 新增环境变量 `MIDSCENE_ADB_PATH / MIDSCENE_ADB_REMOTE_HOST / MIDSCENE_ADB_REMOTE_PORT / MIDSCENE_ANDROID_IME_STRATEGY`
  - 示例:`examples/android_basic.py`;文档:`pymidscene/android/README.md`

- **iOS 平台支持**(默认安装,复用已有的 `httpx` 依赖,不新增第三方包)
  - 通用 W3C WebDriver HTTP 客户端 `pymidscene.webdriver.WebDriverClient`(基于 `httpx`)
  - `IOSWebDriverClient` + `IOSDevice`:覆盖 tap / doubleTap / tripleTap / longPress、swipe(W3C Actions)、scroll / scroll_until_top/bottom/left/right(截图相似度判断边界)、W3C keys 文本输入(ASCII + Unicode)、dismiss_keyboard、launch_app / activate_app / terminate_app、open_url(含 Safari fallback)、home / app_switcher
  - `IOSAgent` 组合式封装,同样暴露 `ai_*` 及 iOS 专属方法
  - 183 条中文/英文应用名 → bundle id 映射,支持 `launch("微信")` 自动解析为 `com.tencent.xin`
  - 新增环境变量 `MIDSCENE_WDA_HOST / MIDSCENE_WDA_PORT / MIDSCENE_WDA_BASE_URL / MIDSCENE_WDA_TIMEOUT`
  - 示例:`examples/ios_basic.py`;文档:`pymidscene/ios/README.md`
  - 注:不提供 JS 版 `WDAManager` 的自动 `xcodebuild` 启动能力,用户需自行用 Xcode / tidevice / 模拟器启动 WebDriverAgent

### 修复

- **移动端报告点击回放动画飞离左上角**
  - 原因:`record_screenshot_before/after` 存储的截图空间不一致 —— AI 路径的 before 截图经 `_capture_ai_screenshot` 归一化到 CSS 尺寸,但 after 截图和非 AI 路径的 before 截图直接保留物理像素;单步报告里 before(CSS)+ after(物理)+ element.center(CSS)混用,click replay 的 zoom-out 阶段 transform-origin 算错 → 图片飞向左上
  - 修复:新增 `Agent._capture_recording_screenshot()`,把所有写入报告 recorder 的截图统一归一化到 CSS 空间,覆盖全部 10 处 `record_screenshot_before/after` 调用点
  - 影响:Web(dpr=1)无行为变化;Android / iOS(dpr=2/3)动画回落平滑,不再飞离

### 其他

- `README.md` / `README_CN.md`:加入 Android / iOS 特性说明,中文版增加 QQ 交流群 `2156022195`
- `tests/android/`(FakeAdbDevice)、`tests/ios/`(httpx.MockTransport)完全离线可跑,无需真实设备或 WDA
- `tests/core/`:补充 `test_playwright_wrapper_parity / test_prompt_modules / test_qwen_model / test_service_caller`
- `examples/basic_usage.py`:改用 `channel='chrome'` 启动,免除 `playwright install chromium` 的前置步骤
- `tests/test_doubao.py`:重写部分 `pytest.raises` 用法,贴近 tests/core 风格

## [0.2.0] - 2026-04-17

### 概述

对照 `midscene-main/` 做了一次完整的行级代码审查(`docs/CODE_REVIEW_2026-04-17.md`),本版本落地审查中发现的 22 项问题,覆盖核心正确性、模型家族完整支持、可视化报告完整度,以及测试骨架修复。详细分波记录见 `docs/FIX_PROGRESS_2026-04-17.md`。

### ⚠️ 破坏性变更(Breaking)

1. **`ai_wait_for` 签名变更**
   - 旧: `ai_wait_for(assertion, timeout=30, interval=2)`(秒)
   - 新: `ai_wait_for(assertion, timeout_ms=15000, check_interval_ms=3000)`(毫秒,与 JS `aiWaitFor` 对齐)
   - 兼容:旧 `timeout=` / `interval=`(秒)作为 kwarg 仍可用,但默认值更短
   - 异常处理收紧:只有**断言为假**才重试,**网络/模型错误直接透传**(之前会被吞成超时)

2. **`ai_assert` 返回形态**
   - 新增 `keep_raw_response=True`,此时不抛 `AssertionError`,返回 `{pass, thought, message}`(与 JS `opt.keepRawResponse` 对齐)
   - 默认行为(`False`)保持不变,失败时仍抛 `AssertionError`

3. **`ai_act` 空计划不再静默成功**
   - 连续两次返回空 action 现在抛 `RuntimeError`(对齐 JS `TaskExecutionError`);之前会返回 `True`

4. **截图 MIME 从 PNG 改为 JPEG**
   - `WebPage.screenshot()` 现在返回 JPEG q=90 的 base64(与 JS `base-page.ts` 对齐)
   - 请求体 `data:image/...;base64,` 前缀同步改为 `image/jpeg`
   - 体积降 3-5×,AI image-token 成本相应下降

5. **`calculate_hash` 输出长度变化**
   - MD5(32 字符)→ SHA-256(64 字符),与 JS `generateHashId` 跨语言对齐

6. **`MODEL_FAMILY_VALUES` 枚举修正**
   - 移除不合法的 `"openai"`
   - 新增 `"glm-v" / "auto-glm" / "auto-glm-multilingual" / "gpt-5"`,与 JS `types.ts:289` 对齐

### 重大变更(Non-breaking)

#### 视觉模型家族全量支持
- **UI-TARS**(`vlm-ui-tars / -doubao / -doubao-1.5`):新增完整解析器 `core/ai_model/ui_tars_planning.py` + 专用 prompt,支持 `Thought:/Action:` 文本语法与 `<bbox>x1 y1 x2 y2</bbox>` → 中心点转换,`[EOS]` 清洗,`Reflection:` 段剥离,9 种动作(click/left_double/right_single/drag/type/hotkey/scroll/wait/finished)
- **auto-glm / auto-glm-multilingual**:新增独立子包 `core/ai_model/auto_glm/`,含 prompt(中英双版本)、parser(`<think>/<answer>` XML)、actions(0-999 归一化 → CSS 像素,Swipe→Scroll 轴分类)、planning 入口
- **Claude 原生 Anthropic 协议**:新增 `_call_with_anthropic_sdk`,OpenAI messages 自动转 Anthropic content blocks,system role 提升到顶层字段;`anthropic` 为 optional 依赖
- **qwen3-vl**:修复坐标家族路由,不再被当作 qwen2.5-vl 处理(之前点击坐标错乱)
- **deepThink 参数体系**:按家族映射到 `extra_body.config.enable_thinking`(qwen3-vl) / `extra_body.thinking.type`(doubao/glm-v) / `reasoning.effort`(gpt-5),支持 `MIDSCENE_FORCE_DEEP_THINK` 全局开关

#### Agent 公开方法大幅扩展
新增 9 个与 JS 对齐的 API:
- `ai_tap` / `ai_hover` / `ai_right_click` / `ai_double_click` / `ai_keyboard_press`
- `ai_boolean` / `ai_number` / `ai_string`(基于 `ai_query` 的类型化问答)
- `ai_ask`(自由问答,返回原始字符串)

#### 可视化报告完整度
- 新增字段透传:`screenshot_marked`(bbox 标注截图)、`ai_prompt_tokens / ai_completion_tokens`(token 细分)、`ai_model`(模型名)、`ai_response`(原始响应最多 2000 字符)
- 新增 `hit_by` 标记 —— cache 命中的步骤在报告里可被渲染为 "cached" 徽标
- 新增 `subtask 树` —— `ai_act / ai_click / ai_input` 下的 Planning / Locate / Tap 作为子任务挂在一个父 execution 下,报告左侧显示树结构而非平铺
- `core/types.py:ExecutionDump._task_to_dict / from_dict` 字段补全,支持 `.web-dump.json` 与 JS visualizer round-trip

#### HiDPI 屏幕坐标正确性(C4)
- `WebPage.get_size()` 现在返回真实 `devicePixelRatio`
- `Agent._capture_ai_screenshot()`:发给 AI 之前把截图压回 CSS 尺寸(对齐 JS `agent.ts:447-467` 的 `resizeImgBase64` 逻辑),消除 Retina / 200% 缩放下的系统性点击偏移

#### Cache YAML 与 JS 互通
- `midsceneVersion` 写入 `0.17.0`(满足 JS 最低支持线 `0.16.10`)
- 文件名 hash 从 MD5 切 SHA-256 前 8 位(对齐 JS `generateHashId`)
- 支持 `MIDSCENE_RUN_DIR` / `MIDSCENE_CACHE_MAX_FILENAME_LENGTH` 环境变量
- 加载时自动迁移 JS 旧版顶层 `xpaths` 字段 → `cache.xpaths`
- write-only 模式:flush 前先读回旧记录再 merge(对齐 JS `updateOrAppendCacheRecord`),不再覆盖丢失旧数据

#### Playwright 动作层修正
- macOS 上 `clearInput` 使用 `Meta+a` 而非 `Ctrl+a`(避免只删单字符的 bug)
- `keyboard.type(delay=80)`,对齐 JS,避免受控输入框丢字
- `click / hover / input_text` 去除"`elementFromPoint` → `scrollIntoView` → 重取中心"逻辑,保留纯视口兜底 —— agent 层已经预先 scrollIntoView,此处再做会命中覆盖层 wrapper 导致误点
- 新增 `double_click / right_click / drag_and_drop` 方法
- 新增 `get_element_xpaths()` 多候选(id / `data-testid` / 文本内容 / tag-index),提升 DOM 漂移后的 cache 命中率

### 新增

- 3 个新 prompt 模块:`describe.py`(元素描述,用于 cache 命名)、`section_locator.py`(大页面二段定位)、`order_sensitive_judge.py`(序数描述识别,含 `heuristic_is_order_sensitive` 本地启发)
- `ai_locate` 对"第 3 行 / the third / 最后一个"等序数描述自动跳过缓存,防止 DOM 重排后错点
- `service_caller`:SOCKS 代理支持(via `httpx-socks` optional dep);流式 `CodeGenerationChunk` 最终帧 `isComplete + usage`(provider 未给 usage 时按 `len(content)/4` 估算)
- `_call_with_httpx` 新增传输层异常重试(`ConnectError / ReadTimeout / ReadError / RemoteProtocolError`)
- `ai_input(mode=...)`:支持 `replace`(默认) / `clear` / `append` / `typeOnly`
- `ai_query` 现在进入 SessionRecorder,前后截图与提取结果都能在报告里看到
- 新增环境变量常量(不再静默忽略):`MIDSCENE_MODEL_MAX_TOKENS / OPENAI_MAX_TOKENS / MIDSCENE_RUN_DIR / MIDSCENE_REPORT_TAG_NAME / MIDSCENE_REPLANNING_CYCLE_LIMIT / MIDSCENE_CACHE / MIDSCENE_CACHE_MAX_FILENAME_LENGTH / MIDSCENE_FORCE_DEEP_THINK / MIDSCENE_LANGSMITH_DEBUG / MIDSCENE_LANGFUSE_DEBUG / MIDSCENE_PREFERRED_LANGUAGE / MIDSCENE_DEBUG_MODE`
- AutoGLM 自动注入 `top_p=0.85 / frequency_penalty=0.2`(对齐 JS)

### 修复

- `ai_act` 把动作 append 到 `conversation_history` / 缓存的时机从"执行前"改为"执行成功后" —— 失败动作不再毒化下一轮 replan 上下文,也不会被固化到 cache.yaml
- `ai_act` 缓存命中路径现在会把每个回放动作写进 session_recorder(对齐 JS `loadYamlFlowAsPlanning`),之前 cached 运行在报告里完全看不见
- `preprocess_doubao_bbox_json` 正则从 O(n²) 改为单次 `re.sub`(lookahead/lookbehind)
- `test_cache.py::test_write_only_mode`:实现端修复,flush 前 merge 磁盘旧记录

### 文档

- `docs/CODE_REVIEW_2026-04-17.md`:初始行级审查,列出 10 项 Critical + 15+ High
- `docs/FIX_PROGRESS_2026-04-17.md`:完整 4 波修复记录,含模型家族矩阵、字段透传前后对比、per-item 文件引用

### 可选依赖

- `anthropic` — Claude 原生协议所需,通过 `pip install anthropic` 启用
- `httpx-socks` — SOCKS 代理所需,通过 `pip install httpx-socks` 启用

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
