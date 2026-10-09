"""Render measured OpenCode trial data; no model calls or candidate execution."""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]


def summarize(report):
    summaries = []
    for model in report['settings']['models']:
        rows = [row for row in report['results'] if row['model'] == model]
        summaries.append({'model': model, 'trials': len(rows), 'passed': sum(row['passed'] for row in rows),
                          'median_seconds': statistics.median(row['wall_seconds'] for row in rows) if rows else None,
                          'peak_vram_gib': max((sample['mem_info_vram_used']/2**30 for row in rows for sample in row['memory_samples']), default=0),
                          'peak_gtt_gib': max((sample['mem_info_gtt_used']/2**30 for row in rows for sample in row['memory_samples']), default=0)})
    for row in report['results']:
        usage, finish_reasons = [], []
        for call in row['api_calls']:
            for line in call['response'].splitlines():
                if line.startswith('data: ') and line != 'data: [DONE]':
                    chunk = json.loads(line[6:])
                    if chunk.get('usage'): usage.append(chunk['usage'])
                    finish_reasons.extend(choice['finish_reason'] for choice in chunk.get('choices', []) if choice.get('finish_reason'))
        tools = [event['part'] for event in row['events'] if event.get('type') == 'tool_use']
        row['derived'] = {'api_calls': len(row['api_calls']), 'tool_calls': len(tools),
                          'tool_errors': sum(tool.get('state', {}).get('status') == 'error' for tool in tools),
                          'tools': dict(Counter(tool.get('tool') for tool in tools)),
                          'prompt_tokens': sum(value.get('prompt_tokens', 0) for value in usage) if usage else None,
                          'completion_tokens': sum(value.get('completion_tokens', 0) for value in usage) if usage else None,
                          'usage_records': len(usage),
                          'usage_complete': len(usage) == len(row['api_calls']),
                          'finish_reasons': finish_reasons,
                          'output_limit_hits': finish_reasons.count('length'),
                          'peak_vram_gib': max((s['mem_info_vram_used']/2**30 for s in row['memory_samples']), default=0),
                          'peak_gtt_gib': max((s['mem_info_gtt_used']/2**30 for s in row['memory_samples']), default=0),
                          'gpu_busy_mean_percent': statistics.mean(s['gpu_busy_percent'] for s in row['memory_samples']) if row['memory_samples'] else None}
    return summaries


def render(directory):
    from jinja2 import Environment, FileSystemLoader
    report = json.loads((directory/'results.json').read_text())
    report['summary'] = summarize(report)
    (directory/'results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    env = Environment(loader=FileSystemLoader(ROOT/'templates'), autoescape=True)
    (directory/'index.html').write_text(env.get_template('opencode.html').render(report=report))
    return report['summary']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    print(json.dumps(render(args.directory), indent=2))
