"""
端到端集成测试

测试完整的 Agent 工作流程，包括：
- Agent 初始化
- AI 元素定位
- 点击和输入操作
- 数据提取
- 断言验证
- 缓存系统
- 执行记录
"""

import pytest
import asyncio
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from pymidscene.core.agent.agent import Agent
from pymidscene.web_integration.base import AbstractInterface
from pymidscene.shared.types import Size, Rect, LocateResultElement
from pymidscene.core.types import UIContext, ScreenshotItem


class MockInterface(AbstractInterface):
    """模拟的设备接口，用于测试"""

    def __init__(self):
        self.screenshot_base64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        self.size = Size(width=1280, height=720, dpr=1.0)
        self.clicked_positions = []
        self.input_texts = []

    async def get_ui_context(self) -> UIContext:
        """获取 UI 上下文"""
        screenshot = ScreenshotItem(self.screenshot_base64)
        return UIContext(
            screenshot=screenshot,
            size=self.size,
            _is_frozen=False
        )

    async def screenshot(self, full_page: bool = False) -> str:
        """获取截图"""
        return self.screenshot_base64

    async def get_size(self) -> Size:
        """获取页面尺寸"""
        return self.size

    async def click(self, x: float, y: float) -> None:
        """点击坐标"""
        self.clicked_positions.append((x, y))

    async def input_text(
        self,
        text: str,
        x: float = None,
        y: float = None
    ) -> None:
        """输入文本"""
        if x is not None and y is not None:
            await self.click(x, y)
        self.input_texts.append(text)

    async def hover(self, x: float, y: float) -> None:
        """悬停"""
        pass

    async def scroll(self, x: float, y: float) -> None:
        """滚动"""
        pass

    async def key_press(self, key: str) -> None:
        """按键"""
        pass

    async def wait_for_navigation(self, timeout: int = 30000) -> None:
        """等待导航"""
        pass

    async def wait_for_network_idle(self, timeout: int = 10000) -> None:
        """等待网络空闲"""
        pass


@pytest.fixture
def mock_interface():
    """创建模拟接口"""
    return MockInterface()


@pytest.fixture
def temp_cache_dir():
    """创建临时缓存目录"""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir)


@pytest.fixture
def mock_ai_response():
    """模拟 AI 响应"""
    def _mock_response(response_type="locate"):
        if response_type == "locate":
            return {
                "content": '{"bbox": [100, 200, 300, 250]}',
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 50,
                    "total_tokens": 1050
                }
            }
        elif response_type == "extract":
            return {
                "content": '<thought>提取数据中</thought><data-json>{"title": "测试标题", "count": 42}</data-json>',
                "usage": {
                    "prompt_tokens": 1200,
                    "completion_tokens": 80,
                    "total_tokens": 1280
                }
            }
        elif response_type == "assert":
            return {
                "content": '{"pass": true, "thought": "验证通过"}',
                "usage": {
                    "prompt_tokens": 800,
                    "completion_tokens": 30,
                    "total_tokens": 830
                }
            }
    return _mock_response


class TestAgentInitialization:
    """测试 Agent 初始化"""

    def test_agent_basic_initialization(self, mock_interface):
        """测试基本初始化"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key',
            'MIDSCENE_QWEN_BASE_URL': 'https://test.api.com'
        }):
            agent = Agent(
                interface=mock_interface,
                model="qwen-vl-max"
            )

            assert agent.interface == mock_interface
            assert agent.model_name == "qwen-vl-max"
            assert agent.task_cache is None
            assert agent.recorder is None

    def test_agent_with_cache(self, mock_interface, temp_cache_dir):
        """测试启用缓存的初始化"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(
                interface=mock_interface,
                model="qwen-vl-max",
                cache_id="test_cache",
                cache_dir=temp_cache_dir
            )

            assert agent.task_cache is not None
            assert agent.task_cache.cache_id == "test_cache"

    def test_agent_with_recording(self, mock_interface):
        """测试启用执行记录的初始化"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(
                interface=mock_interface,
                model="qwen-vl-max",
                enable_recording=True
            )

            assert agent.recorder is not None
            assert agent.enable_recording is True


class TestAILocate:
    """测试 AI 元素定位"""

    @pytest.mark.asyncio
    async def test_ai_locate_success(self, mock_interface, mock_ai_response):
        """测试成功定位元素"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(interface=mock_interface, model="qwen-vl-max")

            # Mock AI 调用
            with patch.object(agent.model, 'call', return_value=mock_ai_response("locate")):
                element = await agent.ai_locate("搜索框")

                assert element is not None
                assert isinstance(element, LocateResultElement)
                assert element.description == "搜索框"
                assert element.center == (200.0, 225.0)  # 中心点计算
                assert element.rect['left'] == 100
                assert element.rect['top'] == 200
                assert element.rect['width'] == 200
                assert element.rect['height'] == 50

    @pytest.mark.asyncio
    async def test_ai_locate_with_cache(self, mock_interface, mock_ai_response, temp_cache_dir):
        """测试带缓存的元素定位"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(
                interface=mock_interface,
                model="qwen-vl-max",
                cache_id="test_locate_cache",
                cache_dir=temp_cache_dir
            )

            # Mock AI 调用
            with patch.object(agent.model, 'call', return_value=mock_ai_response("locate")) as mock_call:
                # 第一次调用（应该调用 AI）
                element1 = await agent.ai_locate("登录按钮")
                assert element1 is not None
                assert mock_call.call_count == 1

                # 第二次调用（应该使用缓存）
                element2 = await agent.ai_locate("登录按钮")
                assert element2 is not None
                assert mock_call.call_count == 1  # 没有增加，使用了缓存

                # 验证两次结果一致
                assert element1.center == element2.center

    @pytest.mark.asyncio
    async def test_ai_locate_with_recording(self, mock_interface, mock_ai_response):
        """测试带执行记录的元素定位"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(
                interface=mock_interface,
                model="qwen-vl-max",
                enable_recording=True
            )

            # Mock AI 调用
            with patch.object(agent.model, 'call', return_value=mock_ai_response("locate")):
                element = await agent.ai_locate("搜索框")

                assert element is not None
                assert agent.recorder is not None
                assert len(agent.recorder.tasks) > 0

                # 验证记录内容
                task = agent.recorder.tasks[-1]
                assert task.type == "locate"
                assert task.param == "搜索框"
                assert task.status == "finished"
                assert task.usage is not None


class TestAIClick:
    """测试 AI 点击操作"""

    @pytest.mark.asyncio
    async def test_ai_click_success(self, mock_interface, mock_ai_response):
        """测试成功点击"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(interface=mock_interface, model="qwen-vl-max")

            # Mock AI 调用
            with patch.object(agent.model, 'call', return_value=mock_ai_response("locate")):
                success = await agent.ai_click("搜索按钮")

                assert success is True
                assert len(mock_interface.clicked_positions) == 1
                assert mock_interface.clicked_positions[0] == (200.0, 225.0)

    @pytest.mark.asyncio
    async def test_ai_click_failure(self, mock_interface):
        """测试点击失败（元素未找到）"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(interface=mock_interface, model="qwen-vl-max")

            # Mock AI 调用返回无效响应
            with patch.object(agent.model, 'call', return_value={"content": '{}', "usage": {}}):
                success = await agent.ai_click("不存在的按钮")

                assert success is False
                assert len(mock_interface.clicked_positions) == 0


class TestAIInput:
    """测试 AI 文本输入"""

    @pytest.mark.asyncio
    async def test_ai_input_success(self, mock_interface, mock_ai_response):
        """测试成功输入文本"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(interface=mock_interface, model="qwen-vl-max")

            # Mock AI 调用
            with patch.object(agent.model, 'call', return_value=mock_ai_response("locate")):
                success = await agent.ai_input("搜索框", "Python 教程")

                assert success is True
                assert len(mock_interface.input_texts) == 1
                assert mock_interface.input_texts[0] == "Python 教程"
                assert len(mock_interface.clicked_positions) == 1  # 先点击再输入


class TestAIQuery:
    """测试 AI 数据提取"""

    @pytest.mark.asyncio
    async def test_ai_query_dict_demand(self, mock_interface, mock_ai_response):
        """测试字典格式的数据提取"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(interface=mock_interface, model="qwen-vl-max")

            # Mock AI 调用
            with patch.object(agent.model, 'call', return_value=mock_ai_response("extract")):
                result = await agent.ai_query({
                    "title": "页面标题",
                    "count": "数量"
                })

                assert result is not None
                assert "data" in result
                assert result["data"]["title"] == "测试标题"
                assert result["data"]["count"] == 42

    @pytest.mark.asyncio
    async def test_ai_query_with_recording(self, mock_interface, mock_ai_response):
        """测试带执行记录的数据提取"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(
                interface=mock_interface,
                model="qwen-vl-max",
                enable_recording=True
            )

            # Mock AI 调用
            with patch.object(agent.model, 'call', return_value=mock_ai_response("extract")):
                result = await agent.ai_query({"title": "页面标题"})

                assert agent.recorder is not None
                assert len(agent.recorder.tasks) > 0

                # 验证记录内容
                task = agent.recorder.tasks[-1]
                assert task.type == "query"
                assert task.status == "finished"
                assert task.output is not None


class TestAIAssert:
    """测试 AI 断言"""

    @pytest.mark.asyncio
    async def test_ai_assert_pass(self, mock_interface, mock_ai_response):
        """测试断言通过"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(interface=mock_interface, model="qwen-vl-max")

            # Mock AI 调用
            with patch.object(agent.model, 'call', return_value=mock_ai_response("assert")):
                result = await agent.ai_assert("页面显示了搜索结果")

                assert result is True

    @pytest.mark.asyncio
    async def test_ai_assert_fail(self, mock_interface):
        """测试断言失败"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(interface=mock_interface, model="qwen-vl-max")

            # Mock AI 调用返回失败
            fail_response = {
                "content": '{"pass": false, "thought": "未找到搜索结果"}',
                "usage": {}
            }

            with patch.object(agent.model, 'call', return_value=fail_response):
                with pytest.raises(AssertionError) as exc_info:
                    await agent.ai_assert("页面显示了搜索结果")

                assert "未找到搜索结果" in str(exc_info.value)


class TestCompleteWorkflow:
    """测试完整的工作流程"""

    @pytest.mark.asyncio
    async def test_complete_automation_workflow(
        self,
        mock_interface,
        mock_ai_response,
        temp_cache_dir
    ):
        """测试完整的自动化流程"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(
                interface=mock_interface,
                model="qwen-vl-max",
                cache_id="complete_workflow",
                cache_dir=temp_cache_dir,
                enable_recording=True
            )

            # Mock AI 调用
            with patch.object(agent.model, 'call') as mock_call:
                # 配置不同的响应
                mock_call.side_effect = [
                    mock_ai_response("locate"),  # 定位搜索框
                    mock_ai_response("locate"),  # 定位搜索按钮
                    mock_ai_response("extract"),  # 提取数据
                    mock_ai_response("assert"),  # 断言验证
                ]

                # 1. 定位并输入
                await agent.ai_input("搜索框", "Python 教程")

                # 2. 点击搜索
                await agent.ai_click("搜索按钮")

                # 3. 提取数据
                data = await agent.ai_query({"title": "页面标题"})

                # 4. 断言验证
                await agent.ai_assert("页面显示了搜索结果")

                # 验证所有操作都成功
                assert len(mock_interface.input_texts) == 1
                assert len(mock_interface.clicked_positions) == 2  # 输入时点击 + 搜索按钮点击
                assert data["data"]["title"] == "测试标题"

                # 验证执行记录
                assert agent.recorder is not None
                assert len(agent.recorder.tasks) >= 4

                # 导出执行记录
                json_report = agent.recorder.to_json()
                assert json_report is not None
                assert "logTime" in json_report
                assert "tasks" in json_report

    @pytest.mark.asyncio
    async def test_workflow_with_cache_hit(
        self,
        mock_interface,
        mock_ai_response,
        temp_cache_dir
    ):
        """测试缓存命中的工作流程"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            # 第一次执行
            agent1 = Agent(
                interface=mock_interface,
                model="qwen-vl-max",
                cache_id="cache_workflow",
                cache_dir=temp_cache_dir
            )

            with patch.object(agent1.model, 'call', return_value=mock_ai_response("locate")) as mock_call1:
                await agent1.ai_locate("登录按钮")
                assert mock_call1.call_count == 1

            # 第二次执行（应该使用缓存）
            agent2 = Agent(
                interface=mock_interface,
                model="qwen-vl-max",
                cache_id="cache_workflow",
                cache_dir=temp_cache_dir
            )

            with patch.object(agent2.model, 'call', return_value=mock_ai_response("locate")) as mock_call2:
                element = await agent2.ai_locate("登录按钮")
                assert element is not None
                assert mock_call2.call_count == 0  # 使用了缓存，没有调用 AI

                # 验证缓存统计
                stats = agent2.get_cache_stats()
                assert stats is not None
                assert stats["matched_records"] == 1


class TestExecutionRecording:
    """测试执行记录功能"""

    @pytest.mark.asyncio
    async def test_recording_full_details(self, mock_interface, mock_ai_response):
        """测试完整的执行记录"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(
                interface=mock_interface,
                model="qwen-vl-max",
                enable_recording=True
            )

            with patch.object(agent.model, 'call', return_value=mock_ai_response("locate")):
                await agent.ai_locate("搜索框")

                # 验证执行记录的详细信息
                assert agent.recorder is not None
                assert len(agent.recorder.tasks) == 1

                task = agent.recorder.tasks[0]
                assert task.type == "locate"
                assert task.param == "搜索框"
                assert task.status == "finished"

                # 验证截图记录
                assert len(task.recorder) > 0
                screenshot_record = task.recorder[0]
                assert screenshot_record.type == "screenshot"
                assert screenshot_record.screenshot is not None

                # 验证 AI 使用信息
                assert task.usage is not None
                assert task.usage.get("total_tokens") == 1050
                assert task.usage.get("model_name") == "qwen-vl-max"

    @pytest.mark.asyncio
    async def test_recording_export_json(self, mock_interface, mock_ai_response):
        """测试执行记录导出为 JSON"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(
                interface=mock_interface,
                model="qwen-vl-max",
                enable_recording=True
            )

            with patch.object(agent.model, 'call', return_value=mock_ai_response("locate")):
                await agent.ai_locate("搜索框")

                # 导出 JSON
                json_str = agent.recorder.to_json()
                assert json_str is not None
                assert isinstance(json_str, str)
                assert "logTime" in json_str
                assert "tasks" in json_str
                assert "locate" in json_str
                assert "搜索框" in json_str


class TestErrorHandling:
    """测试错误处理"""

    @pytest.mark.asyncio
    async def test_locate_error_handling(self, mock_interface):
        """测试定位错误处理"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(
                interface=mock_interface,
                model="qwen-vl-max",
                enable_recording=True
            )

            # Mock AI 调用抛出异常
            with patch.object(agent.model, 'call', side_effect=Exception("API Error")):
                with pytest.raises(Exception) as exc_info:
                    await agent.ai_locate("搜索框")

                assert "API Error" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_invalid_bbox_response(self, mock_interface):
        """测试无效的 bbox 响应"""
        with patch.dict('os.environ', {
            'MIDSCENE_QWEN_API_KEY': 'test-api-key'
        }):
            agent = Agent(interface=mock_interface, model="qwen-vl-max")

            # Mock AI 调用返回无效 bbox
            invalid_response = {
                "content": '{"bbox": [100, 200]}',  # 只有 2 个值，应该有 4 个
                "usage": {}
            }

            with patch.object(agent.model, 'call', return_value=invalid_response):
                element = await agent.ai_locate("搜索框")

                assert element is None  # 应该返回 None
