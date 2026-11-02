"""Optional receiver identity; missing hardware facts are never guessed."""
import os
import platform
import socket
import subprocess


TEXT_FIELDS = ('name', 'model', 'os', 'firmware', 'architecture', 'mac_address', 'ip_address', 'bssid')
NUMBER_FIELDS = ('cpu_mhz', 'cpu_cores', 'flash_bytes', 'ram_bytes', 'heap_bytes', 'psram_bytes', 'rssi_dbm')


def clean_device_info(value):
    if not isinstance(value, dict):
        return {}
    info = {}
    for key in TEXT_FIELDS:
        text = value.get(key)
        if isinstance(text, str):
            info[key] = ''.join(c for c in text[:200] if c.isprintable())
    for key in NUMBER_FIELDS:
        number = value.get(key)
        lower, upper = (-127, -1) if key == 'rssi_dbm' else (0, 2 ** 60)
        if type(number) is int and lower <= number <= upper:
            info[key] = number
    return info


def mac_device_info():
    info = {'name': socket.gethostname(), 'model': platform.machine(),
            'architecture': platform.machine(), 'os': platform.platform(),
            'firmware': 'wifi-distance-lab protocol 1 / Python ' + platform.python_version(),
            'cpu_cores': os.cpu_count()}
    if platform.system() == 'Darwin':
        for field, key in (('model', 'hw.model'), ('ram_bytes', 'hw.memsize')):
            try:
                result = subprocess.run(['/usr/sbin/sysctl', '-n', key], capture_output=True,
                                        text=True, timeout=2, check=True).stdout.strip()
                info[field] = int(result) if field == 'ram_bytes' else result
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
    return clean_device_info(info)


def show_device_info(info):
    for key in TEXT_FIELDS + NUMBER_FIELDS:
        value = info.get(key)
        if key.endswith('_bytes') and value is not None:
            value = f'{value} byte ({value / 1048576:.1f} MiB)'
        print(f'  {key}: {value if value is not None and value != "" else "tidak tersedia"}')
