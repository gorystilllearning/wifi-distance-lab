"""Windows coordinator. Uses only Python standard library."""
import argparse
import math
import re
import secrets
import socket
import time
import uuid
from datetime import datetime
from pathlib import Path

from .protocol import Wire, ProtocolError, expect, PAYLOAD_BYTES, PORT
from .storage import Store, atomic_json
from .plots import plot_session

RESULT_STATUSES = {'success', 'transfer_incomplete', 'timeout', 'connection_disconnected', 'program_error'}


def finite_number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def validate_result(result, record):
    if not isinstance(result, dict):
        raise ProtocolError('Missing result object')
    size = result.get('bytes_received')
    duration = result.get('duration_s')
    status = result.get('status')
    if type(size) is not int or not 0 <= size <= record['target_bytes']:
        raise ProtocolError('Invalid received byte count')
    if not isinstance(status, str) or status not in RESULT_STATUSES:
        raise ProtocolError('Invalid receiver status')
    if duration is None:
        if size != 0 or status == 'success' or not result.get('before_payload'):
            raise ProtocolError('Missing transfer duration')
    elif not finite_number(duration) or not 0 < duration <= record.get('timeout_s', 60) + 10:
        raise ProtocolError('Invalid transfer duration')
    complete = size == record['target_bytes']
    if result.get('transfer_complete') is not complete or (status == 'success') != complete:
        raise ProtocolError('Inconsistent completion status')
    samples = result.get('rssi_samples', [])
    if not isinstance(samples, list) or len(samples) > 512:
        raise ProtocolError('Invalid RSSI sample count')
    clean_samples = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise ProtocolError('Invalid RSSI sample')
        value, elapsed = sample.get('rssi_dbm'), sample.get('elapsed_ms')
        if value is not None and (not finite_number(value) or not -127 <= value < 0):
            raise ProtocolError('Invalid native RSSI')
        if elapsed is None or not finite_number(elapsed) or elapsed < 0 or (duration and elapsed > duration * 1000 + 100):
            raise ProtocolError('Invalid RSSI timestamp')
        clean_samples.append({k: sample[k] for k in
                              ('rssi_dbm', 'elapsed_ms', 'reason', 'ssid', 'bssid', 'interface', 'source') if k in sample})
    return {'bytes_received': size, 'duration_s': duration, 'status': status,
            'transfer_complete': complete, 'rssi_samples': clean_samples,
            'rssi_reason': str(result.get('rssi_reason', ''))[:1000],
            'failure_reason': str(result.get('failure_reason', ''))[:1000],
            'measurement_source': 'receiver', 'timer': str(result.get('timer', ''))[:100]}


class Controller:
    def __init__(self, store, token, ssid, report_timeout=10, rtt_timeout=1):
        self.store, self.token, self.ssid = store, token, ssid
        self.report_timeout, self.rtt_timeout = report_timeout, rtt_timeout

    def handshake(self, wire):
        hello = expect(wire, 'hello', time.monotonic() + 10)
        supplied_token = hello.get('token')
        if (not isinstance(supplied_token, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', supplied_token)
                or hello.get('protocol') != 1 or not secrets.compare_digest(supplied_token, self.token)):
            raise ProtocolError('Authentication/protocol mismatch')
        if hello.get('device') not in ('macbook', 'esp32') or hello.get('ssid') != self.ssid:
            raise ProtocolError('Wrong device or SSID')
        receiver_id = hello.get('receiver_id', '')
        if not isinstance(receiver_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', receiver_id):
            raise ProtocolError('Invalid receiver identity')
        pending = hello.get('pending_count', 0)
        if type(pending) is not int or not 0 <= pending <= 16:
            raise ProtocolError('Invalid pending count')
        wire.send({'type': 'welcome', 'protocol': 1})
        for _ in range(pending):
            report = expect(wire, 'result', time.monotonic() + 10)
            self.accept_result(report, hello)
            wire.send({'type': 'ack', 'test_id': report['test_id']})
        return hello

    def accept_result(self, frame, peer):
        ident = frame.get('test_id')
        if not isinstance(ident, str):
            raise ProtocolError('Invalid result ID')
        record = self.store.records.get(ident)
        if record is None:
            raise ProtocolError('Unknown test ID: restart Windows with --resume for its original session')
        for key in ('device', 'receiver_id'):
            if frame.get(key) != peer.get(key) or frame.get(key) != record.get(key):
                raise ProtocolError('Receiver identity mismatch')
        if frame.get('ssid') != self.ssid or frame.get('ssid') != record.get('ssid'):
            raise ProtocolError('Result belongs to another Wi-Fi SSID')
        changes = validate_result(frame.get('result'), record)
        for sample in changes['rssi_samples']:
            if sample.get('rssi_dbm') is not None and sample.get('ssid', frame.get('ssid')) != self.ssid:
                raise ProtocolError('RSSI sample belongs to another SSID')
            if peer['device'] == 'esp32':
                sample.setdefault('ssid', frame['ssid'])
                sample.setdefault('bssid', frame.get('bssid', ''))
                sample.setdefault('source', 'Arduino WiFi.RSSI / ESP-IDF station API')
                sample.setdefault('interface', 'STA')
        changes.update(report_status='received', bssid=str(frame.get('bssid', ''))[:100])
        # Persist JSON and CSV before ACK. Retrying a report replaces the same ID.
        return self.store.update(ident, changes)

    def record_unreachable(self, peer, distance, repetition, timeout_s):
        """Only connection failure is observed; receiver bytes remain unknown."""
        ident = uuid.uuid4().hex
        self.store.begin({'test_id': ident, 'session_id': self.store.directory.name,
                          'device': peer['device'], 'receiver_id': peer['receiver_id'],
                          'ssid': self.ssid, 'distance_m': distance, 'repetition': repetition,
                          'timeout_s': timeout_s, 'status': 'connection_disconnected',
                          'report_status': 'not_available', 'bytes_sent_socket': 0,
                          'failure_reason': 'Could not establish target connection; no payload initiated'})
        return self.store.records[ident]

    def run_trial(self, wire, peer, distance, repetition, timeout_s, rtt_count=20, progress=None):
        ident = uuid.uuid4().hex
        self.store.begin({'test_id': ident, 'session_id': self.store.directory.name,
                          'device': peer['device'], 'receiver_id': peer['receiver_id'],
                          'ssid': self.ssid, 'distance_m': distance, 'repetition': repetition,
                          'timeout_s': timeout_s})
        rtts = []
        sent = 0
        payload_started = False
        try:
            wire.send({'type': 'start', 'test_id': ident, 'target_bytes': PAYLOAD_BYTES,
                       'timeout_s': timeout_s, 'distance_m': distance, 'repetition': repetition})
            expect(wire, 'ready', time.monotonic() + 5, test_id=ident)
            for seq in range(rtt_count):
                started = time.perf_counter_ns()
                deadline = time.monotonic() + self.rtt_timeout
                sample = {'seq': seq, 'rtt_ms': None, 'reason': 'echo send/read failed'}
                rtts.append(sample)
                wire.send({'type': 'echo', 'test_id': ident, 'seq': seq}, self.rtt_timeout)
                sample['reason'] = 'echo timeout or connection lost before reply'
                try:
                    while True:
                        reply = wire.read(deadline)
                        if reply.get('type') != 'pong' or reply.get('test_id') != ident:
                            raise ProtocolError('Unexpected message during RTT')
                        if reply.get('seq') == seq:
                            sample.update(rtt_ms=(time.perf_counter_ns() - started) / 1e6, reason='')
                            break
                        # Discard late replies; do not assign them to the next echo.
                except TimeoutError:
                    pass
            self.store.update(ident, {'rtt_samples': rtts})
            wire.send({'type': 'transfer', 'test_id': ident, 'target_bytes': PAYLOAD_BYTES,
                       'timeout_s': timeout_s})
            # Drain late echo replies until receiver authorizes the payload phase.
            ready_deadline = time.monotonic() + 5
            while True:
                ready = wire.read(ready_deadline)
                if ready.get('type') == 'payload_ready' and ready.get('test_id') == ident:
                    break
                if ready.get('type') != 'pong' or ready.get('test_id') != ident:
                    raise ProtocolError('Expected payload_ready')
            payload_started = True
            deadline = time.monotonic() + timeout_s
            chunk = b'\xa5' * 65536
            last_progress = 0.0
            send_error = ''
            try:
                while sent < PAYLOAD_BYTES:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('Windows send deadline exceeded')
                    wire.sock.settimeout(remaining)
                    n = wire.sock.send(chunk[:min(len(chunk), PAYLOAD_BYTES - sent)])
                    if n == 0:
                        raise ConnectionError('Socket write returned zero')
                    sent += n
                    if progress and time.monotonic() - last_progress >= .5:
                        progress(sent)
                        last_progress = time.monotonic()
            except OSError as exc:
                send_error = str(exc)
                try:
                    wire.sock.shutdown(socket.SHUT_WR)
                except OSError:
                    pass
            self.store.update(ident, {'bytes_sent_socket': sent, 'controller_reason': send_error})
            # Receiver's deadline starts slightly earlier. Give its full deadline if
            # the sender failed early; allow an additional bounded report interval.
            report_deadline = max(time.monotonic(), deadline) + self.report_timeout
            frame = expect(wire, 'result', report_deadline, test_id=ident)
            record = self.accept_result(frame, peer)
            wire.send({'type': 'ack', 'test_id': ident})
            return record
        except (OSError, EOFError, ProtocolError) as exc:
            current = self.store.records[ident]
            if current.get('report_status') == 'received':
                return current  # ACK lost: receiver will safely resend this report.
            status = 'report_timeout' if payload_started else 'connection_disconnected'
            if isinstance(exc, ProtocolError):
                status = 'program_error'
            return self.store.update(ident, {'status': status, 'report_status': 'awaiting_recovery',
                                            'controller_reason': f'{type(exc).__name__}: {exc}',
                                            'bytes_sent_socket': sent, 'rtt_samples': rtts})


def positive_float(value):
    number = float(value)
    if not math.isfinite(number) or not 0 < number <= 600:
        raise argparse.ArgumentTypeError('Harus >0 dan <=600 detik')
    return number


def refresh_plots(directory):
    """Only called by CLI after measurement/ACK, never inside transfer or RTT."""
    try:
        images = plot_session(directory)
    except ImportError:
        print('Grafik belum dibuat: jalankan setup_grafik.bat. CSV tetap tersimpan; bisa dibuat ulang lewat grafik.bat.')
        return False
    except Exception as exc:
        print(f'Grafik gagal ({type(exc).__name__}: {exc}); hasil pengukuran tetap tersimpan. Coba grafik.bat nanti.')
        return False
    if images:
        print(f'Grafik PNG diperbarui: {images[0].parent.resolve()}')
    return bool(images)


def main():
    parser = argparse.ArgumentParser(description='Eksperimen Windows hotspot -> Mac/ESP. Tidak perlu internet.')
    parser.add_argument('--bind', default='192.168.137.1', help='IP adaptor hotspot Windows, bukan IP internet')
    parser.add_argument('--port', type=int, default=PORT)
    parser.add_argument('--ssid', help='Nama hotspot Windows persis')
    parser.add_argument('--timeout', type=positive_float, default=60)
    parser.add_argument('--rtt-timeout', type=positive_float, default=1)
    parser.add_argument('--report-timeout', type=positive_float, default=10)
    parser.add_argument('--connect-timeout', type=positive_float, default=15)
    parser.add_argument('--repetitions', type=int, choices=[1, 3], default=3)
    parser.add_argument('--resume', type=Path, help='Folder hasil sesi lama untuk sinkronisasi laporan tertunda')
    args = parser.parse_args()
    import json
    if args.resume:
        directory = args.resume
        config = json.loads((directory / 'session.json').read_text(encoding='utf-8'))
        ssid, token = config['ssid'], config['token']
    else:
        ssid = args.ssid or input('Nama hotspot Windows (SSID): ').strip()
        if not ssid or len(ssid.encode()) > 32:
            parser.error('SSID wajib diisi dan maksimal 32 byte')
        token = secrets.token_hex(16)
        directory = Path('hasil') / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:6])
        atomic_json(directory / 'session.json', {'ssid': ssid, 'token': token, 'protocol': 1})
    store = Store(directory)
    for ident, old in list(store.records.items()):
        if old.get('status') == 'pending':
            store.update(ident, {'status': 'report_timeout', 'report_status': 'awaiting_recovery',
                                 'controller_reason': 'Windows stopped before result was committed'})
    if store.records:
        refresh_plots(directory)
    controller = Controller(store, token, ssid, args.report_timeout, args.rtt_timeout)
    print(f'\nHasil: {directory.resolve()}\nHotspot: {ssid}\nServer: {args.bind}:{args.port}\nTOKEN SESI: {token}')
    print('Masukkan token ini di pendamping. Jangan upload token/kata sandi ke GitHub.')
    print('Windows tetap di tempat. Target penerima yang dipindahkan. Hubungkan hanya satu target.')
    print('Progres kirim adalah byte masuk socket, BUKAN bukti byte sudah diterima target.')
    print('Grafik PNG otomatis setelah uji jika Matplotlib terpasang (setup_grafik.bat); tidak membuka jendela.')
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind((args.bind, args.port))
        listener.listen(2)
        listener.settimeout(args.connect_timeout)
        conn = None
        peer = None
        try:
            while True:
                if conn is None:
                    print('\nMenunggu pendamping; Ctrl+C untuk berhenti (hasil tetap tersimpan).')
                    try:
                        conn, addr = listener.accept()
                        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                        wire = Wire(conn)
                        peer = controller.handshake(wire)
                        print(f'Terhubung: {peer["device"]} / {peer["receiver_id"]} / {addr[0]}')
                        print('Laporan tertunda sudah disinkronkan. ringkasan.json diperbarui.')
                        if store.records:
                            refresh_plots(directory)
                    except (OSError, EOFError, ProtocolError) as exc:
                        if conn:
                            conn.close()
                        conn = None
                        print(f'Belum tersambung: {exc}')
                        hint = '; f <jarak> catat gagal koneksi target terakhir' if peer else ''
                        action = input(f'Enter menunggu lagi; q keluar{hint}: ').strip().lower()
                        if action == 'q':
                            break
                        if peer and action.startswith('f '):
                            try:
                                failed_distance = int(action[2:].strip())
                                if failed_distance < 1:
                                    raise ValueError()
                            except ValueError:
                                print('Jarak harus bilangan bulat >=1.')
                                continue
                            previous = [r.get('repetition', 0) for r in store.records.values()
                                        if r['device'] == peer['device'] and r.get('distance_m') == failed_distance]
                            lost = controller.record_unreachable(peer, failed_distance, max(previous, default=0) + 1, args.timeout)
                            print(f'Gagal koneksi dicatat: {lost["test_id"]}; byte/RSSI/throughput tidak diketahui.')
                            refresh_plots(directory)
                        continue
                text = input('\nJarak meter bulat >=1; r=hubungkan ulang/ganti target; q=keluar: ').strip().lower()
                if text == 'q':
                    break
                if text == 'r':
                    conn.close()
                    conn = None
                    continue
                try:
                    distance = int(text)
                    if distance < 1:
                        raise ValueError()
                except ValueError:
                    print('Jarak harus bilangan bulat >=1, diukur secara fisik.')
                    continue
                previous = [r.get('repetition', 0) for r in store.records.values()
                            if r['device'] == peer['device'] and r.get('distance_m') == distance]
                first = max(previous, default=0) + 1
                for repetition in range(first, first + args.repetitions):
                    print(f'\n{peer["device"]}: {distance} m, pengulangan {repetition}; RTT lalu payload 10 MB...')
                    r = controller.run_trial(wire, peer, distance, repetition, args.timeout,
                                             progress=lambda n: print(f'  Dikirim ke socket: {n:,}/{PAYLOAD_BYTES:,} byte'))
                    def show(value, unit):
                        return 'tidak tersedia' if value is None else f'{value:.3f} {unit}'
                    print(f'ID: {r["test_id"]}\nStatus: {r["status"]}; laporan: {r["report_status"]}')
                    print(f'Byte diterima: {r.get("bytes_received")} / {PAYLOAD_BYTES}')
                    print(f'RSSI: {show(r.get("rssi_mean_dbm"), "dBm")} ({r.get("rssi_samples_count", 0)} sampel)')
                    print(f'Throughput: {show(r.get("throughput_mbps"), "Mbps")}; RTT: {show(r.get("rtt_mean_ms"), "ms")}')
                    if r.get('failure_reason') or r.get('controller_reason'):
                        print(r.get('failure_reason') or r.get('controller_reason'))
                    refresh_plots(directory)
                    if r['status'] != 'success':
                        print('Hasil gagal tetap disimpan. Sambungkan ulang; masukkan jarak sama untuk mencoba ulang.')
                        conn.close()
                        conn = None
                        break
        except (KeyboardInterrupt, EOFError):
            print('\nBerhenti. Hasil yang sudah dicatat tetap tersedia.')
        finally:
            if conn:
                conn.close()


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as exc:
        raise SystemExit(f'Gagal: {exc}. Periksa IP hotspot, firewall, file sesi, dan izin menulis hasil.')
