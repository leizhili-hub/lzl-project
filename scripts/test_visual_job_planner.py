# -*- coding: utf-8 -*-
import os, sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django; django.setup()

from apps.requirement_analysis.modao_extractor import ModaoExtractor

def test_visual_job_planner():
    extractor = ModaoExtractor(run_id='test_plan_001')
    assert hasattr(extractor, '_plan_visual_jobs'), "Missing _plan_visual_jobs"
    assert hasattr(extractor, '_is_image_file_different'), "Missing _is_image_file_different"

    # 模拟 shot_manifest
    fake_manifest = {
        1: {
            'default_shot': 'non_existent_1.png',
            'state_shots': [{'state': 'st1', 'shot_path': 'non_existent_st1.png'}]
        }
    }
    jobs = extractor._plan_visual_jobs(fake_manifest)
    assert isinstance(jobs, list), "Expected list of jobs"
    print("✓ test_visual_job_planner passed!")

if __name__ == '__main__':
    test_visual_job_planner()
