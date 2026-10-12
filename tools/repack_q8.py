"""Recreate measured Ollama Q8 GGUF from the two exact pinned source models."""
import argparse
import hashlib
import json
import math
import os
import pathlib
import struct

ROOT = pathlib.Path(__file__).resolve().parents[1]


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        while block := f.read(8 * 1024 * 1024):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ollama-bf16', required=True, type=pathlib.Path)
    parser.add_argument('--upstream-q8', required=True, type=pathlib.Path)
    parser.add_argument('--output', required=True, type=pathlib.Path)
    args = parser.parse_args()
    metadata = json.loads((ROOT / 'evidence/model-parity/control-model-headers.json').read_text())
    hashes = {item['name']: item['sha256'] for item in json.loads(
        (ROOT / 'evidence/model-parity/official-model-verification.json').read_text())['tensor_hashes']}
    partial = args.output.with_suffix(args.output.suffix + '.partial')
    assert not args.output.exists() and not partial.exists(), 'Output exists'
    assert digest(args.ollama_bf16) == 'e7b273f9636059a689e3ddcab3716e4f65abe0143ac978e46673ad0e52d09efb'
    assert digest(args.upstream_q8) == '27cd6c432c7672cb812a92f611cf3ba7bbc35928262bb1e1253ff4ee6ae35901'
    source_info = {item['name']: item for item in metadata['official']['tensors']}
    with args.ollama_bf16.open('rb') as source:
        header = bytearray(source.read(metadata['ollama']['data_start']))
    plan = []
    offset = 0
    for target in metadata['ollama']['tensors']:
        name = target['name'].replace('.attn_out.', '.attn_output.').replace('.ffn_norm.', '.post_attention_norm.')
        if name.endswith('.attn_sinks'):
            name += '.weight'
        item = source_info[name]
        assert item['dims'] == target['dims'] and item['type'] in [0, 8, 39]
        count = math.prod(item['dims'])
        size = count * 4 if item['type'] == 0 else count // 32 * (34 if item['type'] == 8 else 17)
        offset = (offset + 31) // 32 * 32
        struct.pack_into('<I', header, target['type_pos'], item['type'])
        struct.pack_into('<Q', header, target['offset_pos'], offset)
        plan.append((item, offset, size))
        offset += size
    with args.upstream_q8.open('rb') as source, partial.open('x+b') as out:
        out.truncate(metadata['ollama']['data_start'] + offset)
        out.write(header)
        for item, target_offset, size in plan:
            source.seek(metadata['official']['data_start'] + item['offset'])
            out.seek(metadata['ollama']['data_start'] + target_offset)
            remaining = size
            h = hashlib.sha256()
            while remaining:
                block = source.read(min(8 * 1024 * 1024, remaining))
                assert block, item['name']
                out.write(block)
                h.update(block)
                remaining -= len(block)
            assert h.hexdigest() == hashes[item['name']], item['name']
        out.flush()
        os.fsync(out.fileno())
    sha = digest(partial)
    assert sha == '214b01ff392ec0d991c766ceccba11948c1208c3aa8272b63a5170d802c1866e', sha
    # Publish without overwriting a file that appeared while the model copied.
    os.link(partial, args.output)
    partial.unlink()
    print(json.dumps({'path': str(args.output), 'sha256': sha, 'bytes': args.output.stat().st_size,
                      'matching_tensors': len(plan)}, indent=2))


if __name__ == '__main__':
    main()
