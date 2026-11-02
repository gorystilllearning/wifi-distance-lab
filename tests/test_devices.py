import json
import csv
import socket
import tempfile
import unittest
from pathlib import Path

from wifi_lab.controller import Controller
from wifi_lab.protocol import Wire
from wifi_lab.storage import Store


class DeviceDetailsTests(unittest.TestCase):
    def test_local_mac_details_have_a_name_os_and_architecture(self):
        from wifi_lab.devices import mac_device_info
        info = mac_device_info()
        for key in ('name', 'model', 'os', 'architecture', 'firmware'):
            self.assertTrue(info[key])
        self.assertGreater(info['cpu_cores'], 0)

    def handshake(self, root, info=None):
        store = Store(root)
        controller = Controller(store, 'a' * 32, 'lab')
        left, right = socket.socketpair()
        with left, right:
            hello = {'type': 'hello', 'protocol': 1, 'token': 'a' * 32, 'device': 'esp32',
                     'receiver_id': 'esp-test', 'ssid': 'lab', 'pending_count': 0}
            if info is not None:
                hello['device_info'] = info
            Wire(right).send(hello)
            peer = controller.handshake(Wire(left))
        return controller, peer

    def test_specs_are_saved_without_auth_token_and_copied_into_trials(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            controller, peer = self.handshake(root, {'model': 'ESP32-S3', 'flash_bytes': 16777216,
                                                    'psram_bytes': 0, 'token': 'must-not-save'})
            saved = json.loads((root / 'devices.json').read_text())['esp-test']
            self.assertEqual(saved['device_info'], {'model': 'ESP32-S3', 'flash_bytes': 16777216,
                                                   'psram_bytes': 0})
            self.assertNotIn('token', (root / 'devices.json').read_text())
            record = controller.record_unreachable(peer, 3, 1, 60)
            self.assertEqual(record['device_info']['model'], 'ESP32-S3')
            with (root / 'esp32_pengujian.csv').open() as f:
                self.assertEqual(next(csv.DictReader(f))['device_model'], 'ESP32-S3')

    def test_legacy_receiver_without_specs_still_connects(self):
        with tempfile.TemporaryDirectory() as d:
            _, peer = self.handshake(Path(d))
            self.assertEqual(peer['device_info'], {})

    def test_untrusted_specs_are_bounded_and_cannot_inject_terminal_controls(self):
        with tempfile.TemporaryDirectory() as d:
            _, peer = self.handshake(Path(d), {'name': '\x1b[31mBAD\nNAME', 'model': 'x' * 500,
                                              'flash_bytes': -1, 'ram_bytes': True,
                                              'cpu_cores': {'nested': 'not allowed'}})
            self.assertNotIn('\x1b', peer['device_info']['name'])
            self.assertNotIn('\n', peer['device_info']['name'])
            self.assertLessEqual(len(peer['device_info']['model']), 200)
            self.assertNotIn('flash_bytes', peer['device_info'])
            self.assertNotIn('ram_bytes', peer['device_info'])
            self.assertNotIn('cpu_cores', peer['device_info'])
