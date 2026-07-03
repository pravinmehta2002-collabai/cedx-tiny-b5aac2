"""Diagnostic — precise mismatch inspector."""
import json
from pathlib import Path
from agents.prompts import get_prompt
from agents.worker import _build_user_prompt, NAME as WORKER_NAME
from pipeline.intake import intake
from pipeline.normalize import Normalizer
from pipeline.exceptions import ExceptionQueue

seed_dir = Path('seed')
norm = Normalizer(Path('schemas/field_mapping.yaml'))
raws = intake(seed_dir)

normalized = []
drift = {}
for raw in raws:
    res = norm.normalize(raw)
    if res.record:
        normalized.append(res.record)
        if res.drift_fields:
            drift[res.record.id] = res.drift_fields

eq = ExceptionQueue(Path('schemas/field_mapping.yaml'))
triaged = eq.triage(normalized, drift)

p = get_prompt('worker_v1')
system_runtime = p['system']

tr = next(t for t in triaged if not t.superseded_by and not t.blocked)
print('Testing record:', tr.record.id)
user_runtime = _build_user_prompt(tr.record)

print()
print('--- RUNTIME PROMPT ---')
print(repr(user_runtime))
print()

tdir = Path('transcripts')
transcripts = list(tdir.glob('*.json'))
print('Total transcripts on disk:', len(transcripts))

found = False
for tp in transcripts:
    try:
        t = json.loads(tp.read_text(encoding='utf-8'))
    except Exception:
        continue
    if t.get('agent') == 'worker_v1' and tr.record.id in t.get('request', {}).get('user', ''):
        found = True
        user_disk = t['request']['user']
        system_disk = t['request']['system']
        print()
        print('--- DISK PROMPT for', tr.record.id, 'in', tp.name, '---')
        print(repr(user_disk))
        print()
        print('System exact match :', system_disk == system_runtime)
        print('User   exact match :', user_disk == user_runtime)
        print('User len disk      :', len(user_disk))
        print('User len runtime   :', len(user_runtime))

        for i, (a, b) in enumerate(zip(user_disk, user_runtime)):
            if a != b:
                print(f'FIRST USER DIFF at char {i}: disk={a!r} runtime={b!r}')
                print('  context disk    :', repr(user_disk[max(0, i-40):i+40]))
                print('  context runtime :', repr(user_runtime[max(0, i-40):i+40]))
                break
        break

if not found:
    print()
    print('NO worker transcript found on disk for', tr.record.id)
    print('Available worker transcript record_ids on disk:')
    for tp in transcripts:
        try:
            t = json.loads(tp.read_text(encoding='utf-8'))
        except:
            continue
        if t.get('agent') == 'worker_v1':
            resp = t.get('response', {})
            print('  -', tp.name[:12], 'record_id=', resp.get('record_id'))