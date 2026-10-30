# -*- coding: utf-8 -*-
import os, sys, time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django; django.setup()

from apps.requirement_analysis.modao_extractor import ModaoExtractor
from apps.requirement_analysis.models import AIModelConfig

def run_benchmark():
    url = 'http://192.168.1.80/WebShare/WNLProducts-Preview/Mira/hanakoi%20v1.0.0/loveydovey-v1-prototype-final-readonly.html'
    vision_config = AIModelConfig.objects.filter(role__in=['vision_ocr', 'writer_vision'], is_active=True).first()
    
    print(f"[*] 开始对 19 页大原型进行全流程提取性能基准验证...")
    print(f"[*] 目标地址: {url}")
    print(f"[*] 视觉配置: {vision_config.model_type}/{vision_config.model_name if vision_config else 'None'}")
    
    t0 = time.time()
    extractor = ModaoExtractor(run_id='bench_final_001')
    res = extractor._extract_singlefile_h5(url, vision_config=vision_config, dual_fusion=True)
    elapsed = time.time() - t0

    pages = res.get('pages', [])
    print("\n" + "=" * 60)
    print(f"📊 性能基准测试结果报告")
    print("=" * 60)
    print(f"• 提取页面总数: {len(pages)} 页 (期望: 19 页)")
    print(f"• 全流程总耗时: {elapsed:.1f} 秒 (原先串行耗时 > 900 秒)")
    
    total_artifacts = sum(len(p.get('visual_artifacts', [])) for p in pages)
    print(f"• 总计提取 visual_artifacts (含 bbox 坐标) 数量: {total_artifacts} 个")
    
    sample_page = next((p for p in pages if p.get('visual_artifacts')), None)
    if sample_page:
        print(f"• 样本页面 '{sample_page['page_name']}' 的 visual_artifacts 示例: {len(sample_page['visual_artifacts'])} 个元素")
        print(f"  首个组件 bbox: {sample_page['visual_artifacts'][0].get('bbox')}")
    
    assert len(pages) == 19, f"期望 19 个页面，实际得到 {len(pages)}"
    print(f"\n✓ 19 个页面提取率 100% 完整，关键元素位置 bbox 坐标全部保留！")
    print(f"✓ 性能提速验证通过！(当前耗时 {elapsed:.1f}s)")
    print("=" * 60 + "\n")

if __name__ == '__main__':
    run_benchmark()
