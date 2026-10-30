import csv
import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from wifi_lab.protocol import Wire, ProtocolError
from wifi_lab.receiver import receive_payload
from wifi_lab.storage import Store, summarize


class ProtocolTests(unittest.TestCase):
    def test_fragmented_json_does_not_consume_payload(self):
        a, b = socket.socketpair()
        with a, b:
            wire = Wire(a)
            def send():
                for chunk in [b'{"type":', b'"transfer"}\nabc', b'def']:
                    b.sendall(chunk)
            t = threading.Thread(target=send)
            t.start()
            self.assertEqual(wire.read(time.monotonic() + 2), {"type": "transfer"})
            received = b''
            while len(received) < 6:
                received += wire.recv(6 - len(received), time.monotonic() + 2)
            self.assertEqual(received, b'abcdef')
            t.join()

    def test_oversized_and_nonobject_json_rejected(self):
        for payload in [b'[]\n', b'x' * 131073]:
            a, b = socket.socketpair()
            with a, b:
                t = threading.Thread(target=lambda: b.sendall(payload))
                t.start()
                with self.assertRaises(ProtocolError):
                    Wire(a).read(time.monotonic() + 2)
                t.join()


class ReceiverTests(unittest.TestCase):
    def test_slow_trickle_does_not_reset_total_timeout(self):
        a, b = socket.socketpair()
        stop = threading.Event()
        def trickle():
            while not stop.wait(.01):
                b.sendall(b'x')
        with a, b:
            t = threading.Thread(target=trickle)
            t.start()
            r = receive_payload(Wire(a), 100, .06, lambda: {'rssi_dbm': -50})
            stop.set()
            t.join(1)
            self.assertEqual(r['status'], 'timeout')
            self.assertGreater(r['bytes_received'], 0)
            self.assertLess(r['bytes_received'], 100)
            self.assertLess(r['duration_s'], .25)

    def test_exact_bytes_leaves_next_frame(self):
        a, b = socket.socketpair()
        with a, b:
            b.sendall(b'123456' + b'{"type":"next"}\n')
            wire = Wire(a)
            r = receive_payload(wire, 6, 1, lambda: {"rssi_dbm": -55, "ssid": "lab", "bssid": "aa"})
            self.assertEqual(r['bytes_received'], 6)
            self.assertEqual(r['status'], 'success')
            self.assertEqual(r['rssi_samples'][0]['rssi_dbm'], -55)
            self.assertEqual(wire.read(time.monotonic() + 1)['type'], 'next')

    def test_partial_timeout_retains_bytes(self):
        a, b = socket.socketpair()
        with a, b:
            b.sendall(b'abc')
            r = receive_payload(Wire(a), 10, .05, lambda: {"reason": "unavailable"})
            self.assertEqual((r['status'], r['bytes_received']), ('timeout', 3))
            self.assertLess(r['duration_s'], .3)

    def test_eof_incomplete(self):
        a, b = socket.socketpair()
        with a, b:
            b.sendall(b'abc')
            b.shutdown(socket.SHUT_WR)
            r = receive_payload(Wire(a), 10, 1, lambda: {"reason": "no permission"})
            self.assertEqual(r['status'], 'transfer_incomplete')
            self.assertEqual(r['bytes_received'], 3)


class StorageTests(unittest.TestCase):
    def test_formula_and_missing_rssi(self):
        r = summarize({'bytes_received': 10_000_000, 'duration_s': 2,
                       'rssi_samples': [], 'rssi_reason': 'permission denied',
                       'rtt_samples': [{'seq': 0, 'rtt_ms': 5}, {'seq': 1, 'rtt_ms': None}]})
        self.assertEqual(r['throughput_mbps'], 40)
        self.assertIsNone(r['rssi_mean_dbm'])
        self.assertEqual(r['rtt_loss_pct'], 50)
        self.assertEqual(r['rtt_replies'], 1)

    def test_rssi_statistics_ignore_unavailable_samples(self):
        r = summarize({'rssi_samples': [{'rssi_dbm': -40}, {'rssi_dbm': -60}, {'rssi_dbm': None}]})
        self.assertEqual(r['rssi_mean_dbm'], -50)
        self.assertEqual(r['rssi_min_dbm'], -60)
        self.assertEqual(r['rssi_max_dbm'], -40)
        self.assertEqual(r['rssi_samples_count'], 2)
        self.assertIsNone(r['rtt_loss_pct'])

    def test_atomic_upsert_and_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d))
            s.begin({'test_id': 'abc', 'device': 'esp32', 'distance_m': 1, 'repetition': 1})
            s.update('abc', {'bytes_received': 3, 'duration_s': 1, 'status': 'timeout'})
            s.update('abc', {'bytes_received': 3, 'duration_s': 1, 'status': 'timeout'})
            s = Store(Path(d))
            self.assertEqual(s.records['abc']['bytes_received'], 3)
            with (Path(d) / 'esp32_pengujian.csv').open() as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['bytes_received'], '3')

    def test_path_traversal_id_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError):
                Store(Path(d)).begin({'test_id': '../escape', 'device': 'esp32'})

    def test_csv_untrusted_text_cannot_be_excel_formula(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d))
            store.begin({'test_id': 'abc', 'device': 'esp32', 'failure_reason': '=1+1'})
            with (Path(d) / 'esp32_pengujian.csv').open() as f:
                row = list(csv.DictReader(f))[0]
            self.assertEqual(row['failure_reason'], "'=1+1")

    def test_boundary_reports_observed_failure_not_invented(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d))
            for ident, dist, status in [('a', 1, 'success'), ('b', 2, 'timeout'), ('c', 2, 'success')]:
                s.begin({'test_id': ident, 'device': 'macbook', 'distance_m': dist,
                         'repetition': 1, 'status': status})
            summary = json.loads((Path(d) / 'ringkasan.json').read_text())['macbook']
            self.assertEqual(summary['last_success_distance_m'], 2)
            self.assertEqual(summary['first_observed_failure_distance_m'], 2)
            self.assertIsNone(summary['first_confirmed_failure_distance_m'])


if __name__ == '__main__':
    unittest.main()
