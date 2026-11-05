# -*- coding: utf-8 -*-
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
import django
django.setup()

from apps.requirement_analysis.modao_extractor import ModaoExtractor

def test_single_session_capture():
    extractor = ModaoExtractor(run_id='test_session_001')
    assert hasattr(extractor, '_capture_singlefile_h5_session'), "ModaoExtractor missing _capture_singlefile_h5_session"
    print("✓ test_single_session_capture passed!")

if __name__ == '__main__':
    test_single_session_capture()
