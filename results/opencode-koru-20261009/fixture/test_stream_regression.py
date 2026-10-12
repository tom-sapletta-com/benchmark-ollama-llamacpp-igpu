"""Withheld behavior checks for refactoring; intentionally preserve existing semantics."""
import json
import time
from pathlib import Path
from types import SimpleNamespace

from koruapi import dashboard_logs as logs


def event(message, level='INFO'):
    return json.dumps({'timestamp': 't', 'level': level, 'kwargs': {'activity_message': message}}) + '\n'


def data(chunk):
    return json.loads(chunk.removeprefix('data: ').strip())


def paths(project):
    directory = project / '.planfile' / '.koru'
    directory.mkdir(parents=True)
    return directory / 'nfo-events.jsonl', directory / 'autonomous.log'


def test_empty_levels_is_not_default(tmp_path):
    nfo, _ = paths(tmp_path); nfo.write_text(event('not visible'))
    stream = logs.sse_log_stream(tmp_path, levels=set())
    assert next(stream) == ': keepalive\n\n'
    stream.close()


def test_existing_history_order_and_limit_semantics(tmp_path):
    nfo, _ = paths(tmp_path); nfo.write_text(event('first') + event('second'))
    # Existing behavior sends all recent history before checking max_events.
    assert [data(c)['message'] for c in logs.sse_log_stream(tmp_path, max_events=1)] == ['first', 'second']


def test_already_set_stop_event(tmp_path):
    assert list(logs.sse_log_stream(tmp_path, stop_event=SimpleNamespace(is_set=lambda: True))) == []


def test_stop_after_keepalive(tmp_path, monkeypatch):
    stopped = [False]; monkeypatch.setattr(time, 'sleep', lambda _: None)
    stream = logs.sse_log_stream(tmp_path, stop_event=SimpleNamespace(is_set=lambda: stopped[0]))
    assert next(stream) == ': keepalive\n\n'; stopped[0] = True
    assert list(stream) == []


def test_tail_both_sources_and_unicode(tmp_path, monkeypatch):
    nfo, auto = paths(tmp_path); monkeypatch.setattr(time, 'sleep', lambda _: None)
    stream = logs.sse_log_stream(tmp_path, max_events=2)
    assert next(stream) == ': keepalive\n\n'
    nfo.write_text(event('Zażółć 🌍')); auto.write_text('[ERROR] awaria\n')
    assert data(next(stream))['message'] == 'Zażółć 🌍'
    assert data(next(stream))['message'] == '[ERROR] awaria'
    assert next(stream) == ': keepalive\n\n'
    assert list(stream) == []


def test_rotation_resets_offset(tmp_path, monkeypatch):
    nfo, _ = paths(tmp_path); nfo.write_text('not JSON ' * 200 + '\n')
    monkeypatch.setattr(time, 'sleep', lambda _: None)
    stream = logs.sse_log_stream(tmp_path, max_events=1)
    assert next(stream) == ': keepalive\n\n'
    nfo.write_text(event('rotated'))
    assert data(next(stream))['message'] == 'rotated'
    stream.close()


def test_new_file_and_level_filter(tmp_path, monkeypatch):
    monkeypatch.setattr(time, 'sleep', lambda _: None)
    stream = logs.sse_log_stream(tmp_path, levels={'ERROR'}, max_events=1)
    assert next(stream) == ': keepalive\n\n'
    nfo, _ = paths(tmp_path); nfo.write_text(event('ignored') + event('visible', 'ERROR'))
    assert data(next(stream))['message'] == 'visible'; stream.close()


def test_unreadable_logs_are_ignored(tmp_path):
    nfo, auto = paths(tmp_path); nfo.mkdir(); auto.mkdir()
    stream = logs.sse_log_stream(tmp_path)
    assert next(stream) == ': keepalive\n\n'; stream.close()
