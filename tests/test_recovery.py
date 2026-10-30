import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from wifi_lab.companion import PendingQueue, serve
from wifi_lab.controller import Controller
from wifi_lab.protocol import Wire, expect, PAYLOAD_BYTES
from wifi_lab.receiver import receive_payload
from wifi_lab.storage import Store

TOKEN = 'a' * 32


def hello(wire, pending=0):
    wire.send({'type': 'hello', 'protocol': 1, 'token': TOKEN, 'device': 'macbook',
               'receiver_id': 'mac-test', 'ssid': 'lab', 'pending_count': pending})
    expect(wire, 'welcome', time.monotonic() + 2)


class RecoveryTests(unittest.TestCase):
    def test_disconnect_after_echo_still_counts_attempt(self):
        with tempfile.TemporaryDirectory() as d:
            controller = Controller(Store(Path(d)), TOKEN, 'lab')
            a, b = socket.socketpair()
            errors = []
            def client():
                try:
                    with b:
                        wire = Wire(b)
                        hello(wire)
                        start = expect(wire, 'start', time.monotonic() + 2)
                        wire.send({'type': 'ready', 'test_id': start['test_id']})
                        expect(wire, 'echo', time.monotonic() + 2)
                except Exception as exc:
                    errors.append(exc)
            t = threading.Thread(target=client)
            t.start()
            with a:
                wire = Wire(a)
                peer = controller.handshake(wire)
                result = controller.run_trial(wire, peer, 1, 1, 3)
            t.join(5)
            self.assertEqual(errors, [])
            self.assertEqual(result['rtt_attempts'], 1)
            self.assertEqual(result['rtt_replies'], 0)
            self.assertEqual(result['rtt_loss_pct'], 100)

    def test_late_pong_does_not_become_next_sequence(self):
        with tempfile.TemporaryDirectory() as d:
            controller = Controller(Store(Path(d)), TOKEN, 'lab', rtt_timeout=.05)
            a, b = socket.socketpair()
            errors = []
            def client():
                try:
                    with b:
                        wire = Wire(b)
                        hello(wire)
                        request = expect(wire, 'start', time.monotonic() + 2)
                        ident = request['test_id']
                        wire.send({'type': 'ready', 'test_id': ident})
                        for seq in range(3):
                            expect(wire, 'echo', time.monotonic() + 2, seq=seq)
                            if seq == 0:
                                time.sleep(.075)
                            wire.send({'type': 'pong', 'test_id': ident, 'seq': seq})
                        expect(wire, 'transfer', time.monotonic() + 2)
                        r = receive_payload(wire, PAYLOAD_BYTES, 3, lambda: {'reason': 'TEST no radio'},
                                            ready=lambda: wire.send({'type': 'payload_ready', 'test_id': ident}))
                        wire.send({'type': 'result', 'test_id': ident, 'device': 'macbook',
                                   'receiver_id': 'mac-test', 'ssid': 'lab', 'bssid': '', 'result': r})
                        expect(wire, 'ack', time.monotonic() + 2, test_id=ident)
                except Exception as exc:
                    errors.append(exc)
            t = threading.Thread(target=client)
            t.start()
            with a:
                wire = Wire(a)
                peer = controller.handshake(wire)
                result = controller.run_trial(wire, peer, 1, 1, 3, rtt_count=3)
            t.join(5)
            self.assertEqual(errors, [])
            self.assertEqual(result['status'], 'success')
            samples = result['rtt_samples']
            self.assertIsNone(samples[0]['rtt_ms'])
            self.assertIsNotNone(samples[1]['rtt_ms'])
            self.assertIsNotNone(samples[2]['rtt_ms'])
            self.assertAlmostEqual(result['rtt_loss_pct'], 100 / 3)

    def test_lost_ack_retains_pending_and_recovers_without_duplicate(self):
        class DropAckWire(Wire):
            def send(self, frame, timeout=5):
                if frame.get('type') == 'ack':
                    self.sock.shutdown(socket.SHUT_RDWR)
                    raise ConnectionError('TEST injected disconnect before ACK')
                return super().send(frame, timeout)

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            controller = Controller(Store(root / 'results'), TOKEN, 'lab')
            q = PendingQueue(root / 'pending')
            a, b = socket.socketpair()
            errors = []
            def client():
                try:
                    with b:
                        serve(Wire(b), TOKEN, 'macbook', 'mac-test', 'lab', q,
                              lambda: {'reason': 'TEST no radio'}, once=True)
                except (EOFError, OSError) as exc:
                    errors.append(exc)
            t = threading.Thread(target=client)
            t.start()
            with a:
                wire = DropAckWire(a)
                peer = controller.handshake(wire)
                result = controller.run_trial(wire, peer, 1, 1, 3, rtt_count=1)
            t.join(5)
            self.assertFalse(t.is_alive())
            self.assertEqual(result['status'], 'success')
            self.assertEqual(len(q.items()), 1)
            self.assertEqual(len(errors), 1)
            a, b = socket.socketpair()
            recovery_errors = []
            def recovery():
                try:
                    with b:
                        wire = Wire(b)
                        hello(wire, 1)
                        wire.send(q.items()[0])
                        expect(wire, 'ack', time.monotonic() + 2, test_id=result['test_id'])
                        q.ack(result['test_id'])
                except Exception as exc:
                    recovery_errors.append(exc)
            t = threading.Thread(target=recovery)
            t.start()
            with a:
                controller.handshake(Wire(a))
            t.join(5)
            self.assertEqual(recovery_errors, [])
            self.assertEqual(q.items(), [])
            self.assertEqual(len(controller.store.records), 1)
            self.assertEqual(controller.store.records[result['test_id']]['bytes_received'], PAYLOAD_BYTES)


if __name__ == '__main__':
    unittest.main()
