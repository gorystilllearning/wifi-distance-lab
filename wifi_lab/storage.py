import csv
import io
import json
import math
import os
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .protocol import PAYLOAD_BYTES

COLUMNS = ['test_id', 'session_id', 'timestamp_utc', 'device', 'distance_m', 'repetition',
           'status', 'report_status', 'failure_reason', 'controller_reason', 'target_bytes',
           'bytes_sent_socket', 'bytes_received', 'duration_s', 'throughput_mbps', 'transfer_complete',
           'rssi_mean_dbm', 'rssi_min_dbm', 'rssi_max_dbm', 'rssi_samples_count',
           'rssi_reason', 'rtt_mean_ms', 'rtt_min_ms', 'rtt_max_ms', 'rtt_attempts',
           'rtt_replies', 'rtt_loss_pct', 'rtt_phase', 'timeout_s', 'ssid', 'bssid',
           'receiver_id', 'measurement_source', 'timer']


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    with temp.open('w', encoding='utf-8', newline='') as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temp, path)


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def stats(values):
    return (statistics.fmean(values), min(values), max(values)) if values else (None, None, None)


def safe_csv(row):
    # Preserve raw JSON, but don't let peer-supplied text become an Excel formula.
    return {key: "'" + value if isinstance(value, str) and value.startswith(('=', '+', '-', '@', '\t', '\r', '\n'))
            else value for key, value in row.items()}


def summarize(record):
    r = dict(record)
    size, duration = r.get('bytes_received'), r.get('duration_s')
    r['throughput_mbps'] = size * 8 / duration / 1e6 if size is not None and duration and duration > 0 else None
    valid = [s['rssi_dbm'] for s in r.get('rssi_samples', [])
             if isinstance(s.get('rssi_dbm'), (int, float)) and -127 <= s['rssi_dbm'] < 0]
    r['rssi_mean_dbm'], r['rssi_min_dbm'], r['rssi_max_dbm'] = stats(valid)
    r['rssi_samples_count'] = len(valid)
    attempts = r.get('rtt_samples', [])
    replies = [s['rtt_ms'] for s in attempts if s.get('rtt_ms') is not None]
    r['rtt_mean_ms'], r['rtt_min_ms'], r['rtt_max_ms'] = stats(replies)
    r['rtt_attempts'], r['rtt_replies'] = len(attempts), len(replies)
    r['rtt_loss_pct'] = 100 * (len(attempts) - len(replies)) / len(attempts) if attempts else None
    return r


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.record_dir = self.directory / 'records'
        self.record_dir.mkdir(parents=True, exist_ok=True)
        self.records = {p.stem: json.loads(p.read_text(encoding='utf-8')) for p in self.record_dir.glob('*.json')}
        self.export()

    def begin(self, record):
        ident = record.get('test_id', '')
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', ident):
            raise ValueError('Invalid test_id')
        if record.get('device') not in ('esp32', 'macbook'):
            raise ValueError('Invalid device')
        if ident in self.records:
            raise ValueError('Duplicate test ID')
        initial = {'timestamp_utc': datetime.now(timezone.utc).isoformat(),
                   'status': 'pending', 'report_status': 'pending', 'target_bytes': PAYLOAD_BYTES,
                   'bytes_received': None, 'duration_s': None, 'transfer_complete': None,
                   'rtt_phase': 'before_transfer', 'rtt_samples': [], 'rssi_samples': []}
        initial.update(record)
        atomic_json(self.record_dir / f'{ident}.json', initial)
        self.records[ident] = initial
        self.export()

    def update(self, ident, changes):
        record = {**self.records[ident], **changes}
        record = summarize(record)
        atomic_json(self.record_dir / f'{ident}.json', record)
        self.records[ident] = record
        self.export()
        return record

    def export(self):
        grouped = defaultdict(list)
        for r in self.records.values():
            grouped[r['device']].append(summarize(r))
        for device in ('macbook', 'esp32'):
            out = io.StringIO(newline='')
            writer = csv.DictWriter(out, fieldnames=COLUMNS, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(safe_csv(row) for row in grouped[device])
            atomic_text(self.directory / f'{device}_pengujian.csv', out.getvalue())
        for name, cols in [('rssi', ['elapsed_ms', 'rssi_dbm', 'reason', 'ssid', 'bssid', 'interface', 'source']),
                           ('rtt', ['seq', 'rtt_ms', 'reason'])]:
            out = io.StringIO(newline='')
            writer = csv.DictWriter(out, fieldnames=['test_id', 'device', 'distance_m', 'repetition'] + cols,
                                    extrasaction='ignore')
            writer.writeheader()
            for r in self.records.values():
                for sample in r.get(name + '_samples', []):
                    row = {k: r.get(k) for k in ('test_id', 'device', 'distance_m', 'repetition')}
                    writer.writerow(safe_csv({**row, **sample}))
            atomic_text(self.directory / f'sampel_{name}.csv', out.getvalue())
        summaries = {}
        failures = {'timeout', 'transfer_incomplete', 'connection_disconnected', 'report_timeout'}
        for device, rows in grouped.items():
            successes = [r['distance_m'] for r in rows if r.get('status') == 'success']
            failed = [r['distance_m'] for r in rows if r.get('status') in failures]
            confirmed = []
            by_distance = defaultdict(list)
            for r in rows:
                by_distance[r.get('distance_m')].append(r)
            for dist, trials in by_distance.items():
                receiver_failures = [r for r in trials if r.get('report_status') == 'received' and r.get('status') in failures]
                if len(receiver_failures) >= 2 and not any(r.get('status') == 'success' for r in trials):
                    confirmed.append(dist)
            summaries[device] = {'last_success_distance_m': max(successes, default=None),
                                 'first_observed_failure_distance_m': min(failed, default=None),
                                 'first_confirmed_failure_distance_m': min(confirmed, default=None),
                                 'tests': len(rows),
                                 'confirmation_rule': '>=2 receiver-confirmed failures and no success at that distance'}
        atomic_json(self.directory / 'ringkasan.json', summaries)
