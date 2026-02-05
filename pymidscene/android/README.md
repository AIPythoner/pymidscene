# Android Support (Placeholder)

本目录为 Android 自动化支持预留。

## 当前状态

🚧 **规划中** - Android 支持将在 WebDriver 完成后实现

当前 PyMidscene 已完整实现:
- ✅ Playwright 集成 (Web 平台)
- ✅ Qwen VL 和 Doubao Vision 模型支持
- ✅ 智能缓存系统
- ✅ 执行记录和报告

## 未来扩展计划

PyMidscene 将支持 Android 平台的 AI 自动化，通过 ADB 或 Appium 实现。

### 计划支持的功能

- ✅ ADB 连接和控制
- ✅ Appium 集成
- ✅ Android UI 元素定位
- ✅ 截图和坐标转换
- ✅ 手势操作（点击、滑动、长按等）

### 技术方案

**方案一：基于 ADB**
- 使用 `adb` 命令行工具
- 直接控制 Android 设备

**方案二：基于 Appium**
- 使用 `appium-python-client`
- 支持更高级的自动化功能

### 使用示例（未来）

```python
from pymidscene import Agent
from pymidscene.android import AndroidPage

# 连接 Android 设备
android_page = AndroidPage(device_id="emulator-5554")

# 创建 Agent（支持多种模型）
agent = Agent(android_page, model="qwen-vl-max")  # 或 "doubao-vision"

# 执行自动化
agent.ai_act("打开设置应用")
agent.ai_act("找到并点击 Wi-Fi 设置")
```

## 实现指南

如果您想贡献 Android 支持，请参考以下资源：

1. **参考实现**: `pymidscene/web_integration/playwright/`
2. **抽象接口**: `pymidscene/web_integration/base.py` 中的 `AbstractInterface`
3. **JS 版本**: [Midscene android package](https://github.com/web-infra-dev/midscene/tree/main/packages/android)
4. **推荐库**: `appium-python-client` 或 `pure-python-adb`

### 需要实现的核心方法

```python
class AndroidPage(AbstractInterface):
    def screenshot(self) -> str:
        """返回 Base64 编码的截图"""
        pass

    def get_size(self) -> Size:
        """获取屏幕尺寸"""
        pass

    def click(self, x: float, y: float):
        """点击指定坐标"""
        pass

    def swipe(self, start_x: float, start_y: float, end_x: float, end_y: float):
        """滑动手势"""
        pass

    def long_press(self, x: float, y: float, duration: float):
        """长按操作"""
        pass
```

### 技术挑战

- 🔍 Android UI 树解析（XML hierarchy）
- 📱 设备连接和管理
- 🎯 坐标系转换（考虑屏幕密度）
- ⚡ 性能优化（减少 ADB 通信延迟）

## 贡献

欢迎提交 Pull Request！对于移动平台支持，建议先在 Issue 中讨论技术方案。
