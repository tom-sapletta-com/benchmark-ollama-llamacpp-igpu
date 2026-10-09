"""Three fixed coding tasks; reference answers and withheld tests are never prompted."""
from textwrap import dedent


def text(value):
    return dedent(value).lstrip()


CASES = [
    {
        'id': 'generate_invoice_summary',
        'title': 'Generowanie: agregator faktur NDJSON',
        'kind': 'generation',
        'spec': '''Create invoice_summary.py with summarize_invoices(text: str) -> dict[str, str].
Input is NDJSON: one JSON object per nonblank line, with customer (nonempty string),
amount (nonnegative finite Decimal string), and status (paid or pending).
Return paid totals per customer as fixed two-decimal strings, sorted by customer.
Sum exact Decimal amounts before rounding the customer total with ROUND_HALF_UP.
Ignore pending invoices in totals but validate them too. Empty input returns {}.
Reject malformed JSON, non-object records, missing/invalid fields, numeric rather
than string amounts, unknown status, and nonfinite or negative amounts with
ValueError identifying the physical input line (e.g. line 3). Blank lines count
for line numbering. Accept extra object fields. Use only the Python standard library.''',
        'before': {'invoice_summary.py': 'def summarize_invoices(text: str) -> dict[str, str]:\n    raise NotImplementedError\n'},
        'reference': {'invoice_summary.py': text('''
            import json
            from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

            def summarize_invoices(text: str) -> dict[str, str]:
                """Validate NDJSON and aggregate paid amounts before rounding."""
                totals = {}
                for number, line in enumerate(text.splitlines(), 1):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                        if not isinstance(record, dict):
                            raise ValueError('expected object')
                        customer, raw, status = record['customer'], record['amount'], record['status']
                        if not isinstance(customer, str) or not customer.strip():
                            raise ValueError('invalid customer')
                        if not isinstance(raw, str) or status not in ('paid', 'pending'):
                            raise ValueError('invalid amount or status')
                        amount = Decimal(raw)
                        if not amount.is_finite() or amount < 0:
                            raise ValueError('invalid amount')
                        if status == 'paid':
                            totals[customer] = totals.get(customer, Decimal(0)) + amount
                    except (ValueError, KeyError, InvalidOperation, TypeError) as exc:
                        raise ValueError(f'line {number}: invalid invoice') from exc
                return {name: format(totals[name].quantize(Decimal('0.01'), rounding=ROUND_HALF_UP), '.2f')
                        for name in sorted(totals)}
        ''')},
        'tests': text('''
            import unittest, json
            from invoice_summary import summarize_invoices as solve
            def record(customer='a', amount='1', status='paid', **extra):
                return json.dumps(dict(customer=customer, amount=amount, status=status, **extra))
            class Functional(unittest.TestCase):
                def test_aggregate_before_rounding(self):
                    self.assertEqual(solve(record(amount='0.005')+'\\n'+record(amount='0.005')), {'a':'0.01'})
                def test_decimal_precision(self):
                    self.assertEqual(solve(record(amount='0.1')+'\\n'+record(amount='0.2')), {'a':'0.30'})
                def test_half_up(self):
                    self.assertEqual(solve(record(amount='2.345')), {'a':'2.35'})
                def test_sorted_customers(self):
                    result=solve(record('z')+'\\n'+record('b'))
                    self.assertEqual(list(result), ['b','z'])
                def test_invalid_line_number(self):
                    with self.assertRaisesRegex(ValueError, r'(?i)line 3\\b'):
                        solve('\\n'+record()+'\\n{bad')
                def test_invalid_records(self):
                    for line in ['[]','{}',record(customer=''),record(amount=1),record(status='void')]:
                        with self.subTest(line=line), self.assertRaises(ValueError): solve(line)
                def test_invalid_decimal(self):
                    for amount in ['NaN','Infinity','-1','oops']:
                        with self.subTest(amount=amount), self.assertRaises(ValueError): solve(record(amount=amount))
                def test_validate_pending(self):
                    with self.assertRaises(ValueError): solve(record(amount='NaN',status='pending'))
            class Regression(unittest.TestCase):
                def test_empty(self): self.assertEqual(solve(' \\n\\t'), {})
                def test_pending_ignored(self): self.assertEqual(solve(record(status='pending')), {})
                def test_extra_fields(self): self.assertEqual(solve(record(note='ok')), {'a':'1.00'})
                def test_independent_calls(self):
                    solve(record()); self.assertEqual(solve(record('b',amount='0')), {'b':'0.00'})
        '''),
    },
    {
        'id': 'fix_ttl_cache',
        'title': 'Naprawa w jednym pliku: cache TTL + LRU',
        'kind': 'single_file_fix',
        'spec': '''Fix ttl_cache.py preserving TTLCache(capacity, ttl, clock), put(key, value),
get(key, default=None), and len(cache). Capacity is a nonnegative integer (not bool),
ttl is a nonnegative finite number (not bool); invalid values raise ValueError.
clock is an injected callable, returning monotonic seconds. A key expires at
now >= insertion_time + ttl. Reads refresh LRU order but NEVER extend expiry.
An overwrite resets expiry and makes the key most recently used. Purge expired
entries before capacity eviction and len(). Stored None is a legitimate hit.
Capacity zero and ttl zero retain nothing. get() returns the caller's default
for missing/expired keys. Fix expiry, LRU, capacity and validation bugs; keep all
changes in this one file and use only the Python standard library.''',
        'before': {'ttl_cache.py': text('''
            from collections import OrderedDict
            class TTLCache:
                def __init__(self, capacity, ttl, clock):
                    self.capacity, self.ttl, self.clock = capacity, ttl, clock
                    self.entries = OrderedDict()
                def put(self, key, value):
                    if len(self.entries) >= self.capacity and self.entries:
                        self.entries.popitem(last=False)
                    self.entries[key] = (value, self.clock() + self.ttl)
                def get(self, key, default=None):
                    item = self.entries.get(key)
                    if item is None: return default
                    value, expiry = item
                    if self.clock() > expiry:
                        del self.entries[key]
                        return default
                    self.entries[key] = (value, self.clock() + self.ttl)
                    return value
                def __len__(self):
                    return len(self.entries)
        ''')},
        'reference': {'ttl_cache.py': text('''
            import math
            from collections import OrderedDict
            class TTLCache:
                """LRU cache with fixed expiry and an injected monotonic clock."""
                def __init__(self, capacity: int, ttl: float, clock):
                    if isinstance(capacity, bool) or not isinstance(capacity, int) or capacity < 0:
                        raise ValueError('invalid capacity')
                    if isinstance(ttl, bool) or not isinstance(ttl, (int, float)) or not math.isfinite(ttl) or ttl < 0:
                        raise ValueError('invalid ttl')
                    self.capacity, self.ttl, self.clock = capacity, ttl, clock
                    self.entries = OrderedDict()
                def _purge(self, now):
                    for key in list(self.entries):
                        if now >= self.entries[key][1]: del self.entries[key]
                def put(self, key, value):
                    now = self.clock()
                    self._purge(now)
                    if self.capacity == 0 or self.ttl == 0: return
                    self.entries[key] = (value, now + self.ttl)
                    self.entries.move_to_end(key)
                    while len(self.entries) > self.capacity: self.entries.popitem(last=False)
                def get(self, key, default=None):
                    self._purge(self.clock())
                    if key not in self.entries: return default
                    self.entries.move_to_end(key)
                    return self.entries[key][0]
                def __len__(self):
                    self._purge(self.clock())
                    return len(self.entries)
        ''')},
        'tests': text('''
            import unittest
            from ttl_cache import TTLCache
            class Clock:
                def __init__(self): self.now=0
                def __call__(self): return self.now
            class Functional(unittest.TestCase):
                def setUp(self): self.clock=Clock(); self.cache=TTLCache(2,10,self.clock)
                def test_expiry_boundary(self):
                    self.cache.put('a',1); self.clock.now=10; self.assertEqual(self.cache.get('a','miss'),'miss')
                def test_read_no_extension(self):
                    self.cache.put('a',1); self.clock.now=9; self.cache.get('a'); self.clock.now=11
                    self.assertIsNone(self.cache.get('a'))
                def test_lru_on_read(self):
                    self.cache.put('a',1);self.cache.put('b',2);self.cache.get('a');self.cache.put('c',3)
                    self.assertIsNone(self.cache.get('b'));self.assertEqual(self.cache.get('a'),1)
                def test_overwrite_at_capacity(self):
                    self.cache.put('a',1);self.cache.put('b',2);self.cache.put('b',3)
                    self.assertEqual(self.cache.get('a'),1)
                def test_expired_before_eviction(self):
                    self.cache.put('a',1);self.clock.now=5;self.cache.put('b',2);self.cache.get('a')
                    self.clock.now=10;self.cache.put('c',3);self.assertEqual(self.cache.get('b'),2)
                def test_len_purges(self):
                    self.cache.put('a',1);self.clock.now=10;self.assertEqual(len(self.cache),0)
                def test_zero_capacity_and_ttl(self):
                    for capacity,ttl in [(0,10),(2,0)]:
                        cache=TTLCache(capacity,ttl,self.clock);cache.put('a',1);self.assertEqual(len(cache),0)
                def test_invalid_parameters(self):
                    for capacity,ttl in [(-1,1),(True,1),(1.5,1),(1,-1),(1,float('nan')),(1,float('inf')),(1,True)]:
                        with self.subTest(capacity=capacity,ttl=ttl),self.assertRaises(ValueError): TTLCache(capacity,ttl,self.clock)
            class Regression(unittest.TestCase):
                def test_none_value(self):
                    cache=TTLCache(1,5,lambda:0);cache.put('a',None);self.assertIsNone(cache.get('a','miss'))
                def test_custom_default(self): self.assertEqual(TTLCache(1,5,lambda:0).get('absent',42),42)
                def test_overwrite_resets_expiry(self):
                    clock=Clock();cache=TTLCache(1,10,clock);cache.put('a',1);clock.now=9;cache.put('a',2)
                    clock.now=11;self.assertEqual(cache.get('a'),2)
                def test_instance_isolation(self):
                    a=TTLCache(1,5,lambda:0);b=TTLCache(1,5,lambda:0);a.put('x',1);self.assertIsNone(b.get('x'))
        '''),
    },
    {
        'id': 'fix_checkout_three_files',
        'title': 'Naprawa w trzech plikach: kwoty, pozycje i rabat faktury',
        'kind': 'three_file_fix',
        'spec': '''Fix the checkout pipeline in exactly money.py, cart.py, invoice.py.
Public API: money.to_minor(amount: str) -> int; cart.line_total(unit_price: str,
quantity: int) -> int; invoice.invoice_total(items: list[tuple[str,int]],
discount_percent: str = "0") -> int. Results are integer cents, not floats.
Amounts and discount are finite nonnegative Decimal strings; reject non-string,
invalid, nonfinite and negative input with ValueError. Discount must be <=100.
quantity must be a positive integer, not bool; invalid quantity raises ValueError.
money.to_minor rounds cents with ROUND_HALF_UP. cart.line_total multiplies the
EXACT unit price by quantity BEFORE rounding to cents (never round unit first).
invoice.invoice_total sums rounded line totals, applies ONE invoice-level discount
(percent / 100), then rounds with ROUND_HALF_UP. Empty cart returns 0 but still
validates discount. Do not mutate items. Preserve names/signatures and fix the
separate precision/validation bug in money, early rounding/quantity bug in cart,
and discount/rounding bug in invoice. No additional files or dependencies.''',
        'before': {
            'money.py': 'def to_minor(amount: str) -> int:\n    return round(float(amount) * 100)\n',
            'cart.py': 'from money import to_minor\n\ndef line_total(unit_price: str, quantity: int) -> int:\n    return to_minor(unit_price) * quantity\n',
            'invoice.py': 'from cart import line_total\n\ndef invoice_total(items: list[tuple[str, int]], discount_percent: str = "0") -> int:\n    return sum(round(line_total(price, quantity) * (1 - float(discount_percent) / 100)) for price, quantity in items)\n',
        },
        'reference': {
            'money.py': text('''
                from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
                def parse_amount(amount: str) -> Decimal:
                    """Parse a finite nonnegative decimal string."""
                    if not isinstance(amount, str): raise ValueError('amount must be a string')
                    try: value = Decimal(amount)
                    except InvalidOperation as exc: raise ValueError('invalid amount') from exc
                    if not value.is_finite() or value < 0: raise ValueError('invalid amount')
                    return value
                def to_minor(amount: str) -> int:
                    """Round to cents using half-up rounding."""
                    return int((parse_amount(amount) * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            '''),
            'cart.py': text('''
                from money import parse_amount, to_minor
                def line_total(unit_price: str, quantity: int) -> int:
                    """Multiply before rounding; quantity must be a positive integer."""
                    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
                        raise ValueError('invalid quantity')
                    return to_minor(str(parse_amount(unit_price) * quantity))
            '''),
            'invoice.py': text('''
                from decimal import Decimal, ROUND_HALF_UP
                from money import parse_amount
                from cart import line_total
                def invoice_total(items: list[tuple[str, int]], discount_percent: str = "0") -> int:
                    """Apply one validated discount to the invoice's total cents."""
                    discount = parse_amount(discount_percent)
                    if discount > 100: raise ValueError('invalid discount')
                    total = sum(line_total(price, quantity) for price, quantity in items)
                    return int((Decimal(total) * (1 - discount / 100)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))
            '''),
        },
        'tests': text('''
            import unittest
            from money import to_minor
            from cart import line_total
            from invoice import invoice_total
            class Functional(unittest.TestCase):
                def test_money_half_up(self): self.assertEqual(to_minor('0.005'),1)
                def test_large_exact_amount(self): self.assertEqual(to_minor('90071992547409.93'),9007199254740993)
                def test_invalid_money(self):
                    for amount in ['NaN','Infinity','-0.01','oops',1]:
                        with self.subTest(amount=amount), self.assertRaises(ValueError): to_minor(amount)
                def test_multiply_before_rounding(self): self.assertEqual(line_total('0.005',2),1)
                def test_invalid_quantity(self):
                    for quantity in [0,-1,True,1.5,'2']:
                        with self.subTest(quantity=quantity), self.assertRaises(ValueError): line_total('1',quantity)
                def test_discount_once(self): self.assertEqual(invoice_total([('0.01',1),('0.01',1)],'50'),1)
                def test_discount_half_up(self): self.assertEqual(invoice_total([('0.01',1)],'50'),1)
                def test_invalid_discount_even_empty(self):
                    for discount in ['-1','101','NaN','Infinity','bad',10]:
                        with self.subTest(discount=discount), self.assertRaises(ValueError): invoice_total([],discount)
            class Regression(unittest.TestCase):
                def test_empty(self): self.assertEqual(invoice_total([]),0)
                def test_zero_discount(self): self.assertEqual(invoice_total([('2.50',2),('1.20',1)]),620)
                def test_full_discount(self): self.assertEqual(invoice_total([('2.50',2)],'100'),0)
                def test_input_unchanged(self):
                    items=[('1.005',2)];original=items.copy();invoice_total(items,'10');self.assertEqual(items,original)
        '''),
    },
]


def prompt(case):
    files = '\n'.join(f'--- {name} ---\n{code}' for name, code in case['before'].items())
    return ('You are implementing a Python 3.12 coding task. Return ONLY a JSON object '
            'with exactly one key "files", whose value maps each required filename to its '
            'complete final source code string. No markdown, explanations, tests or extra files. '
            'Do not access files, network, environment or processes.\n\nSPECIFICATION:\n' +
            case['spec'] + '\n\nEXISTING FILES:\n' + files)
