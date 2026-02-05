"""
工具函数模块 - 对应 packages/shared/src/utils/

提供常用的工具函数。
"""

import hashlib
import json
import base64
from typing import Any, Optional, Dict, List, Union, Tuple
from io import BytesIO
from PIL import Image


# 默认 bbox 尺寸（用于点坐标转 bbox）
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
    """从 Markdown 代码块中提取 JSON"""
    # 移除 ```json ... ``` 或 ``` ... ``` 包裹
    text = text.strip()

    # 尝试匹配 ```json 格式
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]

    if text.endswith("```"):
        text = text[:-3]

    return text.strip()


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


def adapt_doubao_bbox(
    bbox: Union[List, str],
    width: int,
    height: int
) -> Tuple[int, int, int, int]:
    """
    转换 doubao-vision 模型的 bbox 坐标
    
    Doubao 模型返回的是归一化到 0-1000 的坐标，需要转换为实际像素坐标
    
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
        parts = bbox.strip().split()
        if len(parts) == 4:
            return (
                round(int(parts[0]) * width / 1000),
                round(int(parts[1]) * height / 1000),
                round(int(parts[2]) * width / 1000),
                round(int(parts[3]) * height / 1000),
            )
    
    # 处理数组格式
    bbox_list = []
    if isinstance(bbox, list):
        for item in bbox:
            if isinstance(item, str):
                if ',' in item:
                    x, y = item.split(',')
                    bbox_list.extend([float(x.strip()), float(y.strip())])
                elif ' ' in item:
                    x, y = item.split(' ')
                    bbox_list.extend([float(x.strip()), float(y.strip())])
                else:
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
        center_x = round(bbox_list[0] * width / 1000)
        center_y = round(bbox_list[1] * height / 1000)
        half_size = DEFAULT_BBOX_SIZE // 2
        return (
            max(0, center_x - half_size),
            max(0, center_y - half_size),
            min(width, center_x + half_size),
            min(height, center_y + half_size),
        )
    
    # 8 个元素 - 四角模式
    if len(bbox_list) == 8:
        return (
            round(bbox_list[0] * width / 1000),
            round(bbox_list[1] * height / 1000),
            round(bbox_list[4] * width / 1000),
            round(bbox_list[5] * height / 1000),
        )
    
    raise ValueError(f"Invalid bbox format: {bbox}")


def adapt_qwen_bbox(bbox: List) -> Tuple[int, int, int, int]:
    """
    转换 qwen2.5-vl 模型的 bbox 坐标
    
    Qwen 模型直接返回像素坐标，不需要归一化转换
    
    Args:
        bbox: bbox 数组
    
    Returns:
        转换后的 bbox (x1, y1, x2, y2)
    """
    if len(bbox) < 2:
        raise ValueError(f"Invalid bbox for qwen-vl: {bbox}")
    
    return (
        round(bbox[0]),
        round(bbox[1]),
        round(bbox[2]) if len(bbox) > 2 else round(bbox[0] + DEFAULT_BBOX_SIZE),
        round(bbox[3]) if len(bbox) > 3 else round(bbox[1] + DEFAULT_BBOX_SIZE),
    )


def adapt_gemini_bbox(
    bbox: List,
    width: int,
    height: int
) -> Tuple[int, int, int, int]:
    """
    转换 Gemini 模型的 bbox 坐标
    
    Gemini 模型返回的格式是 [y1, x1, y2, x2]，归一化到 0-1000
    
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
    
    默认的归一化坐标转换，适用于大多数模型
    
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
    model_family: Optional[str] = None
) -> Tuple[int, int, int, int]:
    """
    根据模型类型适配 bbox 坐标
    
    不同模型返回的坐标格式不同，需要统一转换为像素坐标
    
    Args:
        bbox: AI 返回的 bbox 数据
        width: 图像宽度
        height: 图像高度
        model_family: 模型家族类型
    
    Returns:
        转换后的 bbox (x1, y1, x2, y2) 像素坐标
    """
    if model_family in ('doubao-vision', 'vlm-ui-tars-doubao', 'vlm-ui-tars-doubao-1.5'):
        return adapt_doubao_bbox(bbox, width, height)
    elif model_family == 'gemini':
        return adapt_gemini_bbox(bbox, width, height)
    elif model_family == 'qwen2.5-vl':
        return adapt_qwen_bbox(bbox)
    else:
        # 默认使用归一化 0-1000 坐标转换
        if isinstance(bbox, list) and len(bbox) >= 4:
            return normalized_0_1000(bbox, width, height)
        raise ValueError(f"Unsupported bbox format: {bbox}")


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
    "resize_image_base64",
    "get_screenshot_scale",
    "adapt_bbox",
    "adapt_doubao_bbox",
    "adapt_qwen_bbox",
    "adapt_gemini_bbox",
    "normalized_0_1000",
    "format_bbox",
    "calculate_center",
    "DEFAULT_BBOX_SIZE",
]
