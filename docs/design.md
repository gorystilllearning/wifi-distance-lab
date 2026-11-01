# Desain eksperimen Wi-Fi

Windows adalah hotspot 2,4 GHz dan pengirim tetap. MacBook Air M4 macOS
Tahoe atau ESP32-S3-DevKitC-1 N16R8 menjadi penerima bergerak, bergantian.
Tidak ada router atau internet pada jalur uji. Python CLI Windows dipanggil BAT.

Payload tepat 10.000.000 byte, streaming buffer kecil. Penerima menggunakan
timer monotonik dari sebelum pembacaan payload pertama sampai selesai/gagal;
throughput adalah byte diterima * 8 / detik / 1.000.000. RSSI dBm di penerima
adalah sinyal hotspot Windows. RTT aplikasi diukur Windows, 20 echo sebelum
transfer, bukan delay satu arah. Bukan RSSI koneksi internet Windows.

Jarak fisik dimasukkan pengguna, pengulangan 1 atau 3, timeout awal 60 detik.
Windows menyimpan record sebelum uji. Hasil penerima dipertahankan lokal sampai
Windows mengakui penyimpanan; reconnect memperbarui ID yang sama. Byte diterima
tidak diketahui sebelum laporan tiba. Rekam status transfer dan status pelaporan
secara terpisah. CSV diproyeksikan dari record JSON atomik, hasil lama aman.

Mac memakai helper Swift app CoreWLAN/CoreLocation untuk RSSI asli dan izin
lokasi. Python pendamping hanya menerima, membalas echo, mengirim hasil.
ESP memakai Arduino-ESP32 3.3.12, WiFi.RSSI(), LittleFS untuk hasil tertunda,
buffer 4096 byte, tidak membutuhkan PSRAM. Preferences menyimpan token sesi.
Semua kredensial lokal diabaikan git.

Keamanan: hotspot WPA2/lebih baik, token acak sesi sebelum layanan menerima uji,
validasi ukuran/framing, port lokal 8765, hanya gunakan jaringan uji tepercaya.
Tidak ada push GitHub otomatis. Unit/integration tests tidak membuktikan radio,
izin Tahoe, hotspot Windows offline, atau board asli telah bekerja.

## Grafik (disetujui 2026-11-01)
Matplotlib opsional di Windows, bukan scikit-learn. Setelah pengukuran/ACK,
CLI memperbarui tiga PNG jarak vs RSSI/throughput/RTT dalam folder grafik sesi.
grafik.bat membuat ulang dari CSV. Mean dan SD sampel antarulangan sukses dipisah
dari titik gagal. Nilai kosong tidak dianggap nol. Gagal tanpa metrik ditandai
di tepi grafik. Error/missing dependency grafik tidak menggagalkan pengukuran.
setup_grafik.bat memasang dependensi sebelum eksperimen; runtime tetap offline.
