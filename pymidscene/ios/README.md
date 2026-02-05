# iOS Support (Placeholder)

本目录为 iOS 自动化支持预留。

## 当前状态

🚧 **规划中** - iOS 支持将在 Android 支持完成后实现

当前 PyMidscene 已完整实现:
- ✅ Playwright 集成 (Web 平台)
- ✅ Qwen VL 和 Doubao Vision 模型支持
- ✅ 智能缓存系统
- ✅ 执行记录和报告

## 未来扩展计划

PyMidscene 将支持 iOS 平台的 AI 自动化，通过 XCUITest 或 Appium 实现。

### 计划支持的功能

- ✅ XCUITest 集成
- ✅ Appium 支持
- ✅ iOS UI 元素定位
- ✅ 截图和坐标转换
- ✅ 手势操作（点击、滑动、长按等）
- ✅ 模拟器和真机支持

### 技术方案

**方案一：基于 XCUITest**
- 使用 `xcrun simctl` 控制模拟器
- 通过 WebDriverAgent 连接真机

**方案二：基于 Appium**
- 使用 `appium-python-client`
- 统一的 iOS/Android 自动化接口

### 使用示例（未来）

```python
from pymidscene import Agent
from pymidscene.ios import IOSPage

# 连接 iOS 设备
ios_page = IOSPage(device_id="iPhone-14-Pro")

# 创建 Agent（支持多种模型）
agent = Agent(ios_page, model="qwen-vl-max")  # 或 "doubao-vision", "vlm-ui-tars-doubao-1.5"

# 执行自动化
agent.ai_act("打开设置应用")
agent.ai_act("找到并点击通用设置")
```

## 实现指南

如果您想贡献 iOS 支持，请参考以下资源：

1. **参考实现**: `pymidscene/web_integration/playwright/`
2. **抽象接口**: `pymidscene/web_integration/base.py` 中的 `AbstractInterface`
3. **JS 版本**: [Midscene ios package](https://github.com/web-infra-dev/midscene/tree/main/packages/ios)
4. **推荐库**: `appium-python-client` 或 `wda` (WebDriverAgent Python client)

### 需要实现的核心方法

```python
class IOSPage(AbstractInterface):
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

- 🔍 iOS UI 树解析（XCUITest accessibility tree）
- 📱 设备连接（模拟器 vs 真机）
- 🎯 坐标系转换（考虑 Retina 显示屏）
- 🔐 代码签名和证书管理
- ⚡ WebDriverAgent 部署和维护

### 开发环境要求

- macOS 系统（用于 XCUITest）
- Xcode 和命令行工具
- iOS 设备或模拟器

## 贡献

欢迎提交 Pull Request！对于 iOS 支持，建议:
1. 先在 Issue 中讨论技术方案
2. 确保有 macOS 开发环境
3. 提供模拟器和真机测试结果
