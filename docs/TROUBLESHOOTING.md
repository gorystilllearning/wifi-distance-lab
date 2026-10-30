# Kendala perangkat

## Windows
- **Cannot assign requested address / WinError 10049:** hotspot belum aktif atau
  `--bind` salah. Periksa adaptor hotspot dengan `ipconfig`.
- **Target tidak terhubung:** pastikan 2,4 GHz, kata sandi benar, IP server sesuai,
  firewall port 8765 terbatas pada subnet hotspot, token dan SSID sama persis.
- **Mobile Hotspot menolak aktif offline:** masalah Windows/driver/adaptor, bukan
  server TCP. Uji konfigurasi sumber koneksi terlebih dahulu. Jangan mengklaim
  topologi offline berhasil tanpa verifikasi. Wi-Fi Direct bukan pengganti otomatis
  yang kompatibel Mac/ESP.
- **Access denied saat menyimpan CSV:** tutup Excel, periksa antivirus dan izin
  folder. Record JSON ditulis dahulu; restart memakai `--resume` mengekspor ulang.
- **Laporan ID tidak dikenal:** pendamping masih memiliki laporan sesi lama.
  Resume folder asli dengan token asli; jangan hapus laporan hanya agar bisa lanjut.
- **Jarak tidak dapat diuji karena target sama sekali tidak terhubung:** catat
  setelah timeout menunggu, gunakan `f <jarak>` untuk target terakhir yang pernah
  dikenali. Ini observasi gagal koneksi, bukan hasil RSSI/throughput.
  Bila masih ada koneksi TCP lama, memulai uji pada jarak tersebut mencatat kegagalan.
  Jangan mengubah jarak record lama ketika membawa target mendekat untuk recovery.

## macOS Tahoe
- Pastikan helper dibuka sebagai **app bundle** lewat `open`, bukan hanya executable
  Swift di terminal. Bundle memiliki Info.plist, izin lokasi, dan tanda tangan lokal.
- Location Services harus aktif dan helper diizinkan. Biarkan jendela helper terbuka
  selama uji. Jangan mengandalkan izin Terminal untuk menggantikan izin helper.
- Periksa SSID/BSSID dalam helper sebelum uji. Jika kosong, periksa izin atau koneksi.
- Setelah rebuild, macOS mungkin meminta izin ulang karena identitas tanda tangan
  ad-hoc berubah. Tutup helper lama, build, buka ulang dan periksa Settings.
- Ada dialog Local Network untuk Python/Terminal: izinkan jaringan lokal. Jangan
  mematikan seluruh proteksi privasi macOS.
- Pesan `native helper stale`: helper tertutup, file output berbeda atau jam sistem
  diubah. Receiver menolak sampel lebih tua dari 2 detik. Perhitungan transfer/RTT
  sendiri memakai jam monotonik, bukan jam kalender.
- Jika izin tetap membatasi RSSI, nilai dibiarkan kosong dengan alasannya. Jangan
  mengambil dBm dari jaringan lain atau mengonversi persentase kualitas sinyal.
- Python bawaan Xcode mungkin terlalu lama. Gunakan Python 3.11+ yang telah dipasang
  sebelum eksperimen; tidak ada kebutuhan unduh paket saat di lapangan.

## ESP32-S3
- Gunakan port USB yang sesuai Serial; USB native memerlukan CDC On Boot.
  Serial Monitor 115200 + Newline; tekan reset untuk melihat pesan startup.
- Inisialisasi filesystem hanya dengan `FORMAT` ketika memang belum berisi hasil.
  LittleFS memakai partisi berlabel `spiffs`; ini normal di Arduino-ESP32.
- Jika board terus restart: periksa daya, kabel, Flash Size 16 MB, custom partitions,
  PSRAM Disabled. Penggunaan payload tetap 4096 byte; tidak ada array 10 MB.
- `Handshake/recovery failed`: token/SSID salah atau laporan lama membutuhkan
  `--resume` sesi asli. Token baru tidak otomatis menghapus pending.
- Setelah uji gagal, firmware reconnect. Bila Windows masih di prompt input,
  masukkan `r` agar server menerima koneksi baru.
- Perintah `STATUS` memperlihatkan SSID/BSSID/RSSI dan adanya laporan tertunda.
  RSSI 0 ketika disconnected tidak dijadikan dBm sah.
- Arduino API tidak selalu membedakan FIN TCP dari reset pada EOF; pesan kegagalan
  menjelaskan batas ini. Hilangnya asosiasi Wi-Fi diberi status disconnected.

## Praktik lapangan
- Jangan menyalakan video call/download/internet background, VPN atau client hotspot
  lain selama uji. Matikan auto-join jaringan lain pada target.
- Jaga orientasi layar Mac, board, antena, dan tubuh operator konsisten.
- Kegagalan pertama bukan selalu batas jangkauan: ulangi jarak itu, catat gangguan,
  dan lihat jumlah sampel RSSI/RTT serta status pelaporan.
