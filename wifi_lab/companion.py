"""macOS receiver; does not fabricate RSSI when native access is unavailable."""
import argparse
import getpass
import json
import re
import socket
import time
import uuid
from pathlib import Path

from .protocol import Wire, expect, ProtocolError, PAYLOAD_BYTES, PORT
from .receiver import receive_payload
from .storage import atomic_json


class PendingQueue:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def items(self):
        return [json.loads(p.read_text(encoding='utf-8')) for p in sorted(self.directory.glob('*.json'))]

    def put(self, frame):
        ident = frame['test_id']
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', ident):
            raise ProtocolError('Unsafe test ID')
        atomic_json(self.directory / f'{ident}.json', frame)

    def ack(self, ident):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', ident):
            raise ProtocolError('Unsafe ACK ID')
        (self.directory / f'{ident}.json').unlink(missing_ok=True)


def serve(wire, token, device, receiver_id, ssid, pending, read_rssi, once=False):
    queued = pending.items()
    if len(queued) > 16:
        raise ProtocolError('Too many pending reports; recover original session first')
    wire.send({'type': 'hello', 'protocol': 1, 'token': token, 'device': device,
               'receiver_id': receiver_id, 'ssid': ssid, 'pending_count': len(queued)})
    expect(wire, 'welcome', time.monotonic() + 10)
    for frame in queued:
        wire.send(frame)
        expect(wire, 'ack', time.monotonic() + 10, test_id=frame['test_id'])
        pending.ack(frame['test_id'])
    while True:
        try:
            request = wire.read(time.monotonic() + 1)
        except TimeoutError:
            continue
        if request.get('type') != 'start':
            raise ProtocolError('Expected start')
        ident = request.get('test_id', '')
        if not isinstance(ident, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', ident):
            raise ProtocolError('Invalid test ID')
        timeout = request.get('timeout_s')
        if request.get('target_bytes') != PAYLOAD_BYTES or not isinstance(timeout, (int, float)) or not 0 < timeout <= 600:
            raise ProtocolError('Invalid experiment configuration')
        print(f'Uji {ident}: {request.get("distance_m")} m / ulang {request.get("repetition")}', flush=True)
        result = None
        try:
            wire.send({'type': 'ready', 'test_id': ident})
            while True:
                frame = wire.read(time.monotonic() + 650)
                if frame.get('test_id') != ident:
                    raise ProtocolError('Wrong test ID')
                if frame.get('type') == 'echo':
                    wire.send({'type': 'pong', 'test_id': ident, 'seq': frame.get('seq')})
                elif frame.get('type') == 'transfer':
                    if frame.get('target_bytes') != PAYLOAD_BYTES or frame.get('timeout_s') != timeout:
                        raise ProtocolError('Changed transfer parameters')
                    result = receive_payload(wire, PAYLOAD_BYTES, timeout, read_rssi,
                                             ready=lambda: wire.send({'type': 'payload_ready', 'test_id': ident}))
                    break
                else:
                    raise ProtocolError('Unexpected frame')
        except (OSError, EOFError, ProtocolError) as exc:
            result = {'bytes_received': 0, 'duration_s': None, 'transfer_complete': False,
                      'status': 'connection_disconnected', 'before_payload': True,
                      'failure_reason': str(exc), 'rssi_samples': [], 'rssi_reason': 'Payload did not start'}
        # Metadata comes from the same adapter used for RSSI, never Windows WLAN.
        try:
            metadata = read_rssi()
        except Exception:
            metadata = {}
        report = {'type': 'result', 'test_id': ident, 'device': device, 'receiver_id': receiver_id,
                  'ssid': ssid, 'bssid': metadata.get('bssid', ''), 'result': result}
        pending.put(report)  # durable before attempting to deliver
        print(f'Result: {result["status"]}, {result["bytes_received"]} byte; disimpan lokal.', flush=True)
        wire.send(report)
        expect(wire, 'ack', time.monotonic() + 15, test_id=ident)
        pending.ack(ident)
        if once:
            return
        if result['status'] != 'success':
            raise ConnectionError('Trial failed; reconnect for a clean stream')


class NativeRSSI:
    def __init__(self, path, ssid):
        self.path, self.ssid = Path(path), ssid
        self.last_native_sample = None

    def __call__(self):
        try:
            sample = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            return {'rssi_dbm': None, 'reason': f'Native helper unavailable: {exc}', 'source': 'CoreWLAN'}
        value = {'source': 'CoreWLAN', 'ssid': sample.get('ssid', ''), 'bssid': sample.get('bssid', ''),
                 'interface': sample.get('interface', ''), 'rssi_dbm': sample.get('rssi_dbm'),
                 'reason': sample.get('reason', '')}
        timestamp = sample.get('timestamp', 0)
        if not isinstance(timestamp, (int, float)) or not 0 <= time.time() - timestamp <= 2:
            value.update(rssi_dbm=None, reason='Native helper sample stale or invalid clock')
        elif sample.get('ssid') != self.ssid:
            value.update(rssi_dbm=None, reason=(value['reason'] + '; ' if value['reason'] else '') +
                         'Native helper not connected to the expected Windows SSID')
        elif timestamp == self.last_native_sample:
            value.update(rssi_dbm=None, reason='No new native RSSI sample since previous poll')
        self.last_native_sample = timestamp
        return value


def main():
    p = argparse.ArgumentParser(description='MacBook receiver for Windows Wi-Fi experiment')
    p.add_argument('--server', default='192.168.137.1')
    p.add_argument('--port', type=int, default=PORT)
    p.add_argument('--ssid', required=True, help='Expected Windows hotspot SSID')
    p.add_argument('--rssi-file', type=Path, default=Path('macos/build/rssi.json'))
    p.add_argument('--pending-dir', type=Path, default=Path('pending/macbook'))
    args = p.parse_args()
    token = getpass.getpass('Token sesi dari Windows: ').strip()
    queue = PendingQueue(args.pending_dir)
    identity = args.pending_dir / 'receiver-id.txt'
    if not identity.exists():
        identity.write_text('mac-' + uuid.uuid4().hex[:16], encoding='utf-8')
    receiver_id = identity.read_text(encoding='utf-8').strip()
    rssi = NativeRSSI(args.rssi_file, args.ssid)
    print('Hubungkan Wi-Fi Mac ke hotspot Windows, bukan jaringan lain. Ctrl+C untuk berhenti.')
    print('RSSI awal:', rssi())
    try:
        while True:
            try:
                with socket.create_connection((args.server, args.port), timeout=10) as sock:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    serve(Wire(sock), token, 'macbook', receiver_id, args.ssid, queue, rssi)
            except (OSError, EOFError, ProtocolError) as exc:
                print(f'Koneksi: {exc}. Laporan tertunda tidak dihapus; mencoba ulang 3 detik.', flush=True)
                time.sleep(3)
    except KeyboardInterrupt:
        print('\nBerhenti; laporan tertunda tetap tersimpan.')


if __name__ == '__main__':
    main()
