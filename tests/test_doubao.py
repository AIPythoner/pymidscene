"""
豆包模型单元测试

测试豆包模型的基本功能、坐标系统适配等。
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from pymidscene.core.ai_model.models.doubao import DoubaoVisionModel


class TestDoubaoVisionModel:
    """测试豆包视觉模型"""

    def test_model_initialization(self):
        """测试模型初始化"""
        with patch.dict('os.environ', {
            'MIDSCENE_DOUBAO_API_KEY': 'test-key',
            'MIDSCENE_DOUBAO_MODEL_NAME': 'ep-test123'
        }):
            model = DoubaoVisionModel(
                model_name="doubao-vision",
                api_key="test-key",
                base_url="https://test.api.com",
                endpoint_id="ep-test123"
            )

            assert model.model_name == "doubao-vision"
            assert model.api_key == "test-key"
            assert model.endpoint_id == "ep-test123"
            assert model.base_url == "https://test.api.com"

    def test_from_env(self):
        """测试从环境变量创建"""
        with patch.dict('os.environ', {
            'MIDSCENE_DOUBAO_API_KEY': 'env-key',
            'MIDSCENE_DOUBAO_BASE_URL': 'https://env.api.com',
            'MIDSCENE_DOUBAO_MODEL_NAME': 'ep-env123'
        }):
            model = DoubaoVisionModel.from_env("doubao-vision")

            assert model.api_key == "env-key"
            assert model.base_url == "https://env.api.com"
            assert model.endpoint_id == "ep-env123"

    def test_missing_api_key(self):
        """测试缺少 API 密钥"""
        with patch.dict('os.environ', {}, clear=True):
            with pytest.raises(ValueError, match="API key is required"):
                DoubaoVisionModel(model_name="doubao-vision")

    def test_missing_endpoint_id(self):
        """测试缺少推理接入点 ID"""
        with patch.dict('os.environ', {
            'MIDSCENE_DOUBAO_API_KEY': 'test-key'
        }):
            with pytest.raises(ValueError, match="endpoint ID is required"):
                DoubaoVisionModel(model_name="doubao-vision")


class TestBboxPreprocessing:
    """测试 bbox 预处理"""

    def test_preprocess_bbox_spaces(self):
        """测试空格分隔的 bbox 预处理"""
        input_str = '{"bbox": "940 445 969 490"}'
        expected = '{"bbox": "940,445,969,490"}'

        result = DoubaoVisionModel.preprocess_doubao_bbox_json(input_str)
        assert result == expected

    def test_preprocess_bbox_multiple_spaces(self):
        """测试多个空格"""
        input_str = '{"bbox": "100  200  300  400"}'
        result = DoubaoVisionModel.preprocess_doubao_bbox_json(input_str)

        # 所有空格都应该被逗号替换
        assert "100,200,300,400" in result

    def test_preprocess_no_bbox(self):
        """测试没有 bbox 的情况"""
        input_str = '{"result": "success"}'
        result = DoubaoVisionModel.preprocess_doubao_bbox_json(input_str)

        # 应该保持不变
        assert result == input_str

    def test_preprocess_already_comma_separated(self):
        """测试已经用逗号分隔的 bbox"""
        input_str = '{"bbox": [940, 445, 969, 490]}'
        result = DoubaoVisionModel.preprocess_doubao_bbox_json(input_str)

        # 应该保持不变
        assert result == input_str


class TestBboxAdaptation:
    """测试 bbox 坐标适配"""

    def test_adapt_bbox_string_format(self):
        """测试字符串格式 bbox 适配"""
        bbox = "500 300 700 400"  # 0-1000 归一化坐标
        width, height = 1920, 1080

        result = DoubaoVisionModel.adapt_doubao_bbox(bbox, width, height)

        # 500/1000 * 1920 = 960
        # 300/1000 * 1080 = 324
        # 700/1000 * 1920 = 1344
        # 400/1000 * 1080 = 432
        assert result == (960, 324, 1344, 432)

    def test_adapt_bbox_array_format(self):
        """测试数组格式 bbox 适配"""
        bbox = [500, 300, 700, 400]
        width, height = 1920, 1080

        result = DoubaoVisionModel.adapt_doubao_bbox(bbox, width, height)
        assert result == (960, 324, 1344, 432)

    def test_adapt_bbox_center_point(self):
        """测试中心点格式适配"""
        bbox = [500, 500]  # 中心点
        width, height = 1920, 1080

        result = DoubaoVisionModel.adapt_doubao_bbox(bbox, width, height)

        # 中心点 (960, 540)，创建 ±5 像素的小矩形
        assert result == (955, 535, 965, 545)

    def test_adapt_bbox_quadrilateral(self):
        """测试四边形格式适配"""
        # 四边形：[x1,y1, x2,y2, x3,y3, x4,y4]
        bbox = [100, 100, 200, 100, 200, 200, 100, 200]
        width, height = 1000, 1000

        result = DoubaoVisionModel.adapt_doubao_bbox(bbox, width, height)

        # 外接矩形：min(100,200,200,100)=100, max(100,200,200,100)=200
        # 转换：100/1000*1000=100, 200/1000*1000=200
        assert result == (100, 100, 200, 200)

    def test_adapt_bbox_invalid_format(self):
        """测试无效格式"""
        bbox = [100]  # 长度为 1，无效
        width, height = 1920, 1080

        with pytest.raises(ValueError, match="Unsupported bbox format"):
            DoubaoVisionModel.adapt_doubao_bbox(bbox, width, height)

    def test_adapt_bbox_edge_cases(self):
        """测试边界情况"""
        # 0-1000 坐标的边界
        bbox = [0, 0, 1000, 1000]
        width, height = 1920, 1080

        result = DoubaoVisionModel.adapt_doubao_bbox(bbox, width, height)
        assert result == (0, 0, 1920, 1080)


class TestModelFamily:
    """测试模型家族识别"""

    def test_get_model_name(self):
        """测试获取模型名称"""
        with patch.dict('os.environ', {
            'MIDSCENE_DOUBAO_API_KEY': 'test-key',
            'MIDSCENE_DOUBAO_MODEL_NAME': 'ep-test'
        }):
            model = DoubaoVisionModel(
                model_name="doubao-vision",
                api_key="test-key",
                endpoint_id="ep-test"
            )

            assert model.get_model_name() == "doubao-vision"

    def test_get_model_family_doubao(self):
        """测试豆包模型家族识别"""
        with patch.dict('os.environ', {
            'MIDSCENE_DOUBAO_API_KEY': 'test-key',
            'MIDSCENE_DOUBAO_MODEL_NAME': 'ep-test'
        }):
            model = DoubaoVisionModel(
                model_name="doubao-vision",
                api_key="test-key",
                endpoint_id="ep-test"
            )

            assert model.get_model_family() == "doubao-vision"

    def test_get_model_family_ui_tars(self):
        """测试 UI-TARS 模型家族识别"""
        with patch.dict('os.environ', {
            'MIDSCENE_DOUBAO_API_KEY': 'test-key',
            'MIDSCENE_DOUBAO_MODEL_NAME': 'ep-test'
        }):
            model = DoubaoVisionModel(
                model_name="vlm-ui-tars-doubao-1.5",
                api_key="test-key",
                endpoint_id="ep-test"
            )

            assert model.get_model_family() == "vlm-ui-tars-doubao"


class TestDeepThinkMapping:
    """测试深度思考参数映射"""

    @patch('pymidscene.core.ai_model.models.doubao.OpenAI')
    def test_deep_think_enabled(self, mock_openai_class):
        """测试深度思考启用"""
        # Mock OpenAI client
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"result": "success"}'
        mock_response.usage = None

        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict('os.environ', {
            'MIDSCENE_DOUBAO_API_KEY': 'test-key',
            'MIDSCENE_DOUBAO_MODEL_NAME': 'ep-test'
        }):
            model = DoubaoVisionModel(
                model_name="doubao-vision",
                api_key="test-key",
                endpoint_id="ep-test"
            )

            messages = [{"role": "user", "content": "test"}]
            model.call(messages, deep_think=True)

            # 验证调用参数
            call_args = mock_client.chat.completions.create.call_args
            assert 'extra_body' in call_args[1]
            assert call_args[1]['extra_body']['config']['thinking']['type'] == 'enabled'

    @patch('pymidscene.core.ai_model.models.doubao.OpenAI')
    def test_deep_think_disabled(self, mock_openai_class):
        """测试深度思考禁用"""
        mock_client = MagicMock()
        mock_openai_class.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"result": "success"}'
        mock_response.usage = None

        mock_client.chat.completions.create.return_value = mock_response

        with patch.dict('os.environ', {
            'MIDSCENE_DOUBAO_API_KEY': 'test-key',
            'MIDSCENE_DOUBAO_MODEL_NAME': 'ep-test'
        }):
            model = DoubaoVisionModel(
                model_name="doubao-vision",
                api_key="test-key",
                endpoint_id="ep-test"
            )

            messages = [{"role": "user", "content": "test"}]
            model.call(messages, deep_think=False)

            # 验证调用参数
            call_args = mock_client.chat.completions.create.call_args
            assert 'extra_body' in call_args[1]
            assert call_args[1]['extra_body']['config']['thinking']['type'] == 'disabled'


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
