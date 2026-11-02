import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from wifi_lab import controller
from wifi_lab.storage import Store


class CliExportTests(unittest.TestCase):
    def run_cli(self, actions, status='success', reason='', accept_error=None, seeded=False,
                fail_reconnect=False):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'session.json').write_text(json.dumps({'ssid': 'lab', 'token': 'a' * 32}))
            peer = {'device': 'esp32', 'receiver_id': 'esp-test', 'ssid': 'lab'}
            exports = []
            observations = []
            listener = MagicMock()
            listener.__enter__.return_value = listener
            listener.accept.return_value = (MagicMock(), ('192.168.137.2', 1234))
            if seeded:
                Store(root).begin({'test_id': 'earlier', 'device': 'esp32', 'distance_m': 1})
            if fail_reconnect:
                listener.accept.side_effect = [listener.accept.return_value, ConnectionError('offline')]
            if accept_error:
                listener.accept.side_effect = accept_error

            def trial(instance, wire, peer, distance, repetition, timeout_s, **kwargs):
                ident = f'trial-{len(instance.store.records)}'
                instance.store.begin({'test_id': ident, 'device': 'esp32', 'receiver_id': 'esp-test',
                                      'ssid': 'lab', 'distance_m': distance, 'repetition': repetition})
                return instance.store.update(ident, {'status': status, 'controller_reason': reason})

            def render(directory):
                exports.append(sorted(Store(directory).records))
                return []

            commands = iter(actions)

            def read_input(prompt):
                observations.append(len(exports))
                action = next(commands)
                if isinstance(action, BaseException):
                    raise action
                return action

            with patch('sys.argv', ['controller', '--resume', str(root), '--repetitions', '1']), \
                    patch.object(controller.socket, 'socket', return_value=listener), \
                    patch.object(controller.Controller, 'handshake', return_value=peer), \
                    patch.object(controller.Controller, 'run_trial', new=trial), \
                    patch.object(controller, 'plot_session', side_effect=render), \
                    patch('builtins.input', side_effect=read_input), contextlib.redirect_stdout(io.StringIO()):
                controller.main()
            return exports, observations

    def test_successes_wait_for_manual_export_and_quit_exports_all_distances(self):
        exports, observations = self.run_cli(['1', '2', 'p', 'q'])
        self.assertEqual(observations, [0, 0, 0, 1])
        self.assertEqual(exports, [['trial-0', 'trial-1'], ['trial-0', 'trial-1']])

    def test_receiver_timeout_exports_before_waiting_for_reconnection(self):
        exports, observations = self.run_cli(['1', 'q'], status='timeout')
        self.assertEqual(observations, [0, 1])
        self.assertEqual(len(exports), 2)

    def test_controller_timeout_before_payload_also_exports(self):
        exports, observations = self.run_cli(['1', 'q'], status='connection_disconnected',
                                             reason='TimeoutError: timed out')
        self.assertEqual(observations, [0, 1])

    def test_manual_export_while_disconnected_stays_at_command_prompt(self):
        exports, observations = self.run_cli(['1', 'p', 'q'], status='connection_disconnected',
                                             fail_reconnect=True)
        self.assertEqual(observations, [0, 0, 1])
        self.assertEqual(len(exports), 2)

    def test_interrupt_exports_saved_trials(self):
        exports, observations = self.run_cli(['1', KeyboardInterrupt()])
        self.assertEqual(observations, [0, 0])
        self.assertEqual(exports, [['trial-0']])

    def test_empty_session_quit_does_not_render(self):
        exports, _ = self.run_cli(['q'], accept_error=TimeoutError('timed out'))
        self.assertEqual(exports, [])

    def test_connection_timeout_exports_prior_session_records(self):
        exports, observations = self.run_cli(['q'], seeded=True, accept_error=TimeoutError('timed out'))
        self.assertEqual(observations, [1])
        self.assertEqual(exports, [['earlier'], ['earlier']])

    def test_resume_and_reconnect_do_not_export_until_quit(self):
        exports, observations = self.run_cli(['r', 'q'], seeded=True)
        self.assertEqual(observations, [0, 0])
        self.assertEqual(exports, [['earlier']])
