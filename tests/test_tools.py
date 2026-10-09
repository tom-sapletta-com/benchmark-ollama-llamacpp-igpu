import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import native_stream


def test_final_harmony_channel():
    raw = '<|channel|>analysis<|message|>Think.<|end|><|start|>assistant<|channel|>final<|message|>```python\nx = 42\n```<|return|>'
    answer, thinking = native_stream.split_answer(raw)
    assert answer == '```python\nx = 42\n```'
    assert 'Think.' in thinking


def test_partial_harmony_is_not_an_answer():
    for raw in ['<|channel|>analysis<|message|>thinking', '<|channel|>final', '<|channel|>final<|mess']:
        assert native_stream.split_answer(raw)[0] == ''


def test_plain_ollama_response():
    assert native_stream.split_answer('42', 'thinking') == ('42', 'thinking')


def test_archive_validation():
    spec = importlib.util.spec_from_file_location('verify_results', ROOT / 'tools/verify_results.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.verify()
    assert result['coding_passed'] == 72 and result['long_input_passed'] == 12
