# -*- coding: utf-8 -*-
import os, sys, asyncio
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django; django.setup()

from apps.requirement_analysis.modao_extractor import ModaoExtractor

def test_visual_pool_execution():
    extractor = ModaoExtractor(run_id='test_pool_001')
    assert hasattr(extractor, '_execute_visual_jobs_pool'), "Missing _execute_visual_jobs_pool"

    # 测试空 jobs 返回空字典
    res = asyncio.run(extractor._execute_visual_jobs_pool([], vision_config=None))
    assert isinstance(res, dict), "Expected dict output"
    print("✓ test_visual_pool_execution passed!")

if __name__ == '__main__':
    test_visual_pool_execution()
