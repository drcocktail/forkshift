"""Run the simulator, start the local cockpit, or write an evidence bundle."""
import argparse
import json
import os
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import arcade, branch_view, director
from .canary import canary
from .model import propose
from .scenarios import INCIDENTS, incident_info
from .sim import BASELINE, FALLBACK, compare, plan_hash, search

ROOT = Path(__file__).resolve().parent.parent
RUN_LOCK = threading.Lock()


def run(key, mode):
    if key not in INCIDENTS or mode not in ('compare', 'llama', 'muse'):
        raise ValueError('Unsupported incident or run mode.')
    plans = {'unchanged': BASELINE, 'panic': FALLBACK, 'search': search(key)}
    report = {'incident': incident_info(key), 'mode': mode,
              'created_utc': datetime.now(timezone.utc).isoformat()}
    if mode != 'compare':
        try:
            plans['llama'], reason, metadata = propose(key, mode=mode)
            report['model'] = {**metadata, 'reason': reason}
        except ValueError as exc:
            report['model_error'] = str(exc)
    report['branches'] = compare(key, plans)
    first = report['branches'].get('llama')
    if first and not first['eligible']:
        feedback = {'previous_plan': first['plan'], 'replays': [
            {'replay': name, 'failures': row['failures'], 'voice': row['voice']['rate'],
             'batch': row['batch']['rate'], 'alternate': row['alternate_rate']}
            for name, row in first['replays'].items()
        ]}
        try:
            plan, reason, metadata = propose(key, feedback, mode=mode)
            report['revision'] = {**metadata, 'reason': reason, 'feedback': feedback}
            report['branches'].update(compare(key, {'revision': plan}))
        except ValueError as exc:
            report['revision_error'] = str(exc)
    return report


class Handler(BaseHTTPRequestHandler):
    def reply(self, status, payload, content_type='application/json'):
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/':
            self.reply(200, (ROOT / 'static/index.html').read_bytes(), 'text/html')
        elif self.path == '/director':
            self.send_response(308)
            self.send_header('Location', '/director/')
            self.send_header('Content-Length', '0')
            self.end_headers()
        elif self.path == '/director/':
            self.reply(200, (ROOT / 'director' / 'index.html').read_bytes(), 'text/html')
        elif self.path == '/director/engine.mjs':
            self.reply(200, (ROOT / 'director' / 'engine.mjs').read_bytes(), 'text/javascript')
        elif self.path == '/director/level.json':
            self.reply(200, (ROOT / 'director' / 'level.json').read_bytes())
        elif self.path == '/arcade':
            self.reply(200, (ROOT / 'static' / 'arcade.html').read_bytes(), 'text/html')
        elif self.path == '/redshift':
            self.reply(200, (ROOT / 'static' / 'redshift.html').read_bytes(), 'text/html')
        elif self.path == '/api/redshift/trial':
            try:
                self.reply(200, branch_view.read_trial())
            except FileNotFoundError:
                self.reply(404, {'error': 'No recorded Redshift branch trial.'})
            except (ValueError, KeyError):
                self.reply(500, {'error': 'The Redshift trial failed its presentation checks.'})
        elif self.path == '/api/arcade':
            self.reply(200, arcade.catalog())
        elif self.path.startswith('/api/arcade/replay/'):
            try:
                self.reply(200, arcade.replay(self.path.removeprefix('/api/arcade/replay/')))
            except ValueError as exc:
                self.reply(404, {'error': str(exc)})
        elif self.path == '/api/incidents':
            self.reply(200, {'incidents': [incident_info(key) for key in INCIDENTS],
                             'recordings': [key for key in INCIDENTS if self.recording(key).is_file()],
                             'muse_configured': bool(os.environ.get('MODEL_API_KEY'))})
        elif self.path.startswith('/api/recording/'):
            key = self.path.removeprefix('/api/recording/')
            if key not in INCIDENTS or not self.recording(key).is_file():
                self.reply(404, {'error': 'Recording unavailable.'})
            else:
                self.reply(200, self.recording(key).read_bytes())
        else:
            self.reply(404, {'error': 'Unknown path.'})

    @staticmethod
    def recording(key):
        return ROOT / 'evidence' / f'{key}.json'

    def do_POST(self):
        if self.path not in ('/api/run', '/api/canary', '/api/arcade/run', '/api/director/author'):
            self.reply(404, {'error': 'Unknown path.'})
            return
        origin = self.headers.get('Origin')
        allowed = {f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'}
        if origin and origin not in allowed:
            self.reply(403, {'error': 'Only the loopback cockpit can start runs.'})
            return
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            self.reply(415, {'error': 'Send application/json.'})
            return
        if not RUN_LOCK.acquire(blocking=False):
            self.reply(409, {'error': 'Another inference request is running.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096:
                raise ValueError('Invalid request size.')
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or not all(isinstance(v, str) for v in body.values()):
                raise ValueError('Expected a JSON object of strings.')
            if self.path == '/api/director/author' and set(body) == {'brief'}:
                result = director.author(body['brief'])
            elif self.path == '/api/arcade/run' and set(body) == {'scenario', 'agent', 'engine'}:
                if body['agent'] not in ('llama', 'policy'):
                    raise ValueError('Reference controls are only available as recordings.')
                result = arcade.run(body['scenario'], body['agent'], body['engine'])
            elif self.path == '/api/run' and set(body) == {'incident', 'mode'}:
                result = run(body['incident'], body['mode'])
            elif self.path == '/api/canary' and set(body) == {'incident', 'branch', 'plan_sha256'}:
                key, branch = body['incident'], body['branch']
                if key not in INCIDENTS or branch not in ('unchanged', 'panic', 'search', 'llama', 'revision'):
                    raise ValueError('Unsupported canary target.')
                # Recompute the gate server-side. Client verdicts cannot enable a canary.
                # A model branch uses the exact plan saved by the server's last live run.
                plan = self.server.model_plans.get((key, branch)) if branch in ('llama', 'revision') else {
                    'unchanged': BASELINE, 'panic': FALLBACK, 'search': search(key),
                }[branch]
                if plan is None:
                    raise ValueError('Generate a new model branch before its canary.')
                if plan_hash(plan) != body['plan_sha256']:
                    raise ValueError('The selected plan changed. Run the replay again.')
                result = canary(compare(key, {branch: plan})[branch])
            else:
                raise ValueError('Unsupported request fields.')
            if self.path == '/api/run' and body['mode'] in ('llama', 'muse'):
                for model_branch in ('llama', 'revision'):
                    cache_key = (body['incident'], model_branch)
                    self.server.model_plans.pop(cache_key, None)
                    if model_branch in result['branches']:
                        self.server.model_plans[cache_key] = result['branches'][model_branch]['plan']
            self.reply(200, result)
        except (ValueError, UnicodeDecodeError) as exc:
            self.reply(400, {'error': str(exc)})
        finally:
            RUN_LOCK.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    serve = commands.add_parser('serve')
    serve.add_argument('--port', type=int, default=8790)
    record = commands.add_parser('run')
    record.add_argument('--incident', choices=INCIDENTS, default='rank-drop')
    record.add_argument('--mode', choices=('compare', 'llama', 'muse'), default='compare')
    record.add_argument('--canary', choices=('search', 'llama', 'revision'))
    record.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.command == 'serve':
        with ThreadingHTTPServer(('127.0.0.1', args.port), Handler) as server:
            server.model_plans = {}
            print(f'Forkshift: http://127.0.0.1:{server.server_port}', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
        return
    result = run(args.incident, args.mode)
    if args.canary:
        candidate = result['branches'].get(args.canary)
        if candidate and candidate['eligible']:
            result['canary'] = {'branch': args.canary, **canary(candidate)}
        else:
            result['canary'] = {'branch': args.canary, 'outcome': 'blocked-by-verifier'}
    rendered = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x') as stream:
            stream.write(rendered)
    else:
        print(rendered, end='')


if __name__ == '__main__':
    main()
