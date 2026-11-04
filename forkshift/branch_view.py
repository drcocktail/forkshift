"""Read-only presentation of a completed native Redshift branch trial."""
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRIAL = ROOT / 'redshift_evidence' / 'branch-trial.json'
LIVE_TRIAL = TRIAL.with_name('live-branch-trial.json')


def read_trial(path=None):
    if path is None:
        path = LIVE_TRIAL if LIVE_TRIAL.is_file() else TRIAL
    raw = json.loads(path.read_text())
    branches = []
    winner = None
    for row in raw['branches']:
        episode = row.get('episode') or {}
        summary = episode.get('summary', {})
        worker_engine = episode.get('engine', 'fixture')
        result = (f'{worker_engine.title()} workers · recovery '
                  f'{"passed" if summary.get("recovered") else "not verified"} · safety '
                  f'{"passed" if summary.get("safe") else "not verified"}')
        receipt = row.get('receipt')
        terminal = (receipt or {}).get('verification', {}).get('status') == 'pass'
        if terminal != row.get('terminal_verified'):
            raise ValueError('Recorded terminal status disagrees with the native receipt.')
        if row['id'] == raw.get('selected_branch_id') and terminal and row.get('receipt_valid'):
            winner = row['label']
        payload = {key: value for key, value in receipt.items() if key != 'signature'} if receipt else None
        canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode() if payload else b''
        branches.append({
            'id': row['id'], 'label': row['label'], 'actions': row['actions'],
            'elapsed_ms': row.get('elapsed_ms'), 'terminal_verified': row.get('terminal_verified'),
            'receipt_valid': row.get('receipt_valid'), 'route': row.get('route'),
            'model_calls': row.get('model_calls'), 'outcome': result,
            'receipt': receipt, 'cartridge': row.get('artifact'), 'evidence': episode,
            'receipt_bytes': base64.b64encode(canonical).decode() if canonical else None,
        })
    return {
        'title': 'The green-light trap', 'winner': winner, 'branches': branches,
        'scope': ('The worker drill recorded the original Llama moves. Redshift repeats the moves with fresh workers '
                  'and signs each result. The grades apply to this incident.'),
    }


def export():
    report = read_trial()
    page = (ROOT / 'static' / 'redshift.html').read_text()
    marker = 'const OFFLINE_BRANCH_TRIAL = null;'
    if page.count(marker) != 1:
        raise ValueError('Offline branch marker missing or duplicated.')
    payload = json.dumps(report, separators=(',', ':')).replace('<', '\\u003c')
    (ROOT / 'Forkshift-Branch-Garden.html').write_text(
        page.replace(marker, 'const OFFLINE_BRANCH_TRIAL = ' + payload + ';')
    )


if __name__ == '__main__':
    export()
