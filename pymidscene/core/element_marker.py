"""
元素标记器 - 在截图上绘制元素边界框、点击位置等标记

用于生成可视化报告，标记 AI 识别到的元素和执行的操作。
"""

import base64
import io
from typing import Tuple, List, Optional, Union
from dataclasses import dataclass

try:
    from PIL import Image, ImageDraw, ImageFont
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

from ..shared.logger import logger


@dataclass
class MarkerStyle:
    """标记样式配置"""
    # 边界框样式
    bbox_color: str = "#FF0000"  # 红色
    bbox_width: int = 3
    bbox_fill: Optional[str] = None  # 填充颜色（带透明度）

    # 点击标记样式
    click_color: str = "#00FF00"  # 绿色
    click_radius: int = 15
    click_cross_size: int = 20

    # 标签样式
    label_color: str = "#FFFFFF"  # 白色文字
    label_bg_color: str = "#FF0000"  # 红色背景
    label_font_size: int = 14
    label_padding: int = 4

    # 序号标记样式
    index_color: str = "#FFFFFF"
    index_bg_color: str = "#0066FF"  # 蓝色背景
    index_radius: int = 12


@dataclass
class ActionMarker:
    """操作标记"""
    action_type: str  # 'click', 'input', 'scroll', 'hover'
    point: Tuple[int, int]
    label: Optional[str] = None
    index: Optional[int] = None


class ElementMarker:
    """
    元素标记器

    在截图上绘制各种可视化标记：
    - 元素边界框 (bounding box)
    - 点击位置标记
    - 操作序列轨迹
    - 元素标签和序号
    """

    def __init__(self, style: Optional[MarkerStyle] = None):
        """
        初始化元素标记器

        Args:
            style: 标记样式配置
        """
        if not HAS_PIL:
            logger.warning(
                "Pillow not installed. ElementMarker will return original images. "
                "Install with: pip install Pillow"
            )

        self.style = style or MarkerStyle()
        self._font = None

    def _get_font(self, size: int = 14):
        """获取字体"""
        if not HAS_PIL:
            return None

        try:
            # 尝试加载系统字体
            return ImageFont.truetype("arial.ttf", size)
        except:
            try:
                # Windows 中文字体
                return ImageFont.truetype("msyh.ttc", size)
            except:
                try:
                    # macOS
                    return ImageFont.truetype("/System/Library/Fonts/PingFang.ttc", size)
                except:
                    # 使用默认字体
                    return ImageFont.load_default()

    def _parse_color(self, color: str) -> Tuple[int, int, int, int]:
        """
        解析颜色字符串为 RGBA

        Args:
            color: 颜色字符串 (#RGB, #RGBA, #RRGGBB, #RRGGBBAA)

        Returns:
            RGBA 元组
        """
        color = color.lstrip('#')

        if len(color) == 3:
            r, g, b = [int(c * 2, 16) for c in color]
            return (r, g, b, 255)
        elif len(color) == 4:
            r, g, b, a = [int(c * 2, 16) for c in color]
            return (r, g, b, a)
        elif len(color) == 6:
            r = int(color[0:2], 16)
            g = int(color[2:4], 16)
            b = int(color[4:6], 16)
            return (r, g, b, 255)
        elif len(color) == 8:
            r = int(color[0:2], 16)
            g = int(color[2:4], 16)
            b = int(color[4:6], 16)
            a = int(color[6:8], 16)
            return (r, g, b, a)
        else:
            return (255, 0, 0, 255)  # 默认红色

    def _base64_to_image(self, image_base64: str) -> Optional['Image.Image']:
        """将 base64 字符串转换为 PIL Image"""
        if not HAS_PIL:
            return None

        try:
            # 移除可能的 data URL 前缀
            if ',' in image_base64:
                image_base64 = image_base64.split(',')[1]

            image_data = base64.b64decode(image_base64)
            return Image.open(io.BytesIO(image_data)).convert('RGBA')
        except Exception as e:
            logger.error(f"Failed to decode base64 image: {e}")
            return None

    def _image_to_base64(self, image: 'Image.Image', format: str = 'PNG') -> str:
        """将 PIL Image 转换为 base64 字符串"""
        if not HAS_PIL:
            return ""

        buffer = io.BytesIO()
        # 转换为 RGB 模式以支持 JPEG
        if format.upper() == 'JPEG' and image.mode == 'RGBA':
            image = image.convert('RGB')
        image.save(buffer, format=format)
        return base64.b64encode(buffer.getvalue()).decode('utf-8')

    def draw_bbox(
        self,
        image_base64: str,
        bbox: Tuple[int, int, int, int],
        color: Optional[str] = None,
        label: Optional[str] = None,
        width: Optional[int] = None
    ) -> str:
        """
        在截图上绘制边界框

        Args:
            image_base64: 原始截图的 base64 字符串
            bbox: 边界框坐标 (x1, y1, x2, y2) 或 (x, y, width, height)
            color: 边框颜色
            label: 标签文字
            width: 边框宽度

        Returns:
            带标记的截图 base64 字符串
        """
        if not HAS_PIL:
            return image_base64

        image = self._base64_to_image(image_base64)
        if image is None:
            return image_base64

        draw = ImageDraw.Draw(image, 'RGBA')

        # 解析坐标
        x1, y1, x2_or_w, y2_or_h = bbox
        # 判断是 (x1, y1, x2, y2) 还是 (x, y, width, height)
        if x2_or_w > x1 and y2_or_h > y1:
            # 可能是 (x1, y1, x2, y2) 格式
            x2, y2 = x2_or_w, y2_or_h
        else:
            # (x, y, width, height) 格式
            x2 = x1 + x2_or_w
            y2 = y1 + y2_or_h

        # 绘制边界框
        box_color = self._parse_color(color or self.style.bbox_color)
        line_width = width or self.style.bbox_width

        # 绘制矩形边框
        draw.rectangle(
            [(x1, y1), (x2, y2)],
            outline=box_color[:3],
            width=line_width
        )

        # 如果有填充色，添加半透明填充
        if self.style.bbox_fill:
            fill_color = self._parse_color(self.style.bbox_fill)
            overlay = Image.new('RGBA', image.size, (0, 0, 0, 0))
            overlay_draw = ImageDraw.Draw(overlay)
            overlay_draw.rectangle(
                [(x1, y1), (x2, y2)],
                fill=fill_color
            )
            image = Image.alpha_composite(image, overlay)

        # 绘制标签
        if label:
            font = self._get_font(self.style.label_font_size)

            # 计算文字大小
            text_bbox = draw.textbbox((0, 0), label, font=font)
            text_width = text_bbox[2] - text_bbox[0]
            text_height = text_bbox[3] - text_bbox[1]

            padding = self.style.label_padding

            # 标签背景位置（在边界框上方）
            label_x = x1
            label_y = max(0, y1 - text_height - padding * 2 - 2)

            # 绘制标签背景
            bg_color = self._parse_color(self.style.label_bg_color)
            draw.rectangle(
                [
                    (label_x, label_y),
                    (label_x + text_width + padding * 2, label_y + text_height + padding * 2)
                ],
                fill=bg_color[:3]
            )

            # 绘制标签文字
            text_color = self._parse_color(self.style.label_color)
            draw.text(
                (label_x + padding, label_y + padding),
                label,
                fill=text_color[:3],
                font=font
            )

        return self._image_to_base64(image)

    def draw_click_point(
        self,
        image_base64: str,
        point: Tuple[int, int],
        color: Optional[str] = None,
        radius: Optional[int] = None
    ) -> str:
        """
        在截图上绘制点击位置标记

        Args:
            image_base64: 原始截图的 base64 字符串
            point: 点击位置坐标 (x, y)
            color: 标记颜色
            radius: 标记半径

        Returns:
            带标记的截图 base64 字符串
        """
        if not HAS_PIL:
            return image_base64

        image = self._base64_to_image(image_base64)
        if image is None:
            return image_base64

        draw = ImageDraw.Draw(image, 'RGBA')

        x, y = point
        click_color = self._parse_color(color or self.style.click_color)
        r = radius or self.style.click_radius
        cross_size = self.style.click_cross_size

        # 绘制圆形
        draw.ellipse(
            [(x - r, y - r), (x + r, y + r)],
            outline=click_color[:3],
            width=3
        )

        # 绘制十字
        draw.line([(x - cross_size, y), (x + cross_size, y)], fill=click_color[:3], width=2)
        draw.line([(x, y - cross_size), (x, y + cross_size)], fill=click_color[:3], width=2)

        # 绘制中心点
        draw.ellipse(
            [(x - 3, y - 3), (x + 3, y + 3)],
            fill=click_color[:3]
        )

        return self._image_to_base64(image)

    def draw_action_sequence(
        self,
        image_base64: str,
        actions: List[ActionMarker]
    ) -> str:
        """
        在截图上绘制操作序列轨迹

        Args:
            image_base64: 原始截图的 base64 字符串
            actions: 操作标记列表

        Returns:
            带标记的截图 base64 字符串
        """
        if not HAS_PIL or not actions:
            return image_base64

        image = self._base64_to_image(image_base64)
        if image is None:
            return image_base64

        draw = ImageDraw.Draw(image, 'RGBA')

        # 绘制连接线
        if len(actions) > 1:
            points = [action.point for action in actions]
            for i in range(len(points) - 1):
                draw.line(
                    [points[i], points[i + 1]],
                    fill=(100, 100, 100, 128),
                    width=2
                )

        # 绘制每个操作点
        for i, action in enumerate(actions):
            x, y = action.point

            # 根据操作类型选择颜色
            if action.action_type == 'click':
                color = self.style.click_color
            elif action.action_type == 'input':
                color = "#FFA500"  # 橙色
            elif action.action_type == 'scroll':
                color = "#0066FF"  # 蓝色
            else:
                color = "#888888"  # 灰色

            parsed_color = self._parse_color(color)

            # 绘制操作点
            r = 8
            draw.ellipse(
                [(x - r, y - r), (x + r, y + r)],
                fill=parsed_color[:3],
                outline=(255, 255, 255),
                width=2
            )

            # 绘制序号
            index = action.index if action.index is not None else i + 1
            font = self._get_font(10)
            index_text = str(index)

            # 序号背景圆
            idx_r = self.style.index_radius
            idx_x = x + r + 5
            idx_y = y - r - 5

            idx_bg_color = self._parse_color(self.style.index_bg_color)
            draw.ellipse(
                [(idx_x - idx_r, idx_y - idx_r), (idx_x + idx_r, idx_y + idx_r)],
                fill=idx_bg_color[:3]
            )

            # 序号文字
            text_bbox = draw.textbbox((0, 0), index_text, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]

            idx_color = self._parse_color(self.style.index_color)
            draw.text(
                (idx_x - text_w // 2, idx_y - text_h // 2),
                index_text,
                fill=idx_color[:3],
                font=font
            )

        return self._image_to_base64(image)

    def draw_element_with_click(
        self,
        image_base64: str,
        bbox: Tuple[int, int, int, int],
        click_point: Tuple[int, int],
        label: Optional[str] = None
    ) -> str:
        """
        同时绘制元素边界框和点击位置

        Args:
            image_base64: 原始截图的 base64 字符串
            bbox: 边界框坐标
            click_point: 点击位置坐标
            label: 标签文字

        Returns:
            带标记的截图 base64 字符串
        """
        # 先绘制边界框
        result = self.draw_bbox(image_base64, bbox, label=label)
        # 再绘制点击位置
        result = self.draw_click_point(result, click_point)
        return result

    def draw_multiple_elements(
        self,
        image_base64: str,
        elements: List[dict]
    ) -> str:
        """
        绘制多个元素标记

        Args:
            image_base64: 原始截图的 base64 字符串
            elements: 元素列表，每个元素包含 bbox, label, index 等

        Returns:
            带标记的截图 base64 字符串
        """
        if not HAS_PIL or not elements:
            return image_base64

        image = self._base64_to_image(image_base64)
        if image is None:
            return image_base64

        draw = ImageDraw.Draw(image, 'RGBA')

        # 颜色列表用于区分不同元素
        colors = [
            "#FF0000", "#00FF00", "#0066FF", "#FFA500",
            "#FF00FF", "#00FFFF", "#FFFF00", "#FF6666"
        ]

        for i, element in enumerate(elements):
            bbox = element.get('bbox')
            if not bbox:
                continue

            color = colors[i % len(colors)]
            label = element.get('label', f"Element {i + 1}")

            # 绘制边界框
            x1, y1, x2, y2 = bbox
            parsed_color = self._parse_color(color)

            draw.rectangle(
                [(x1, y1), (x2, y2)],
                outline=parsed_color[:3],
                width=self.style.bbox_width
            )

            # 绘制序号标记
            font = self._get_font(12)
            index_text = str(i + 1)

            idx_r = self.style.index_radius
            idx_x = x1 + idx_r
            idx_y = y1 + idx_r

            draw.ellipse(
                [(idx_x - idx_r, idx_y - idx_r), (idx_x + idx_r, idx_y + idx_r)],
                fill=parsed_color[:3]
            )

            text_bbox = draw.textbbox((0, 0), index_text, font=font)
            text_w = text_bbox[2] - text_bbox[0]
            text_h = text_bbox[3] - text_bbox[1]

            idx_color = self._parse_color(self.style.index_color)
            draw.text(
                (idx_x - text_w // 2, idx_y - text_h // 2),
                index_text,
                fill=idx_color[:3],
                font=font
            )

        return self._image_to_base64(image)


# 默认实例
_default_marker: Optional[ElementMarker] = None


def get_default_marker() -> ElementMarker:
    """获取默认的元素标记器实例"""
    global _default_marker
    if _default_marker is None:
        _default_marker = ElementMarker()
    return _default_marker


__all__ = [
    "ElementMarker",
    "MarkerStyle",
    "ActionMarker",
    "get_default_marker",
]
