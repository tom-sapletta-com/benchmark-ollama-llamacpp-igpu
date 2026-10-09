"""Check benchmark assertions against independently written reference solutions."""
import json
from pathlib import Path
import pytest

TASKS = json.loads((Path(__file__).parents[1] / 'allama/benchmark_tasks.json').read_text())
REFERENCES = {
'unique_ordered': '''
def unique_ordered(items):
    result = []
    for item in items:
        if item not in result:
            result.append(item)
    return result
''',
'merge_intervals': '''
def merge_intervals(intervals):
    out = []
    for start, end in sorted(intervals):
        if start > end:
            raise ValueError()
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return out
''',
'csv_totals': '''
import csv, io
from decimal import Decimal, InvalidOperation
def csv_totals(text):
    result = {}
    for row in csv.DictReader(io.StringIO(text)):
        try:
            amount = Decimal(row['amount'])
        except (InvalidOperation, TypeError):
            raise ValueError()
        k = row['category']
        result[k] = result.get(k, Decimal(0)) + amount
    return result
''',
 'topological_sort': '''
import heapq
def topo_sort(graph):
    degree = {v:0 for v in set(graph).union(*(set(vs) for vs in graph.values()))}
    for vs in graph.values():
        for v in vs:
            degree[v] += 1
    ready = [v for v in degree if degree[v] == 0]
    heapq.heapify(ready)
    out = []
    while ready:
        u = heapq.heappop(ready)
        out.append(u)
        for v in graph.get(u, []):
            degree[v] -= 1
            if degree[v] == 0:
                heapq.heappush(ready, v)
    if len(out) != len(degree):
        raise ValueError()
    return out
''',
'deep_merge': '''
from copy import deepcopy
def deep_merge(a, b):
    result = deepcopy(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = deepcopy(v)
    return result
''',
'lru_cache': '''
from collections import OrderedDict
class LRUCache:
    def __init__(self, capacity):
        if capacity < 0:
            raise ValueError()
        self.capacity = capacity
        self.items = OrderedDict()
    def get(self, key):
        if key not in self.items:
            return -1
        self.items.move_to_end(key)
        return self.items[key]
    def put(self, key, value):
        self.items[key] = value
        self.items.move_to_end(key)
        if len(self.items) > self.capacity:
            self.items.popitem(last=False)
'''
}

@pytest.mark.parametrize('task', TASKS, ids=lambda t:t['id'])
def test_reference_satisfies_contract(task):
    scope = {}
    exec(REFERENCES[task['id']], scope)
    exec(task['tests'], scope)
