"""Meta Llama planning and real local generation through Ollama."""
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .scenarios import incident_info
from .sim import ADMISSION, OVERFLOW, RESERVE, validate_plan

PLANNER = 'llama3.1:8b'
FAST_MODEL = 'llama3.2:3b'
MUSE_ENDPOINT = 'https://api.meta.ai/v1/chat/completions'
MUSE_MODEL = 'muse-spark-1.3'
SCHEMA = {
    'type': 'object',
    'properties': {
        'overflow': {'type': 'string', 'enum': list(OVERFLOW)},
        'batch_admit_pct': {'type': 'integer', 'enum': list(ADMISSION)},
        'reserve_pct': {'type': 'integer', 'enum': list(RESERVE)},
        'reason': {'type': 'string'},
    },
    'required': ['overflow', 'batch_admit_pct', 'reserve_pct', 'reason'],
    'additionalProperties': False,
}


def generate(model, prompt, *, schema=None, tokens=200, keep_alive=None):
    body = {'model': model, 'prompt': prompt, 'stream': False,
            'options': {'temperature': 0, 'seed': 42, 'num_predict': tokens}}
    if schema:
        body['format'] = schema
    if keep_alive is not None:
        body['keep_alive'] = keep_alive
    request = Request('http://127.0.0.1:11434/api/generate',
                      data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    started = time.monotonic()
    try:
        with urlopen(request, timeout=60) as stream:
            result = json.loads(stream.read(1_000_000))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
        raise ValueError('Local Ollama request failed. Check the installed model tags and service.') from None
    if not isinstance(result, dict) or not isinstance(result.get('response'), str) or (schema and result.get('done_reason') != 'stop'):
        raise ValueError('Model returned an incomplete response.')
    metadata = {'model': result.get('model', model),
                'latency_ms': round((time.monotonic() - started) * 1000),
                'prompt_tokens': result.get('prompt_eval_count'),
                'output_tokens': result.get('eval_count')}
    return result['response'], metadata


def generate_muse(prompt):
    key = os.environ.get('MODEL_API_KEY')
    if not key:
        raise ValueError('Set MODEL_API_KEY to enable Muse planning.')
    model = os.environ.get('META_MODEL', MUSE_MODEL)
    body = {
        'model': model, 'max_completion_tokens': 1200,
        'messages': [{'role': 'user', 'content': prompt}],
        'response_format': {'type': 'json_schema',
                            'json_schema': {'name': 'ForkshiftPlan', 'strict': True, 'schema': SCHEMA}},
    }
    request = Request(MUSE_ENDPOINT, data=json.dumps(body).encode(),
                      headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})
    started = time.monotonic()
    try:
        with urlopen(request, timeout=50) as stream:
            result = json.loads(stream.read(1_000_000))
        choice = result['choices'][0]
        if choice.get('finish_reason') != 'stop':
            raise ValueError('Muse did not finish its plan.')
        answer = choice['message']['content']
    except HTTPError as exc:
        raise ValueError(f'Muse API returned HTTP {exc.code}.') from None
    except (URLError, TimeoutError, KeyError, IndexError, TypeError, AttributeError, json.JSONDecodeError):
        raise ValueError('Muse API request or response failed.') from None
    if not isinstance(answer, str):
        raise ValueError('Muse returned an invalid plan response.')
    usage = result.get('usage')
    if not isinstance(usage, dict):
        usage = {}
    return answer, {'model': result.get('model', model), 'provider': 'meta-model-api',
                    'latency_ms': round((time.monotonic() - started) * 1000),
                    'prompt_tokens': usage.get('prompt_tokens'), 'output_tokens': usage.get('completion_tokens')}


def propose(key, feedback=None, *, mode='llama'):
    incident = incident_info(key)
    prompt = f'''You are the incident commander for an inference service. Propose one routing policy.
Owner incident brief: {incident['brief']}
Primary capacity before fault: {incident['primary_capacity']} requests/sec.
Primary capacity during fault: {incident['degraded_capacity']} requests/sec.
Alternate capacity: {incident['alternate_capacity']} requests/sec.
overflow=off, voice or all. The alternate serves waiting voice first, then batch only if all.
batch_admit_pct is the percent of new batch requests admitted during the fault.
reserve_pct is the percent of primary capacity given to voice first; unused capacity goes back to FIFO.
All controls revert after recovery. Prefer to preserve batch where targets allow it.
A plan that violates an approval restriction is invalid. Explain the plan in one short sentence.
Return the three policy fields and the reason in JSON.'''
    if feedback:
        prompt += (
            '\nThe simulator rejected the previous plan. Change the controls to address these '
            'counterexamples. A rejected plan must not be used. Previous plan and measured failures:\n'
            + json.dumps(feedback)
        )
    if mode == 'muse':
        response, metadata = generate_muse(prompt)
    else:
        response, metadata = generate(PLANNER, prompt, schema=SCHEMA, tokens=220)
    try:
        candidate = json.loads(response)
    except json.JSONDecodeError:
        raise ValueError('Model returned invalid plan JSON.') from None
    if not isinstance(candidate, dict) or not isinstance(candidate.get('reason'), str):
        raise ValueError('Model returned an invalid plan.')
    reason = candidate.pop('reason')
    return validate_plan(candidate), reason, metadata
