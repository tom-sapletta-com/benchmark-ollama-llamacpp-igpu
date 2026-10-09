import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from render_opencode_report import summarize
from verify_opencode import verify


def test_missing_usage_is_not_invented():
    report={'settings':{'models':['local']},'results':[{'model':'local','passed':False,'wall_seconds':2,
        'memory_samples':[{'mem_info_vram_used':2**30,'mem_info_gtt_used':0,'gpu_busy_percent':50}],
        'api_calls':[{'response':'data: [DONE]\n'}],'events':[]}]}
    assert summarize(report)[0]['peak_vram_gib']==1
    assert report['results'][0]['derived']['completion_tokens'] is None


def test_real_task_evidence():
    result=verify()
    assert result['trials']==2 and result['withheld_tests']==8


def test_summary_uses_saved_data():
    report=json.loads((ROOT/'results/opencode-koru-20261009/results.json').read_text())
    expected=copy.deepcopy(report['summary'])
    assert summarize(report)==expected
