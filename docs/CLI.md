# pymidscene CLI

用自然语言 YAML 脚本驱动 web / Android / iOS 自动化。对齐 Midscene.js 的
`@midscene/cli`(YAML 脚本与 flow 执行契约)。

## 安装与入口

CLI 随包安装,提供 `pymidscene` 命令(等价 `python -m pymidscene.cli`):

```bash
pymidscene ./script.yaml                 # 跑单个脚本
pymidscene ./scripts/                     # 跑目录下所有 *.yaml
pymidscene --files a.yaml b.yaml          # 显式多文件
pymidscene --config ./suite.yaml          # 索引 yaml 的 files: 列表
```

模型通过环境变量配置(`MIDSCENE_MODEL_NAME` / `MIDSCENE_MODEL_API_KEY` /
`MIDSCENE_MODEL_BASE_URL` / `MIDSCENE_MODEL_FAMILY`)。当前工作目录下若有 `.env`,
启动时会自动加载。

## 命令行选项

| 选项 | 说明 | 默认 |
| --- | --- | --- |
| `<path>` | 文件 / 目录 / glob | — |
| `--files a.yaml b.yaml` | 显式文件/ glob 列表 | — |
| `--config suite.yaml` | 索引 yaml(含 `files:` 数组) | — |
| `--concurrent N` | 并发文件数 | 1 |
| `--continue-on-error` | 出错继续跑其余文件 | false |
| `--headed` | 浏览器有头模式 | false |
| `--keep-window` | 跑完不关浏览器(强制有头) | false |
| `--share-browser-context` | 多个 web 文件共用一个浏览器会话/cookie | false |
| `--summary name.json` | 汇总索引文件名 | `summary-<ts>.json` |
| `--dotenv-override` / `--dotenv-debug` | 控制 `.env` 加载 | false |
| `--web.* / --android.* / --ios.*` | 目标环境覆盖,如 `--web.viewportWidth 1920` | — |

退出码:全部成功为 `0`,任一失败 / 部分失败 / 未执行为 `1`。

## YAML 脚本结构

顶层恰好一个平台块(`web` / `android` / `ios` / `interface`,`target` 是 `web`
的废弃别名),加可选 `config` / `agent`,再加 `tasks`:

```yaml
web:
  url: https://example.com
  viewportWidth: 1280
  output: ./result.json        # 不写则落到 midscene_run/output/

tasks:
  - name: do something
    continueOnError: false
    flow:
      - aiTap: the login button
      - aiInput: the username field
        value: alice
      - aiKeyboardPress: Enter
      - aiWaitFor: the dashboard is visible
        timeout: 15000          # 毫秒
      - aiQuery: "{ count: number }"
        name: stats             # 结果按 name 存入 output JSON
      - aiAssert: the page shows the dashboard
```

支持 `${VAR}` 环境变量插值(注释行除外)。

### flow 步骤一览

- 交互:`aiTap` `aiHover` `aiRightClick` `aiDoubleClick` `aiClearInput`
  `aiInput`(`value` + 可选 `mode: replace|append|clear`)、`aiKeyboardPress`
  (`keyName` + 可选 `locate` 先聚焦)、`aiScroll`(`direction`/`distance`/`scrollType`)
- 自主任务:`ai` / `aiAction`(plan-execute-replan 循环)
- 提取/断言:`aiQuery` `aiNumber` `aiString` `aiBoolean` `aiAsk` `aiLocate`
  `aiAssert`、`aiWaitFor`(毫秒超时)
- 其它:`sleep`(毫秒)、`javascript`(web)、`aiDragAndDrop` `LongPress` `Swipe`
  (用 `ai_locate` 把定位描述桥接成坐标)、`launch` `runAdbShell`(Android)
  `runWdaRequest`(iOS)

有返回值的步骤(`aiQuery` 族、`aiAssert`、`javascript` 等)按 `name` 写入
`--output` JSON;没写 `name` 则用自增整数下标。

## 与 Midscene.js 的有意差异

- `--web.* / --android.*` 覆盖只在脚本声明了同类目标(或无目标)时叠加,不会
  给一个 Android 脚本平白塞 web 块。
- 批量里某个 yaml 解析失败时记为该文件 `failed` 并继续其余文件(退出码仍 1),
  而非整批中止。
- `--files` 匹配 0 个文件时退出码 1(fail-loud)。
- summary 的 `generatedAt` 用确定性的 ISO-8601。
- `serve`(本地静态服务器)与 `bridgeMode`(Chrome 扩展桥)暂不支持。
