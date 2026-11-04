"""Export a self-contained, interactive recording for an offline reviewer."""
import json
from pathlib import Path

from forkshift.scenarios import INCIDENTS

ROOT = Path(__file__).resolve().parent


def main():
    recordings = {}
    for key in INCIDENTS:
        recordings[key] = json.loads((ROOT / 'evidence' / f'{key}.json').read_text())
    payload = json.dumps(recordings, separators=(',', ':')).replace('<', '\\u003c')
    template = (ROOT / 'static' / 'index.html').read_text()
    marker = 'const OFFLINE_REPLAYS = null;'
    if template.count(marker) != 1:
        raise RuntimeError('Offline marker missing or duplicated.')
    (ROOT / 'Forkshift-Demo.html').write_text(
        template.replace(marker, 'const OFFLINE_REPLAYS = ' + payload + ';')
    )


if __name__ == '__main__':
    main()
