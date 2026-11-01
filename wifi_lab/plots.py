"""Optional offline Matplotlib PNGs from session CSVs; never changes measurements."""
import argparse
import csv
import math
import os
import statistics
import tempfile
from pathlib import Path

DEVICES = {'macbook': ('MacBook', '#2563eb'), 'esp32': ('ESP32-S3', '#c2410c')}
METRICS = {
    'rssi_mean_dbm': ('jarak_rssi.png', 'Jarak vs RSSI', 'RSSI rata-rata per uji (dBm)'),
    'throughput_mbps': ('jarak_throughput.png', 'Jarak vs throughput', 'Throughput payload aplikasi (Mbps)'),
    'rtt_mean_ms': ('jarak_rtt.png', 'Jarak vs RTT', 'RTT aplikasi sebelum transfer (ms)'),
}


def metric_number(value, metric):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if metric == 'rssi_mean_dbm':
        return number if -127 <= number < 0 else None
    return number if number >= 0 else None


def load_rows(directory):
    directory = Path(directory)
    if not directory.is_dir():
        raise ValueError('Folder sesi tidak ditemukan')
    rows = []
    found = False
    required = {'test_id', 'device', 'distance_m', 'status', 'report_status', *METRICS}
    for device in DEVICES:
        path = directory / f'{device}_pengujian.csv'
        if not path.exists():
            continue
        found = True
        with path.open(encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            if not required.issubset(reader.fieldnames or []):
                raise ValueError(f'{path.name}: kolom CSV tidak lengkap')
            for line, row in enumerate(reader, 2):
                try:
                    distance = int(row.get('distance_m', ''))
                except (ValueError, TypeError):
                    raise ValueError(f'{path.name}, baris {line}: jarak tidak valid') from None
                if distance < 1 or row.get('device') != device:
                    raise ValueError(f'{path.name}, baris {line}: jarak/perangkat tidak valid')
                row['distance_m'] = distance
                for metric in METRICS:
                    row[metric] = metric_number(row.get(metric), metric)
                rows.append(row)
    if not found:
        raise ValueError('Folder ini tidak memiliki CSV pengujian MacBook atau ESP32')
    return rows


def build_series(rows, metric, device):
    trials = [r for r in rows if r.get('device') == device and r.get('status') != 'pending']
    distances = sorted({r['distance_m'] for r in trials})
    means, deviations, counts = [], [], []
    raw, failed, missing = [], [], set()
    for distance in distances:
        values = []
        for trial in trials:
            if trial['distance_m'] != distance:
                continue
            value = metric_number(trial.get(metric), metric)
            if trial.get('status') == 'success':
                if value is not None:
                    values.append(value)
                    raw.append((distance, value))
            elif value is not None:
                failed.append((distance, value))
            else:
                missing.add(distance)
        counts.append(len(values))
        means.append(statistics.fmean(values) if values else math.nan)
        deviations.append(statistics.stdev(values) if len(values) >= 2 else math.nan)
    return {'distance_m': distances, 'mean': means, 'std': deviations, 'n': counts,
            'raw': raw, 'failed': failed, 'failed_without_value': sorted(missing)}


def plot_session(directory):
    directory = Path(directory)
    rows = load_rows(directory)
    if not any(r.get('status') != 'pending' for r in rows):
        return []
    # Lazy imports keep measurements working without this optional dependency.
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import MaxNLocator

    output = directory / 'grafik'
    output.mkdir(exist_ok=True)
    images = []
    simulated = any(str(r.get('test_id', '')).upper().startswith('SIMULASI') for r in rows)
    for metric, (filename, title, ylabel) in METRICS.items():
        fig = Figure(figsize=(11, 6.5), layout='constrained', facecolor='white')
        FigureCanvasAgg(fig)  # PNG only: never opens a GUI or blocks for window close.
        ax = fig.subplots()
        total_values = 0
        for device, (label, color) in DEVICES.items():
            series = build_series(rows, metric, device)
            if not series['distance_m']:
                continue
            if series['raw']:
                x, y = zip(*series['raw'])
                ax.scatter(x, y, color=color, alpha=.35, s=28, label=f'{label}: uji sukses')
                ax.errorbar(series['distance_m'], series['mean'], yerr=series['std'],
                            fmt='o-', color=color, capsize=4, linewidth=1.7, markersize=5,
                            label=f'{label}: mean +/- SD antarulangan')
                total_values += len(series['raw'])
            if series['failed']:
                x, y = zip(*series['failed'])
                ax.scatter(x, y, color=color, marker='x', s=70, linewidths=1.8,
                           label=f'{label}: uji gagal, nilai tersedia')
                total_values += len(series['failed'])
            if series['failed_without_value']:
                x = series['failed_without_value']
                ax.scatter(x, [1.02] * len(x), color=color, marker='x', s=60,
                           transform=ax.get_xaxis_transform(), clip_on=False,
                           label=f'{label}: gagal tanpa nilai (penanda di tepi)')
        ax.set_title(('SIMULASI / DATA CAMPURAN - BUKAN HASIL NYATA\n' if simulated else '') + title,
                     fontsize=15, pad=28)
        ax.set_xlabel('Jarak (m)')
        ax.set_ylabel(ylabel)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.grid(True, alpha=.22)
        ax.set_axisbelow(True)
        ax.spines[['top', 'right']].set_visible(False)
        distances = [r['distance_m'] for r in rows if r.get('status') != 'pending']
        ax.set_xlim(min(distances) - .4, max(distances) + .4)
        if metric != 'rssi_mean_dbm' and total_values:
            ax.set_ylim(bottom=0)
        if not total_values:
            ax.text(.5, .5, 'Belum ada nilai metrik valid.\nData kosong bukan nol.',
                    transform=ax.transAxes, ha='center', va='center', color='#555555')
            ax.set_yticks([])
        handles, _ = ax.get_legend_handles_labels()
        if handles:
            ax.legend(loc='best', fontsize=8, framealpha=.92)
        fig.supxlabel('Mean/SD hanya uji sukses dan nilai valid; SD sampel jika n >= 2.\n'
                      'x = uji gagal; penanda di tepi bukan nilai metrik. Tidak ada interpolasi data kosong.',
                      fontsize=9, color='#555555')
        destination = output / filename
        fd, temporary = tempfile.mkstemp(prefix=filename + '-', suffix='.tmp', dir=output)
        os.close(fd)
        try:
            fig.savefig(temporary, format='png', dpi=160)
            os.replace(temporary, destination)
            images.append(destination)
        finally:
            fig.clear()
            Path(temporary).unlink(missing_ok=True)
    return images


def main():
    parser = argparse.ArgumentParser(description='Buat ulang 3 grafik PNG dari CSV sesi tanpa mengulang eksperimen.')
    parser.add_argument('session', type=Path, help='Folder hasil sesi yang berisi CSV pengujian')
    args = parser.parse_args()
    try:
        images = plot_session(args.session)
    except ImportError:
        parser.exit(1, 'Matplotlib belum tersedia. Jalankan setup_grafik.bat dahulu.\n')
    except (OSError, ValueError) as exc:
        parser.exit(1, f'Grafik gagal: {exc}\n')
    if not images:
        print('Belum ada hasil uji selesai/gagal; tidak membuat grafik data buatan.')
    for image in images:
        print(image.resolve())


if __name__ == '__main__':
    main()
