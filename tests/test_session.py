import json
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from wifi_lab.controller import Controller, validate_result
from wifi_lab.companion import PendingQueue, serve
from wifi_lab.protocol import Wire, PAYLOAD_BYTES, ProtocolError
from wifi_lab.storage import Store


class SessionTests(unittest.TestCase):
    def test_real_tcp_ten_mb_and_pending_cleared_after_ack(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store = Store(root / 'results')
            controller = Controller(store, 'a' * 32, 'lab')
            listener = socket.socket()
            listener.bind(('127.0.0.1', 0))
            listener.listen(1)
            errors = []
            queue = PendingQueue(root / 'pending')
            def client():
                try:
                    with socket.create_connection(listener.getsockname()) as s:
                        serve(Wire(s), 'a' * 32, 'macbook', 'mac-test', 'lab', queue,
                              lambda: {'rssi_dbm': None, 'reason': 'TEST: no radio on loopback',
                                       'ssid': 'lab', 'bssid': 'test-only'}, once=True)
                except Exception as exc:
                    errors.append(exc)
            thread = threading.Thread(target=client)
            thread.start()
            conn, _ = listener.accept()
            with conn:
                wire = Wire(conn)
                peer = controller.handshake(wire)
                r = controller.run_trial(wire, peer, 1, 1, 5, rtt_count=3)
            thread.join(5)
            listener.close()
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(r['status'], 'success')
            self.assertEqual(r['bytes_received'], PAYLOAD_BYTES)
            self.assertEqual(r['rtt_replies'], 3)
            self.assertEqual(r['rssi_samples_count'], 0)
            self.assertGreater(r['throughput_mbps'], 0)
            self.assertEqual(queue.items(), [])

    def test_recovered_result_updates_existing_id(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d))
            store.begin({'test_id': 'recover', 'device': 'esp32', 'receiver_id': 'esp-test',
                         'ssid': 'lab', 'distance_m': 1, 'repetition': 1, 'timeout_s': 60})
            controller = Controller(store, 'a' * 32, 'lab')
            frame = {'type': 'result', 'test_id': 'recover', 'device': 'esp32', 'receiver_id': 'esp-test',
                     'ssid': 'lab', 'bssid': 'aa', 'result': {'bytes_received': 25, 'duration_s': 1,
                     'status': 'timeout', 'transfer_complete': False, 'rssi_samples': [], 'rssi_reason': 'unavailable'}}
            controller.accept_result(frame, {'device': 'esp32', 'receiver_id': 'esp-test'})
            controller.accept_result(frame, {'device': 'esp32', 'receiver_id': 'esp-test'})
            self.assertEqual(len(store.records), 1)
            self.assertEqual(store.records['recover']['report_status'], 'received')
            self.assertEqual(store.records['recover']['bytes_received'], 25)

    def test_result_validation_rejects_inconsistent_or_foreign_data(self):
        record = {'target_bytes': PAYLOAD_BYTES, 'timeout_s': 60}
        for bad in [
            {'bytes_received': 10, 'duration_s': 1, 'status': 'success', 'transfer_complete': True},
            {'bytes_received': -1, 'duration_s': 1, 'status': 'timeout', 'transfer_complete': False},
            {'bytes_received': 0, 'duration_s': float('nan'), 'status': 'timeout', 'transfer_complete': False},
            {'bytes_received': 0, 'duration_s': 1, 'status': [], 'transfer_complete': False},
        ]:
            with self.assertRaises(ProtocolError):
                validate_result(bad, record)

    def test_foreign_receiver_cannot_overwrite_existing_trial(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d))
            store.begin({'test_id': 'abc', 'device': 'esp32', 'receiver_id': 'esp-original',
                         'ssid': 'lab', 'distance_m': 1})
            controller = Controller(store, 'a' * 32, 'lab')
            report = {'type': 'result', 'test_id': 'abc', 'device': 'esp32',
                      'receiver_id': 'esp-foreign', 'ssid': 'lab'}
            with self.assertRaises(ProtocolError):
                controller.accept_result(report, {'device': 'esp32', 'receiver_id': 'esp-foreign'})
            self.assertEqual(store.records['abc']['status'], 'pending')

    def test_pending_queue_survives_restart(self):
        with tempfile.TemporaryDirectory() as d:
            q = PendingQueue(Path(d))
            q.put({'type': 'result', 'test_id': 'abc', 'result': {'bytes_received': 4}})
            self.assertEqual(PendingQueue(Path(d)).items()[0]['test_id'], 'abc')

    def test_malformed_tokens_rejected_without_crashing_listener(self):
        with tempfile.TemporaryDirectory() as d:
            controller = Controller(Store(Path(d)), 'a' * 32, 'lab')
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                listener.listen(1)
                for token in ['é', [], None, 'z' * 32, 'a' * 1000, 'b' * 32, 'a' * 32]:
                    with socket.create_connection(listener.getsockname()) as client:
                        conn, _ = listener.accept()
                        with conn:
                            Wire(client).send({'type': 'hello', 'protocol': 1, 'token': token,
                                               'device': 'esp32', 'receiver_id': 'esp-test',
                                               'ssid': 'lab', 'pending_count': 0})
                            if token == 'a' * 32:
                                self.assertEqual(controller.handshake(Wire(conn))['device'], 'esp32')
                            else:
                                with self.assertRaises(ProtocolError):
                                    controller.handshake(Wire(conn))

    def test_unreachable_attempt_has_no_invented_receiver_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(Path(d))
            controller = Controller(store, 'a' * 32, 'lab')
            r = controller.record_unreachable({'device': 'esp32', 'receiver_id': 'esp-test'}, 12, 2, 60)
            self.assertEqual(r['distance_m'], 12)
            self.assertEqual(r['status'], 'connection_disconnected')
            self.assertIsNone(r['bytes_received'])
            self.assertIsNone(r.get('throughput_mbps'))


if __name__ == '__main__':
    unittest.main()
