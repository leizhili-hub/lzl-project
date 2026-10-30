# -*- coding: utf-8 -*-
import os, sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django; django.setup()

from apps.requirement_analysis.modao_extractor import ModaoExtractor

def test_integration_methods():
    extractor = ModaoExtractor(run_id='test_integ_001')
    assert hasattr(extractor, '_capture_singlefile_h5_session')
    assert hasattr(extractor, '_plan_visual_jobs')
    assert hasattr(extractor, '_execute_visual_jobs_pool')
    assert hasattr(extractor, '_extract_singlefile_h5')
    print("✓ test_integration_methods passed!")

if __name__ == '__main__':
    test_integration_methods()
