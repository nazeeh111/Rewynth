"""Data-only, source-bound counterexample records for declared memory models."""
import hashlib
import json
import os
import tempfile
import stat
from pathlib import Path
from .words import normalize_request

LIMIT = 1024 * 1024

def publish_exclusive(destination, raw):
    """Publish complete bytes; return a warning if owned-stage cleanup fails."""
    path = Path(destination)
    fd, staging = tempfile.mkstemp(prefix='.rewynth-witness-', dir=path.parent)
    failure = None
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(staging, path)
    except BaseException as exc:
        failure = exc
    try:
        os.unlink(staging)
    except OSError as cleanup:
        note = f'Owned staging cleanup failed at {staging}: {cleanup}'
        if failure is not None:
            failure.add_note(note)
        else:
            return note
    if failure is not None:
        raise failure
    return None


def capture_witness(path):
    """Capture bounded bytes from one nonblocking, no-follow regular descriptor."""
    if not hasattr(os, 'O_NONBLOCK') or not hasattr(os, 'O_NOFOLLOW'):
        raise ValueError('Safe witness admission requires nonblocking no-follow support.')
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > LIMIT:
            raise ValueError('Witness must be a bounded regular file.')
        chunks, total = [], 0
        while True:
            chunk = os.read(fd, min(65536, LIMIT + 1 - total))
            if not chunk: break
            total += len(chunk)
            if total > LIMIT: raise ValueError('Witness exceeds its byte limit.')
            chunks.append(chunk)
        return b''.join(chunks)
    finally:
        os.close(fd)


def unique_json(raw):
    def pairs(items):
        output = {}
        for key, value in items:
            if key in output: raise ValueError('Duplicate witness key.')
            output[key] = value
        return output
    def nonfinite(_): raise ValueError('Nonfinite witness value.')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ValueError('Invalid witness JSON.') from exc


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')

def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()

def harness(original, candidate, observation, binding):
    # These are reconstructed model functions; they do not execute target bytes.
    original = original.replace('rewynth_', 'original_')
    candidate = candidate.replace('rewynth_', 'candidate_')
    def integer(value): return int(value, 0) if isinstance(value, str) else value
    inputs = ', '.join('UINT64_C(%d)' % integer(v) for v in observation['inputs_u64'])
    checks = []
    for prefix, key in [('a', 'original'), ('b', 'candidate')]:
        checks.append('%s.result == UINT64_C(%d)' % (prefix, integer(observation[key+'_output_u64'])))
        for i, value in enumerate(observation[key+'_memory_u64']):
            checks.append('%s.memory[%d] == UINT64_C(%d)' % (prefix, i, integer(value)))
    return ('/* Reconstructed instruction model only; not target execution or its pointer ABI.\n'
            '   Binding SHA-256: ' + digest(binding) + ' (artifact, function, settings and expression). */\n'
            + original + '\n' + candidate + '\n#include <stdio.h>\nint main(void) {\n'
            + '  original_state a = original_transition('+inputs+');\n'
            + '  candidate_state b = candidate_transition('+inputs+');\n'
            + '  if (!(' + ' && '.join(checks) + ')) return 1;\n'
            + '  puts("Reconstructed model witness reproduced"); return 0;\n}\n')

def create(request, code, address, name, result, run):
    proof = result.get('verification', {})
    if request.get('memory') is None or proof.get('status') != 'sat':
        raise ValueError('A witness requires a SAT memory transition comparison.')
    inputs = proof['counterexample']['inputs_u64']
    replay_request = {**request, 'operation':'replay_witness', 'inputs':inputs}
    observed = run(replay_request, code, address, name)['observation']
    for key in ('inputs_u64','original_output_u64','candidate_output_u64','original_memory_u64','candidate_memory_u64','differences'):
        if observed[key] != proof['counterexample'][key]:
            raise ValueError('Counterexample could not be replayed exactly.')
    recovered = run({**request, 'operation':'recover'}, code, address, name)
    if recovered.get('reconstruction',{}).get('verification',{}).get('status') != 'unsat':
        raise ValueError('Original transition could not be reconstructed for the C harness.')
    binding = {'artifact_sha256':request['artifact'], 'function_sha256':hashlib.sha256(code).hexdigest(),
               'symbol':name, 'settings':{'arity':request['arity'], 'word_bits':request['word_bits'],
                                         'memory':request['memory'], 'domain':request.get('domain')},
               'expression':request['expression']}
    payload = {'schema':'rewynth-memory-witness/1', 'artifact_sha256':request['artifact'],
               'function_sha256':hashlib.sha256(code).hexdigest(), 'symbol':name,
               'settings':{'arity':request['arity'], 'word_bits':request['word_bits'],
                           'memory':request['memory'], 'domain':request.get('domain')},
               'expression':request['expression'], 'observation':observed,
               'c_harness':harness(recovered['source'], result['source'], observed, binding),
               'scope':'Reconstructed ARM64 instruction model and declared domain; no native execution or authenticity claim.'}
    return {'payload':payload, 'sha256':digest(payload)}

def replay(document, artifact, code, address, name, run):
    if not isinstance(document,dict) or set(document)!={'payload','sha256'} or not isinstance(document['payload'],dict):
        raise ValueError('Invalid witness envelope.')
    p=document['payload']
    required={'schema','artifact_sha256','function_sha256','symbol','settings','expression','observation','c_harness','scope'}
    if set(p)!=required or p['schema']!='rewynth-memory-witness/1' or document['sha256']!=digest(p):
        raise ValueError('Witness integrity or schema mismatch.')
    if p['scope']!='Reconstructed ARM64 instruction model and declared domain; no native execution or authenticity claim.':
        raise ValueError('Witness scope differs.')
    if p['artifact_sha256']!=artifact or p['function_sha256']!=hashlib.sha256(code).hexdigest() or p['symbol']!=name:
        raise ValueError('Witness artifact or function binding differs.')
    if not isinstance(p['settings'],dict) or set(p['settings'])!={'arity','word_bits','memory','domain'}:
        raise ValueError('Invalid witness settings.')
    request=normalize_request({**p['settings'],'artifact':artifact,'operation':'replay_witness',
                               'expression':p['expression'],'inputs':p['observation']['inputs_u64']})
    result=run(request,code,address,name)
    if canonical(result['observation'])!=canonical(p['observation']) or not result['observation']['differences']:
        raise ValueError('Witness observations do not replay.')
    recovered=run({**request,'operation':'recover'},code,address,name)
    if recovered.get('reconstruction',{}).get('verification',{}).get('status')!='unsat' or p['c_harness']!=harness(recovered['source'],result['source'],result['observation'],{k:p[k] for k in ('artifact_sha256','function_sha256','symbol','settings','expression')}):
        raise ValueError('Witness C harness differs from reconstructed model.')
    return result
