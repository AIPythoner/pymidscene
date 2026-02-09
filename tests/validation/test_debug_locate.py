"""
调试定位测试 - 在截图上标出红色框，查看 AI 定位是否正确

运行方式：python tests/validation/test_debug_locate.py
"""

import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv()


async def debug_locate():
    """调试 AI 定位，在截图上标出红色框"""
    print("=" * 60)
    print("PyMidscene 定位调试测试")
    print("=" * 60)
    
    from playwright.async_api import async_playwright
    from pymidscene import PlaywrightAgent
    from pymidscene.core.element_marker import ElementMarker, MarkerStyle
    import base64
    
    # 检查配置
    if not os.getenv("MIDSCENE_MODEL_API_KEY"):
        print("请先配置环境变量！")
        return
    
    # 创建输出目录
    output_dir = Path(__file__).parent / "debug_output"
    output_dir.mkdir(exist_ok=True)
    
    # 初始化标记器（红色边框）
    marker = ElementMarker(MarkerStyle(
        bbox_color="#FF0000",  # 红色边框
        bbox_width=4,
        click_color="#00FF00",  # 绿色点击点
        click_radius=20,
    ))
    
    test_page = Path(__file__).parent / "test_automation.html"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        # 加载测试页面
        print("\n1. 加载测试页面...")
        await page.goto(f"file://{test_page.absolute()}")
        await asyncio.sleep(1)
        
        # 创建 Agent（禁用报告记录，避免干扰）
        agent = PlaywrightAgent(page, enable_recording=False)
        
        # 要测试的元素列表
        test_cases = [
            "用户名输入框",
            "密码输入框", 
            "搜索框",
            "搜索按钮",
            "主要按钮",
            "危险按钮",
            "成功按钮",
        ]
        
        print("\n2. 开始定位测试...")
        print("-" * 60)
        
        for i, description in enumerate(test_cases):
            print(f"\n[{i+1}/{len(test_cases)}] 定位: '{description}'")
            
            # 获取截图（定位前）
            screenshot_b64 = await page.screenshot(type="png")
            screenshot_b64_str = base64.b64encode(screenshot_b64).decode('utf-8')
            
            try:
                # 调用 AI 定位
                result = await agent._agent.ai_locate(description)
                
                if result:
                    # 获取定位结果
                    center = result.center
                    rect = result.rect
                    
                    # 计算 bbox (x1, y1, x2, y2)
                    x1 = int(rect['left'])
                    y1 = int(rect['top'])
                    x2 = int(rect['left'] + rect['width'])
                    y2 = int(rect['top'] + rect['height'])
                    bbox = (x1, y1, x2, y2)
                    
                    # 点击点
                    click_point = (int(center[0]), int(center[1]))
                    
                    print(f"   定位成功!")
                    print(f"   - 边界框: {bbox}")
                    print(f"   - 中心点: {click_point}")
                    print(f"   - 矩形: left={rect['left']}, top={rect['top']}, w={rect['width']}, h={rect['height']}")
                    
                    # 在截图上绘制红色边框和绿色点击点
                    marked_image = marker.draw_element_with_click(
                        screenshot_b64_str,
                        bbox,
                        click_point,
                        label=description
                    )
                    
                    # 保存标记后的截图
                    timestamp = datetime.now().strftime("%H%M%S")
                    filename = f"{i+1:02d}_{description.replace(' ', '_')}_{timestamp}.png"
                    filepath = output_dir / filename
                    
                    with open(filepath, "wb") as f:
                        f.write(base64.b64decode(marked_image))
                    
                    print(f"   截图已保存: {filepath}")
                    
                else:
                    print(f"   定位失败: 未找到元素")
                    
                    # 保存原始截图
                    timestamp = datetime.now().strftime("%H%M%S")
                    filename = f"{i+1:02d}_{description.replace(' ', '_')}_FAILED_{timestamp}.png"
                    filepath = output_dir / filename
                    
                    with open(filepath, "wb") as f:
                        f.write(screenshot_b64)
                    
                    print(f"   原始截图已保存: {filepath}")
                    
            except Exception as e:
                print(f"   错误: {e}")
                import traceback
                traceback.print_exc()
            
            # 短暂等待
            await asyncio.sleep(0.5)
        
        print("\n" + "=" * 60)
        print(f"测试完成！截图保存在: {output_dir}")
        print("=" * 60)
        
        # 等待查看
        print("\n10 秒后关闭浏览器...")
        await asyncio.sleep(10)
        
        await browser.close()


async def debug_single_locate(description: str = "用户名输入框"):
    """调试单个元素的定位"""
    print(f"调试定位: '{description}'")
    
    from playwright.async_api import async_playwright
    from pymidscene import PlaywrightAgent
    from pymidscene.core.element_marker import ElementMarker
    import base64
    
    output_dir = Path(__file__).parent / "debug_output"
    output_dir.mkdir(exist_ok=True)
    
    marker = ElementMarker()
    test_page = Path(__file__).parent / "test_automation.html"
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, channel="chrome")
        page = await browser.new_page(viewport={"width": 1280, "height": 900})
        
        await page.goto(f"file://{test_page.absolute()}")
        await asyncio.sleep(1)
        
        agent = PlaywrightAgent(page, enable_recording=False)
        
        # 获取截图
        screenshot_b64 = await page.screenshot(type="png")
        screenshot_b64_str = base64.b64encode(screenshot_b64).decode('utf-8')
        
        # 获取页面尺寸
        size = await page.evaluate("() => ({ width: window.innerWidth, height: window.innerHeight })")
        print(f"页面尺寸: {size['width']} x {size['height']}")
        
        # 获取模型配置
        config = agent._agent._get_model_config("default")
        print(f"模型: {config.model_name}")
        print(f"模型家族: {config.model_family}")
        print(f"Base URL: {config.openai_base_url}")
        
        # 执行定位
        print(f"\n开始定位 '{description}'...")
        result = await agent._agent.ai_locate(description)
        
        if result:
            center = result.center
            rect = result.rect
            
            x1 = int(rect['left'])
            y1 = int(rect['top'])
            x2 = int(rect['left'] + rect['width'])
            y2 = int(rect['top'] + rect['height'])
            bbox = (x1, y1, x2, y2)
            click_point = (int(center[0]), int(center[1]))
            
            print(f"\n定位结果:")
            print(f"  - bbox: {bbox}")
            print(f"  - center: {click_point}")
            print(f"  - rect: {rect}")
            
            # 绘制标记
            marked_image = marker.draw_element_with_click(
                screenshot_b64_str,
                bbox,
                click_point,
                label=description
            )
            
            # 保存
            filepath = output_dir / f"debug_{description.replace(' ', '_')}.png"
            with open(filepath, "wb") as f:
                f.write(base64.b64decode(marked_image))
            
            print(f"\n截图已保存: {filepath}")
            
        else:
            print("定位失败!")
        
        print("\n按 Ctrl+C 关闭...")
        try:
            await asyncio.sleep(300)
        except:
            pass
        
        await browser.close()


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="调试 AI 定位")
    parser.add_argument("--element", "-e", type=str, default=None,
                       help="要定位的单个元素描述")
    
    args = parser.parse_args()
    
    if args.element:
        asyncio.run(debug_single_locate(args.element))
    else:
        asyncio.run(debug_locate())
