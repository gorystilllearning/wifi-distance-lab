# Catatan validasi

Tidak ada hasil pengukuran radio nyata yang disertakan. `contoh_SIMULASI.csv`
adalah data buatan yang diberi label eksplisit, bukan keluaran eksperimen.

## Dapat diperiksa secara lokal
Hasil pemeriksaan pembuatan proyek: **24 tes lulus** melalui
`python3 -m unittest discover -s tests -v`; `compileall` dan CLI `--help` lulus.
Pemeriksaan dijalankan pada Python 3.15.2 di macOS, bukan di Windows.

- Python unittest: framing JSON/payload terfragmentasi, pembacaan parsial, timeout
  total, EOF parsial, rumus, CSV upsert/reopen, ID tidak aman, boundary campuran,
  helper RSSI tidak tersedia/stale/SSID salah/izin ditolak, pending persistence,
  transfer TCP loopback **10.000.000 byte**, laporan recovery dan validasi status,
  balasan RTT terlambat, putus sebelum ACK dan recovery tanpa duplikat, token
  Unicode/malformed, identitas asing, CSV formula injection, koneksi tidak tersedia.
- Swift helper: compile + local ad-hoc code signing untuk arm64 macOS 13+;
  API dicek terhadap SDK CoreWLAN/CoreLocation yang terpasang.
- ESP: compile Arduino-ESP32 **3.3.12**, ESP32S3 Dev Module, FlashSize=16M,
  **PSRAM=disabled**, CDCOnBoot=cdc; tidak flash board dalam proses pembuatan.
  Hasil compile: sketch 947461 byte, global variables 50480 byte. Ukuran heap
  runtime dan kestabilan daya tetap perlu dicek pada board asli.

## Review independen
Review sumber/protokol dilakukan oleh reviewer terpisah. Temuan penting:
token non-ASCII dapat memicu TypeError pada compare_digest dan menghentikan
server. Sudah diperbaiki dengan validasi tipe/format token dan tes regresi
yang menolak input malformed, lalu menerima client sah pada listener yang sama.
Tidak ada pemeriksaan tersebut yang mengubah pengaturan jaringan atau flash board.

## Belum dibuktikan oleh pemeriksaan tersebut
- Eksekusi BAT dan server di komputer Windows pengguna.
- Windows Mobile Hotspot 2,4 GHz bisa beroperasi tanpa internet pada adaptor tersebut.
- Dialog/perizinan Tahoe menghasilkan RSSI asli pada MacBook pengguna.
- Firmware boot, filesystem, association, daya, dan jangkauan pada board nyata.
- Keakuratan/kalibrasi RSSI dan perilaku driver saat interferensi/roaming.

## Smoke test wajib sebelum lapangan
1. Pada jarak 1 m, cek SSID/BSSID target dan IP server hotspot.
2. Jalankan satu uji per target: byte diterima tepat 10.000.000, durasi >0,
   rssi_samples_count >0 atau alasan akses RSSI jelas, 20 echo tercatat.
3. Cek hitung ulang Mbps dan rata-rata dari file sampel.
4. Matikan hotspot saat payload: hasil gagal/unknown tidak menjadi sukses palsu.
5. Aktifkan hotspot, reconnect memakai sesi asli; laporan pulih by ID tanpa duplikat.
6. Tutup Windows setelah receiver menyimpan report sebelum ACK, lalu `--resume`;
   receiver harus mempertahankan pending sampai ACK.
7. Setelah ketiga platform lulus, baru jalankan seri 1 m, 2 m, 3 m sampai gagal.

Record waktu eksekusi/perangkat/OS nyata ketika melakukan checklist ini; jangan
menandainya lulus hanya karena compile atau loopback berhasil.
