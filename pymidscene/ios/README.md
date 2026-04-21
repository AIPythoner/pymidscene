# pymidscene.ios

**iOS 自动化支持** — 通过 WebDriverAgent (WDA) 的 HTTP API 控制 iOS 设备 / 模拟器，复用 Web 端同一套 AI 驱动能力。

## 安装

`pymidscene` 默认已包含 iOS 模块（只依赖 `httpx`, 它是基础依赖），无需额外安装。

## 前置条件

本库**不负责启动 WebDriverAgent**。使用前需要自行在目标设备上启动 WDA，以下任选其一：

| 场景 | 启动方式 |
|---|---|
| iOS 真机 (macOS) | Xcode 打开 WebDriverAgent.xcodeproj → Product → Test (WebDriverAgentRunner) |
| iOS 真机 (跨平台) | `pip install tidevice` + `tidevice xctest -B com.facebook.WebDriverAgentRunner.xctrunner` |
| iOS 模拟器 | Xcode Test 运行一次, 或 `xcodebuild test -project WebDriverAgent.xcodeproj ...` |
| 远程设备 | 在远端启动 WDA, 然后 SSH port-forward 8100 到本地 |

验证 WDA 可达:

```bash
curl http://localhost:8100/status
```

## 快速上手

```python
import asyncio
from pymidscene.ios import agent_from_webdriver_agent, check_ios_environment

async def main():
    env = await check_ios_environment()
    assert env["available"], env["error"]

    async with await agent_from_webdriver_agent() as agent:
        await agent.launch("微信")          # 中文名 → com.tencent.xin
        await agent.ai_tap("扫一扫")
        await agent.ai_query({"text": "页面标题"})
        await agent.home()

asyncio.run(main())
```

## 已实现能力

| 能力 | JS 对应 | Python 对应 |
|---|---|---|
| WDA HTTP 基础协议 | `@midscene/webdriver` | `pymidscene.webdriver.WebDriverClient` |
| iOS WDA 客户端 | `ios-webdriver-client.ts` | `pymidscene.ios.IOSWebDriverClient` |
| Session / Capabilities | `createSession` | `create_session` (默认注入 XCUITest) |
| 截图 | `screenshotBase64` | `IOSDevice.screenshot` |
| 窗口尺寸 / DPR | `size` + `/wda/screen` | `IOSDevice.get_size` |
| 点击 / 双击 / 三连击 / 长按 | `tap / doubleTap / tripleTap / longPress` | `click / double_click / long_press` + WDA client |
| 滑动 | W3C Actions `/actions` | `IOSDevice.swipe` (同 W3C) |
| 滚动 | `scroll*` | `scroll / scroll_until_top/bottom/left/right` |
| Drag & Drop | `swipe` | `drag_and_drop` |
| 文本输入 (ASCII + Unicode) | `/wda/keys` | `IOSDevice.input_text` / `type_text` |
| 单键 (Enter / 方向键 / Tab) | `pressKey` | `key_press` |
| 清空当前输入 | `clearActiveElement` | `IOSDevice.clear_input` |
| 关闭软键盘 | `dismissKeyboard` | `hide_keyboard` (含上滑 fallback) |
| App 生命周期 | `launchApp / activateApp / terminateApp` | `launch / activate_app / terminate_app` |
| 打开 URL (带 Safari 兜底) | `openUrl` | 内部实现已含 Safari fallback |
| Home / App Switcher | `pressHomeButton / appSwitcher` | `home / app_switcher` |
| 直通 WDA 请求 | `runWdaRequest` | `run_wda_request` |
| App 名 → Bundle ID | 183 条映射 | `DEFAULT_APP_NAME_MAPPING` |
| `evaluate_javascript` 兼容 | — | 识别 `scrollTo(0,0)` / `scrollHeight` / `history.back` 后本地化 |

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `MIDSCENE_WDA_HOST` | `localhost` | WDA host |
| `MIDSCENE_WDA_PORT` | `8100` | WDA port |
| `MIDSCENE_WDA_BASE_URL` | — | 直接指定完整 URL, 覆盖 host+port |
| `MIDSCENE_WDA_TIMEOUT` | `30` | HTTP 请求超时 (秒) |

## 架构

```
pymidscene/
├── webdriver/client.py       # 通用 W3C WebDriver HTTP 客户端 (httpx)
└── ios/
    ├── webdriver_client.py   # iOS 专属 WDA 端点
    ├── device.py             # IOSDevice(AbstractInterface)
    ├── agent.py              # IOSAgent (组合 core Agent)
    ├── app_name_mapping.py   # 183 条中文名 → bundle id
    └── utils.py              # check_ios_environment / agent_from_webdriver_agent
```

JS 版的 `@midscene/webdriver` `WDAManager`(用 `xcodebuild` 启动 WDA 的那部分)在 Python 版**不提供** — 启动 WDA 本身超出 Python 端的职责范围, 不同用户用 tidevice / Xcode / 模拟器的方式各异, 强行打包会引入 macOS 限制。

## 尚未移植

- `WDAManager` (自动 `xcodebuild` 启 WDA)
- iOS Playground 与 MCP server
- Safari URL 兜底方案里的 UI 自动化细节 (目前只做了"重启 Safari → POST /url" 的简化版)

## 与 Android 的选择

| 场景 | 推荐 |
|---|---|
| 国内安卓机 (含鸿蒙兼容) | `pymidscene[android]` — ADB 直连 |
| iOS 真机 / 模拟器 | `pymidscene.ios` — 需要 WDA |
| 跨 iOS + Android 对同一动作 | 两者都初始化, 通过 AI 指令保持一致 |

## 运行测试

```bash
pytest tests/ios/ -v
```

全部测试基于 `httpx.MockTransport` mock, 不需要真实 WDA 或 iOS 设备。

## 贡献

欢迎提 PR。WDA Manager 自动化启动、完整的 `clearActiveElement` 回退策略、或 iOS 15+ 的最新 WDA 端点兼容都是好方向。
