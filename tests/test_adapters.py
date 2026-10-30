import json
import tempfile
import time
import unittest
from pathlib import Path

from wifi_lab.companion import NativeRSSI


class AdapterTests(unittest.TestCase):
    def test_native_rssi_missing_stale_wrong_network_and_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'rssi.json'
            reader = NativeRSSI(path, 'lab')
            self.assertIsNone(reader()['rssi_dbm'])
            for extra in [{'timestamp': time.time() - 5, 'ssid': 'lab'},
                          {'timestamp': time.time(), 'ssid': 'other'}]:
                path.write_text(json.dumps({'rssi_dbm': -40, **extra}))
                self.assertIsNone(reader()['rssi_dbm'])
            path.write_text(json.dumps({'timestamp': time.time(), 'ssid': 'lab', 'bssid': 'aa', 'rssi_dbm': -60}))
            self.assertEqual(reader()['rssi_dbm'], -60)
            self.assertIsNone(reader()['rssi_dbm'])

    def test_native_permission_error_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'rssi.json'
            path.write_text(json.dumps({'timestamp': time.time(), 'ssid': '', 'rssi_dbm': None,
                                       'reason': 'Location permission denied'}))
            sample = NativeRSSI(path, 'lab')()
            self.assertIn('Location permission denied', sample['reason'])


if __name__ == '__main__':
    unittest.main()
