import math
import time


def receive_payload(wire, target, timeout_s, read_rssi, ready=None):
    """Time reception, not sender writes. Keep payload out of permanent storage."""
    if not isinstance(target, int) or not 1 <= target <= 10_000_000:
        raise ValueError('Invalid target byte count')
    if not math.isfinite(timeout_s) or not 0 < timeout_s <= 600:
        raise ValueError('Invalid transfer timeout')
    samples = []
    count = 0
    status, reason = 'success', ''
    interval = max(.25, timeout_s / 240)
    if ready:
        ready()
    start_ns = time.perf_counter_ns()
    start = time.monotonic()
    deadline = start + timeout_s
    next_sample = start
    while count < target:
        now = time.monotonic()
        if now >= next_sample:
            try:
                sample = dict(read_rssi())
            except Exception as exc:
                sample = {'rssi_dbm': None, 'reason': f'RSSI read error: {exc}'}
            value = sample.get('rssi_dbm')
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not -127 <= value < 0:
                sample['rssi_dbm'] = None
                sample['reason'] = sample.get('reason') or 'No valid native dBm reading'
            sample['elapsed_ms'] = (time.perf_counter_ns() - start_ns) / 1e6
            samples.append(sample)
            next_sample = now + interval
        if time.monotonic() >= deadline:
            status, reason = 'timeout', 'Total payload deadline exceeded'
            break
        try:
            data = wire.recv(min(65536, target - count), min(deadline, next_sample))
            if not data:
                status, reason = 'transfer_incomplete', 'TCP EOF before target byte count'
                break
            count += len(data)
        except TimeoutError:
            continue  # Sample RSSI on schedule; never extend the total deadline.
        except OSError as exc:
            status, reason = 'connection_disconnected', str(exc)
            break
        except Exception as exc:
            status, reason = 'program_error', f'{type(exc).__name__}: {exc}'
            break
    duration = (time.perf_counter_ns() - start_ns) / 1e9
    missing = sorted({s.get('reason', 'Unavailable') for s in samples if s.get('rssi_dbm') is None})
    return {'bytes_received': count, 'duration_s': duration, 'status': status,
            'failure_reason': reason, 'transfer_complete': count == target,
            'rssi_samples': samples, 'rssi_reason': '; '.join(missing),
            'measurement_source': 'receiver', 'timer': 'perf_counter_ns'}
