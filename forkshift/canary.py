"""Route a real synthetic probe through a faulting loopback model gateway."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from .model import FAST_MODEL, PLANNER, generate

PROBE_ID = 'forkshift-voice-01'
PROMPT = f'Return a JSON object that acknowledges receipt of the synthetic probe with probe_id "{PROBE_ID}".'
SCHEMA = {
    'type': 'object',
    'properties': {
        'status': {'type': 'string', 'enum': ['acknowledged']},
        'probe_id': {'type': 'string'},
    },
    'required': ['status', 'probe_id'],
    'additionalProperties': False,
}


def model_probe(model, inference):
    try:
        answer, usage = inference(model, PROMPT, schema=SCHEMA, tokens=65)
        if json.loads(answer) != {'status': 'acknowledged', 'probe_id': PROBE_ID}:
            raise ValueError('Model response failed the probe ID and acknowledgement check.')
    except (ValueError, TypeError) as exc:
        return {'status': 502, 'model': model, 'error': str(exc)}
    return {'status': 200, 'response': answer.strip(), **usage}


class PrimaryGateway(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.server.faulted:
            payload = {'status': 503, 'injected': True, 'model': PLANNER}
        else:
            payload = model_probe(PLANNER, self.server.inference)
        data = json.dumps(payload).encode()
        self.send_response(payload['status'])
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def request_primary(port):
    url = f'http://127.0.0.1:{port}/probe'
    try:
        try:
            with urlopen(url, timeout=65) as response:
                return json.load(response)
        except HTTPError as exc:
            with exc:
                return json.load(exc)
    except (URLError, TimeoutError, ValueError):
        return {'status': 502, 'model': PLANNER, 'error': 'Primary loopback request failed.'}


def canary(result, inference=generate):
    if not result['eligible']:
        raise ValueError('Canary blocked because this plan failed replay verification.')
    attempts = []
    with HTTPServer(('127.0.0.1', 0), PrimaryGateway) as gateway:
        gateway.faulted = False
        gateway.inference = inference
        thread = Thread(target=gateway.serve_forever, daemon=True)
        thread.start()
        try:
            baseline = request_primary(gateway.server_port)
            attempts.append({'phase': 'healthy', 'pool': 'primary', 'transport': 'loopback-http', **baseline})
            gateway.faulted = True
            failed = request_primary(gateway.server_port)
            attempts.append({'phase': 'fault', 'pool': 'primary', 'transport': 'loopback-http', **failed})
            if failed['status'] != 503:
                return {'attempts': attempts, 'outcome': 'fault-injection-failed'}
            if result['plan']['overflow'] == 'off':
                outcome = 'blocked-by-policy'
            else:
                alternate = model_probe(FAST_MODEL, inference)
                attempts.append({'phase': 'fault', 'pool': 'alternate', **alternate})
                outcome = 'served-by-alternate' if alternate['status'] == 200 else 'alternate-failed'
            gateway.faulted = False
            restored = request_primary(gateway.server_port)
            attempts.append({'phase': 'restored', 'pool': 'primary', 'transport': 'loopback-http', **restored})
            if baseline['status'] != 200 or restored['status'] != 200:
                outcome = 'primary-probe-failed'
        finally:
            gateway.shutdown()
            thread.join(timeout=2)
    return {'attempts': attempts, 'outcome': outcome}
