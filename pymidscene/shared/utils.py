"""
工具函数模块 - 对应 packages/core/src/common.ts 和 packages/shared/src/utils/

提供常用的工具函数，包括坐标转换等。
"""

import hashlib
import json
import re
import base64
from typing import Any, Optional, Dict, List, Union, Tuple
from io import BytesIO
from PIL import Image


# 默认 bbox 尺寸（用于点坐标转 bbox）- 对应 JS 的 defaultBboxSize
DEFAULT_BBOX_SIZE = 20


def calculate_hash(text: str) -> str:
    """计算字符串的 MD5 哈希值"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def safe_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """安全解析 JSON，失败返回 None"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def extract_json_from_code_block(text: str) -> str:
    """
    从 Markdown 代码块中提取 JSON
    
    对应 JS 版本: extractJSONFromCodeBlock (service-caller/index.ts:500-524)
    """
    try:
        # 首先尝试直接匹配 JSON 对象
        json_match = re.match(r'^\s*(\{[\s\S]*\})\s*$', text)
        if json_match:
            return json_match.group(1)

        # 尝试从代码块中提取
        code_block_match = re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text)
        if code_block_match:
            return code_block_match.group(1)

        # 尝试找到类似 JSON 的结构
        json_like_match = re.search(r'\{[\s\S]*\}', text)
        if json_like_match:
            return json_like_match.group(0)
    except Exception:
        pass

    return text


def normalize_json_object(obj: Any) -> Any:
    """
    规范化 JSON 对象，去除 key 和 value 的前后空格
    
    对应 JS 版本: normalizeJsonObject (service-caller/index.ts:606-646)
    """
    if obj is None:
        return obj

    if isinstance(obj, list):
        return [normalize_json_object(item) for item in obj]

    if isinstance(obj, dict):
        normalized = {}
        for key, value in obj.items():
            trimmed_key = key.strip() if isinstance(key, str) else key
            normalized_value = normalize_json_object(value)
            if isinstance(normalized_value, str):
                normalized_value = normalized_value.strip()
            normalized[trimmed_key] = normalized_value
        return normalized

    if isinstance(obj, str):
        return obj.strip()

    return obj


def preprocess_doubao_bbox_json(input_str: str) -> str:
    """
    预处理豆包 bbox JSON 格式
    
    豆包可能返回空格分隔的 bbox 值："940 445 969 490"
    需要转换为逗号分隔："940,445,969,490"
    
    对应 JS 版本: preprocessDoubaoBboxJson (service-caller/index.ts:526-534)
    """
    if 'bbox' not in input_str:
        return input_str

    # 将 bbox 值中的空格替换为逗号
    while re.search(r'\d+\s+\d+', input_str):
        input_str = re.sub(r'(\d+)\s+(\d+)', r'\1,\2', input_str)

    return input_str


def is_ui_tars(model_family: Optional[str]) -> bool:
    """
    判断是否是 UI-TARS 模型
    
    对应 JS 版本: isUITars (auto-glm/util.ts:17-23)
    """
    return model_family in (
        'vlm-ui-tars',
        'vlm-ui-tars-doubao',
        'vlm-ui-tars-doubao-1.5',
    )


def resize_image_base64(
    base64_str: str,
    max_width: int = 1280,
    max_height: int = 720
) -> str:
    """
    调整 Base64 编码图像的大小

    Args:
        base64_str: Base64 编码的图像字符串
        max_width: 最大宽度
        max_height: 最大高度

    Returns:
        调整后的 Base64 编码图像字符串
    """
    # 解码 Base64
    image_data = base64.b64decode(base64_str)

    # 打开图像
    image = Image.open(BytesIO(image_data))

    # 计算缩放比例
    width, height = image.size
    scale = min(max_width / width, max_height / height, 1.0)

    if scale < 1.0:
        new_width = int(width * scale)
        new_height = int(height * scale)
        image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

    # 转换回 Base64
    buffer = BytesIO()
    image.save(buffer, format=image.format or 'PNG')
    return base64.b64encode(buffer.getvalue()).decode('utf-8')


def get_screenshot_scale(screenshot_width: float, page_width: float) -> float:
    """
    计算截图与页面的缩放比例

    Args:
        screenshot_width: 截图宽度
        page_width: 页面宽度

    Returns:
        缩放比例
    """
    return screenshot_width / page_width if page_width > 0 else 1.0


def point_to_bbox(
    x: int,
    y: int,
    bbox_size: int = DEFAULT_BBOX_SIZE
) -> Tuple[int, int, int, int]:
    """
    将点坐标转换为 bbox
    
    对应 JS 版本: pointToBbox (common.ts:38-50)
    
    Args:
        x: X 坐标
        y: Y 坐标
        bbox_size: bbox 尺寸
    
    Returns:
        bbox (x1, y1, x2, y2)
    """
    half_size = bbox_size // 2
    x1 = max(x - half_size, 0)
    y1 = max(y - half_size, 0)
    x2 = min(x + half_size, 1000)
    y2 = min(y + half_size, 1000)
    return (x1, y1, x2, y2)


def normalize_bbox_input(bbox: Any) -> Union[List, str]:
    """
    规范化 bbox 输入，处理嵌套数组
    
    对应 JS 版本: normalizeBboxInput (common.ts:196-206)
    
    Args:
        bbox: 原始 bbox 输入
    
    Returns:
        规范化后的 bbox
    """
    if isinstance(bbox, list):
        if len(bbox) > 0 and isinstance(bbox[0], list):
            return bbox[0]
        return bbox
    return bbox


def adapt_doubao_bbox(
    bbox: Union[List, str],
    width: int,
    height: int
) -> Tuple[int, int, int, int]:
    """
    转换 doubao-vision 模型的 bbox 坐标
    
    Doubao 模型返回的是归一化到 0-1000 的坐标，需要转换为实际像素坐标
    
    对应 JS 版本: adaptDoubaoBbox (common.ts:108-192)
    
    Args:
        bbox: bbox 数据，可以是数组或字符串格式
        width: 图像宽度
        height: 图像高度
    
    Returns:
        转换后的 bbox (x1, y1, x2, y2)
    """
    assert width > 0 and height > 0, "width and height must be greater than 0"
    
    # 处理字符串格式："x1 y1 x2 y2"
    if isinstance(bbox, str):
        # 验证格式
        if not re.match(r'^(\d+)\s(\d+)\s(\d+)\s(\d+)$', bbox.strip()):
            raise ValueError(f"Invalid bbox string format for doubao-vision: {bbox}")
        
        parts = bbox.strip().split()
        if len(parts) == 4:
            return (
                round(int(parts[0]) * width / 1000),
                round(int(parts[1]) * height / 1000),
                round(int(parts[2]) * width / 1000),
                round(int(parts[3]) * height / 1000),
            )
        raise ValueError(f"Invalid bbox string format for doubao-vision: {bbox}")
    
    # 处理数组格式
    bbox_list: List[float] = []
    if isinstance(bbox, list):
        # 处理字符串数组格式：["123 222", "789 100"] 或 ["123,222", "789,100"] 或 ["500", "300", "600", "400"]
        for item in bbox:
            if isinstance(item, str):
                item = item.strip()
                if ',' in item:
                    # 格式: "123,222"
                    parts = item.split(',')
                    bbox_list.extend([float(p.strip()) for p in parts])
                elif ' ' in item:
                    # 格式: "123 222"
                    parts = item.split()
                    bbox_list.extend([float(p.strip()) for p in parts])
                else:
                    # 单个数字字符串: "500"
                    bbox_list.append(float(item))
            else:
                bbox_list.append(float(item))
    
    # 4 或 5 个元素 - 标准 bbox
    if len(bbox_list) in (4, 5):
        return (
            round(bbox_list[0] * width / 1000),
            round(bbox_list[1] * height / 1000),
            round(bbox_list[2] * width / 1000),
            round(bbox_list[3] * height / 1000),
        )
    
    # 2, 3, 6, 7 个元素 - 中心点模式，扩展为 bbox
    if len(bbox_list) in (2, 3, 6, 7):
        half_size = DEFAULT_BBOX_SIZE // 2
        center_x = round(bbox_list[0] * width / 1000)
        center_y = round(bbox_list[1] * height / 1000)
        return (
            max(0, center_x - half_size),
            max(0, center_y - half_size),
            min(width, center_x + half_size),
            min(height, center_y + half_size),
        )
    
    # 8 个元素 - 四角模式 (对应 JS: 取第 0,1,4,5 个点)
    if len(bbox_list) == 8:
        return (
            round(bbox_list[0] * width / 1000),
            round(bbox_list[1] * height / 1000),
            round(bbox_list[4] * width / 1000),
            round(bbox_list[5] * height / 1000),
        )
    
    raise ValueError(f"Invalid bbox format: {bbox}")


def adapt_qwen2_5_bbox(bbox: List) -> Tuple[int, int, int, int]:
    """
    转换 qwen2.5-vl 模型的 bbox 坐标
    
    Qwen 2.5 模型直接返回像素坐标，不需要归一化转换
    
    对应 JS 版本: adaptQwen2_5Bbox (common.ts:82-101)
    
    Args:
        bbox: bbox 数组
    
    Returns:
        转换后的 bbox (x1, y1, x2, y2)
    """
    if len(bbox) < 2:
        raise ValueError(f"Invalid bbox for qwen2.5-vl: {bbox}")
    
    return (
        round(bbox[0]),
        round(bbox[1]),
        round(bbox[2]) if len(bbox) > 2 and bbox[2] is not None else round(bbox[0] + DEFAULT_BBOX_SIZE),
        round(bbox[3]) if len(bbox) > 3 and bbox[3] is not None else round(bbox[1] + DEFAULT_BBOX_SIZE),
    )


def adapt_gemini_bbox(
    bbox: List,
    width: int,
    height: int
) -> Tuple[int, int, int, int]:
    """
    转换 Gemini 模型的 bbox 坐标
    
    Gemini 模型返回的格式是 [y1, x1, y2, x2]，归一化到 0-1000
    
    对应 JS 版本: adaptGeminiBbox (common.ts:103-106)
    
    Args:
        bbox: bbox 数组
        width: 图像宽度
        height: 图像高度
    
    Returns:
        转换后的 bbox (x1, y1, x2, y2)
    """
    # 注意：Gemini 的顺序是 [y1, x1, y2, x2]
    return (
        round(bbox[1] * width / 1000),   # x1 = bbox[1]
        round(bbox[0] * height / 1000),  # y1 = bbox[0]
        round(bbox[3] * width / 1000),   # x2 = bbox[3]
        round(bbox[2] * height / 1000),  # y2 = bbox[2]
    )


def normalized_0_1000(
    bbox: List,
    width: int,
    height: int
) -> Tuple[int, int, int, int]:
    """
    转换归一化 0-1000 坐标到像素坐标
    
    默认的归一化坐标转换，适用于 qwen3-vl, glm-v, auto-glm 等模型
    
    对应 JS 版本: normalized01000 (common.ts:238-249)
    
    Args:
        bbox: bbox 数组 [x1, y1, x2, y2]，归一化到 0-1000
        width: 图像宽度
        height: 图像高度
    
    Returns:
        转换后的 bbox (x1, y1, x2, y2)
    """
    return (
        round(bbox[0] * width / 1000),
        round(bbox[1] * height / 1000),
        round(bbox[2] * width / 1000),
        round(bbox[3] * height / 1000),
    )


def adapt_bbox(
    bbox: Union[List, str],
    width: int,
    height: int,
    right_limit: Optional[int] = None,
    bottom_limit: Optional[int] = None,
    model_family: Optional[str] = None
) -> Tuple[int, int, int, int]:
    """
    根据模型类型适配 bbox 坐标
    
    不同模型返回的坐标格式不同，需要统一转换为像素坐标
    
    对应 JS 版本: adaptBbox (common.ts:208-235)
    
    坐标系统说明：
    - qwen2.5-vl: 绝对像素坐标
    - gemini: 归一化 0-1000，顺序是 [y1, x1, y2, x2]
    - doubao-vision/UI-TARS: 归一化 0-1000，顺序是 [x1, y1, x2, y2]
    - qwen3-vl/glm-v 等: 归一化 0-1000 (默认)
    
    Args:
        bbox: AI 返回的 bbox 数据
        width: 图像宽度
        height: 图像高度
        right_limit: 右边界限制（默认为 width）
        bottom_limit: 下边界限制（默认为 height）
        model_family: 模型家族类型
    
    Returns:
        转换后的 bbox (x1, y1, x2, y2) 像素坐标
    """
    if right_limit is None:
        right_limit = width
    if bottom_limit is None:
        bottom_limit = height
    
    # 规范化输入
    normalized_bbox = normalize_bbox_input(bbox)
    
    result: Tuple[int, int, int, int]
    
    # Doubao/UI-TARS 使用 0-1000 归一化坐标
    if model_family == 'doubao-vision' or is_ui_tars(model_family):
        result = adapt_doubao_bbox(normalized_bbox, width, height)
    
    # Gemini 使用 0-1000 归一化坐标，但顺序不同
    elif model_family == 'gemini':
        bbox_list: List[float]
        if isinstance(normalized_bbox, str):
            parts = re.split(r'[,\s]+', normalized_bbox.strip())
            bbox_list = [float(p) for p in parts]
        else:
            bbox_list = [float(x) for x in normalized_bbox]
        result = adapt_gemini_bbox(bbox_list, width, height)
    
    # Qwen 2.5 使用绝对像素坐标
    elif model_family == 'qwen2.5-vl':
        bbox_list_qwen: List[float]
        if isinstance(normalized_bbox, str):
            parts = re.split(r'[,\s]+', normalized_bbox.strip())
            bbox_list_qwen = [float(p) for p in parts]
        else:
            bbox_list_qwen = [float(x) for x in normalized_bbox]
        result = adapt_qwen2_5_bbox(bbox_list_qwen)
    
    # 默认：使用归一化 0-1000 坐标系统
    # 包括: qwen3-vl, glm-v, auto-glm, auto-glm-multilingual 等
    else:
        if isinstance(normalized_bbox, str):
            # 尝试解析字符串格式
            parts = re.split(r'[,\s]+', normalized_bbox.strip())
            if len(parts) == 4:
                normalized_bbox = [float(p) for p in parts]
        
        if isinstance(normalized_bbox, list) and len(normalized_bbox) >= 4:
            result = normalized_0_1000(normalized_bbox, width, height)
        else:
            raise ValueError(f"Unsupported bbox format: {bbox}")
    
    # 应用边界限制
    result = (
        result[0],
        result[1],
        min(result[2], right_limit),
        min(result[3], bottom_limit),
    )
    
    return result


def fill_bbox_param(
    locate: Dict[str, Any],
    width: int,
    height: int,
    right_limit: int,
    bottom_limit: int,
    model_family: Optional[str] = None
) -> Dict[str, Any]:
    """
    填充 bbox 参数，处理 Qwen 的 bbox_2d 幻觉问题
    
    对应 JS 版本: fillBboxParam (common.ts:52-80)
    
    Args:
        locate: 定位参数字典
        width: 图像宽度
        height: 图像高度
        right_limit: 右边界限制
        bottom_limit: 下边界限制
        model_family: 模型家族类型
    
    Returns:
        处理后的定位参数
    """
    # Qwen 模型可能将 bbox 命名为 bbox_2d（幻觉）
    if 'bbox_2d' in locate and 'bbox' not in locate:
        locate['bbox'] = locate.pop('bbox_2d')
    
    if 'bbox' in locate and locate['bbox']:
        locate['bbox'] = adapt_bbox(
            locate['bbox'],
            width,
            height,
            right_limit,
            bottom_limit,
            model_family,
        )
    
    return locate


def adapt_bbox_to_rect(
    bbox: List,
    width: int,
    height: int,
    offset_x: int = 0,
    offset_y: int = 0,
    right_limit: Optional[int] = None,
    bottom_limit: Optional[int] = None,
    model_family: Optional[str] = None
) -> Dict[str, float]:
    """
    将 bbox 转换为 Rect 对象
    
    对应 JS 版本: adaptBboxToRect (common.ts:251-290)
    
    Args:
        bbox: bbox 数组
        width: 图像宽度
        height: 图像高度
        offset_x: X 偏移
        offset_y: Y 偏移
        right_limit: 右边界限制
        bottom_limit: 下边界限制
        model_family: 模型家族类型
    
    Returns:
        Rect 字典 {left, top, width, height, right, bottom}
    """
    if right_limit is None:
        right_limit = width
    if bottom_limit is None:
        bottom_limit = height
    
    adapted = adapt_bbox(bbox, width, height, right_limit, bottom_limit, model_family)
    
    left = adapted[0] + offset_x
    top = adapted[1] + offset_y
    right = adapted[2] + offset_x
    bottom = adapted[3] + offset_y
    
    return {
        "left": float(left),
        "top": float(top),
        "width": float(right - left),
        "height": float(bottom - top),
        "right": float(right),
        "bottom": float(bottom),
    }


def format_bbox(bbox: tuple) -> Dict[str, float]:
    """
    将 bbox 元组转换为 Rect 字典

    Args:
        bbox: [xmin, ymin, xmax, ymax] 元组（像素坐标）

    Returns:
        Rect 字典 {left, top, width, height}
    """
    if len(bbox) != 4:
        raise ValueError(f"bbox must have 4 elements, got {len(bbox)}")

    xmin, ymin, xmax, ymax = bbox
    
    return {
        "left": float(xmin),
        "top": float(ymin),
        "width": float(xmax - xmin),
        "height": float(ymax - ymin),
    }


def calculate_center(rect: Dict[str, float]) -> tuple:
    """
    计算矩形的中心点

    Args:
        rect: 矩形字典

    Returns:
        (x, y) 中心点坐标
    """
    x = rect["left"] + rect["width"] / 2
    y = rect["top"] + rect["height"] / 2
    return (x, y)


__all__ = [
    "calculate_hash",
    "safe_parse_json",
    "extract_json_from_code_block",
    "normalize_json_object",
    "preprocess_doubao_bbox_json",
    "is_ui_tars",
    "resize_image_base64",
    "get_screenshot_scale",
    "point_to_bbox",
    "normalize_bbox_input",
    "adapt_bbox",
    "adapt_doubao_bbox",
    "adapt_qwen2_5_bbox",
    "adapt_gemini_bbox",
    "normalized_0_1000",
    "fill_bbox_param",
    "adapt_bbox_to_rect",
    "format_bbox",
    "calculate_center",
    "DEFAULT_BBOX_SIZE",
]
