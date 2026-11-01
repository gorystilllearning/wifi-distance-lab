import csv
import importlib.util
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wifi_lab.plots import build_series, load_rows, plot_session
from wifi_lab.controller import refresh_plots
from wifi_lab.storage import COLUMNS


def write_fixture(directory, device, rows):
    path = directory / f'{device}_pengujian.csv'
    with path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for i, row in enumerate(rows):
            writer.writerow({'test_id': f'TEST-{i}', 'device': device, 'distance_m': 1,
                             'status': 'success', 'report_status': 'received', **row})
    return path


class PlotDataTests(unittest.TestCase):
    def test_success_mean_sample_std_and_failed_values_separate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_fixture(root, 'esp32', [
                {'throughput_mbps': 8}, {'throughput_mbps': 10}, {'throughput_mbps': 12},
                {'distance_m': 2, 'status': 'timeout', 'throughput_mbps': 2},
                {'distance_m': 3, 'status': 'report_timeout', 'report_status': 'awaiting_recovery'},
            ])
            series = build_series(load_rows(root), 'throughput_mbps', 'esp32')
            self.assertEqual(series['distance_m'], [1, 2, 3])
            self.assertEqual(series['mean'][0], 10)
            self.assertEqual(series['std'][0], 2)
            self.assertEqual(series['n'], [3, 0, 0])
            self.assertTrue(math.isnan(series['mean'][1]))
            self.assertEqual(series['failed'], [(2, 2)])
            self.assertEqual(series['failed_without_value'], [3])
            self.assertEqual(series['raw'], [(1, 8), (1, 10), (1, 12)])

    def test_blank_nan_infinity_and_invalid_metrics_are_not_zero(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_fixture(root, 'macbook', [
                {'rssi_mean_dbm': '', 'throughput_mbps': 'NaN', 'rtt_mean_ms': 'inf'},
                {'rssi_mean_dbm': 0, 'throughput_mbps': -1, 'rtt_mean_ms': -2},
                {'rssi_mean_dbm': -60, 'throughput_mbps': 0, 'rtt_mean_ms': 0},
            ])
            rows = load_rows(root)
            self.assertEqual(build_series(rows, 'rssi_mean_dbm', 'macbook')['raw'], [(1, -60)])
            self.assertEqual(build_series(rows, 'throughput_mbps', 'macbook')['raw'], [(1, 0)])
            self.assertEqual(build_series(rows, 'rtt_mean_ms', 'macbook')['raw'], [(1, 0)])

    def test_pending_records_and_other_devices_do_not_enter_means(self):
        rows = [{'device': 'macbook', 'distance_m': 1, 'status': 'pending', 'throughput_mbps': 99},
                {'device': 'esp32', 'distance_m': 1, 'status': 'success', 'throughput_mbps': 5}]
        self.assertEqual(build_series(rows, 'throughput_mbps', 'macbook')['raw'], [])
        self.assertEqual(build_series(rows, 'throughput_mbps', 'esp32')['mean'], [5])
        self.assertTrue(math.isnan(build_series(rows, 'throughput_mbps', 'esp32')['std'][0]))

    def test_nonexistent_folder_and_wrong_header_fail_clearly(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with self.assertRaises(ValueError):
                load_rows(root / 'missing')
            (root / 'esp32_pengujian.csv').write_text('a,b\n1,2\n')
            with self.assertRaisesRegex(ValueError, 'kolom'):
                load_rows(root)

    def test_automatic_plot_failure_does_not_raise_or_change_csv(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = write_fixture(root, 'esp32', [{'throughput_mbps': 10}])
            before = path.read_bytes()
            with patch('wifi_lab.controller.plot_session', side_effect=RuntimeError('TEST disk/plot failed')):
                with patch('builtins.print') as output:
                    self.assertFalse(refresh_plots(root))
            self.assertEqual(path.read_bytes(), before)
            self.assertTrue(output.called)

    def test_no_measurements_produces_no_fake_plot(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_fixture(root, 'esp32', [])
            self.assertEqual(plot_session(root), [])


@unittest.skipUnless(importlib.util.find_spec('matplotlib'), 'Optional Matplotlib not installed')
class PlotRenderTests(unittest.TestCase):
    def test_three_real_pngs_and_csv_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path = write_fixture(root, 'esp32', [
                {'rssi_mean_dbm': -50, 'throughput_mbps': 10, 'rtt_mean_ms': 5},
                {'distance_m': 2, 'status': 'timeout', 'rssi_mean_dbm': -80, 'throughput_mbps': 1},
                {'distance_m': 3, 'status': 'report_timeout'},
            ])
            write_fixture(root, 'macbook', [{'rssi_mean_dbm': -45, 'throughput_mbps': 25, 'rtt_mean_ms': 3}])
            before = path.read_bytes()
            images = plot_session(root)
            self.assertEqual({p.name for p in images}, {'jarak_rssi.png', 'jarak_throughput.png', 'jarak_rtt.png'})
            for path in images:
                self.assertEqual(path.read_bytes()[:8], b'\x89PNG\r\n\x1a\n')
                self.assertGreater(path.stat().st_size, 10000)
            self.assertEqual((root / 'esp32_pengujian.csv').read_bytes(), before)

    def test_only_missing_failed_metrics_can_render_without_making_zero_values(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_fixture(root, 'esp32', [{'status': 'connection_disconnected', 'report_status': 'not_available'}])
            self.assertEqual(len(plot_session(root)), 3)


if __name__ == '__main__':
    unittest.main()
