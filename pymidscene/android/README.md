# pymidscene.android

**Android 自动化支持** — Midscene.js 的 Python 移植版 `pymidscene` 面向 Android 设备的分支。基于 `adbutils` 通过 ADB 直连设备，复用 Web 端同一套 AI 驱动能力。

## 安装

```bash
pip install "pymidscene[android]"
# 首次使用前确认 adb 可用
adb devices
```

需要 `adb` 可执行文件在 `PATH` 中，或通过 `MIDSCENE_ADB_PATH` 指定。

## 快速上手

```python
import asyncio
from pymidscene.android import agent_from_adb_device

async def main():
    agent = await agent_from_adb_device()   # 自动选第一个在线设备
    await agent.launch("小红书")
    await agent.ai_tap("搜索框")
    await agent.ai_input("搜索框", "Python")
    print(await agent.ai_query({"titles": "前 5 条笔记标题"}))
    agent.finish()

asyncio.run(main())
```

## 已实现能力

| 能力 | JS 对应 | Python 对应 |
|---|---|---|
| ADB 连接/断开 | `appium-adb` | `adbutils` |
| 截图 | `screenshotBase64` | `AndroidDevice.screenshot` |
| 屏幕尺寸/方向/密度 | `size` + `getScreenSize` | `AndroidDevice.get_size` |
| 点击 / 双击 / 长按 | `mouseClick` / `mouseDoubleClick` / `longPress` | `click` / `double_click` / `long_press` |
| 滑动 / 滚动 | `scroll*` | `scroll` / `scroll_until_*` |
| 下拉刷新 / 上拉 | `pullDown` / `pullUp` | `pull_down` / `pull_up` |
| 拖拽 | `mouseDrag` | `mouse_drag` / `drag_and_drop` |
| 键盘输入 (ASCII) | `input text` | `_type_via_input_text` |
| 键盘输入 (非 ASCII) | yadb | ADBKeyboard 广播 |
| 清空输入框 | `clearInput` | `clear_input` |
| 键码 | `keyboardPress` | `key_press` |
| 隐藏软键盘 | `hideKeyboard` | `hide_keyboard` |
| 返回 / Home / 最近 | `back / home / recentApps` | `back / home / recent_apps` |
| 启动应用或 URL | `launch` | `launch` (URL / package/activity / 中文名) |
| 运行 ADB 命令 | `RunAdbShell` | `run_adb_shell` |
| App 名 → 包名映射 | `defaultAppNameMapping` | `DEFAULT_APP_NAME_MAPPING` (169 条) |
| `evaluate_javascript` 兼容 | — | 识别 `window.scrollTo(0,0)` / `scrollHeight` / `history.back()` 后本地化 |

## 中文/非 ASCII 输入

Android 系统的 `input text` 命令无法可靠输入非 ASCII。本实现默认走 **ADBKeyboard** 策略：

1. 在设备上安装 [ADBKeyboard.apk](https://github.com/senzhk/ADBKeyBoard/raw/master/ADBKeyboard.apk)
2. 启用并设为默认输入法：

   ```bash
   adb shell ime enable com.android.adbkeyboard/.AdbIME
   adb shell ime set com.android.adbkeyboard/.AdbIME
   ```

3. 代码里非 ASCII 文本会通过 `am broadcast -a ADB_INPUT_TEXT` 广播送入。

策略可通过 `MIDSCENE_ANDROID_IME_STRATEGY` 或 `AndroidDeviceOpt.ime_strategy` 覆盖：

| 值 | 行为 |
|---|---|
| `adb-keyboard` (默认) | ASCII 用 `input text`, 非 ASCII 走 ADBKeyboard |
| `yadb-for-non-ascii` | 保留 JS 命名。当前未移植 yadb，退化为 ADBKeyboard |
| `always-yadb` | 同上 |

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `MIDSCENE_ADB_PATH` | — | `adb` 可执行文件路径 |
| `MIDSCENE_ADB_REMOTE_HOST` | — | 远程 adb server host |
| `MIDSCENE_ADB_REMOTE_PORT` | `5037` | 远程 adb server port |
| `MIDSCENE_ANDROID_IME_STRATEGY` | `adb-keyboard` | 输入法策略 |

## 尚未移植

- yadb（Java payload 推送至 `/data/local/tmp`）— 目前退化为 ADBKeyboard
- `forceScreenshot`（利用 yadb 绕过截图禁令）
- 多 display 的完整处理（`displayId` / `getPhysicalDisplayId` 只在少量路径做了适配）
- Android MCP server（JS 侧 `mcp-server.ts`, `mcp-tools.ts`）

欢迎通过 PR 贡献。

## 贡献

- JS 参考：https://github.com/web-infra-dev/midscene/tree/main/packages/android
- 对应 Python 入口：`pymidscene/android/`
- 运行测试：`pytest tests/android/ -v`

所有测试基于 mock 的 `FakeAdbDevice`，不需要真机。
