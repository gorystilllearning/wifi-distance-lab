# Wi-Fi Distance Lab

Program eksperimen jarak **Windows → MacBook Air M4 (macOS Tahoe)** dan
**Windows → ESP32-S3-DevKitC-1 N16R8**, bergantian. CLI Windows diluncurkan
dengan `.bat`. Tidak perlu internet saat eksperimen.

**Status validasi:** lihat [docs/VALIDATION.md](docs/VALIDATION.md). Tes TCP lokal
bukan hasil radio lapangan. Jangan memakai angka dari unit test sebagai data penelitian.

## Topologi dan pembagian tugas

| Perangkat | Peran dan posisi |
|---|---|
| Windows | Hotspot **2,4 GHz**, pengirim payload **tetap**, pengukur RTT, pengendali dan pencatat |
| MacBook **atau** ESP32-S3 | Client hotspot, penerima yang dipindahkan 1 m, 2 m, dst.; menghitung penerimaan dan membaca RSSI |

Hanya **satu target** yang aktif/tersambung saat pengujian. Jalur data:
Windows → Wi-Fi → target. Pesan kontrol, echo dan laporan memakai koneksi TCP
yang sama, **di luar fase pengiriman payload**. Tidak ada router ketiga.
Wi-Fi/TCP tetap mengirim ACK balik; "satu pengirim/penerima" di sini adalah arah
payload utama, bukan radio satu arah mutlak.

Windows **tidak mengukur RSSI client hotspot**. RSSI dibaca client terhadap sinyal
Windows. Windows tidak dapat membuktikan byte diterima hanya dari keberhasilan
`send()`: itulah alasan program/firmware pendamping diperlukan.

## Struktur folder

```text
wifi-distance-lab/
├── setup.bat                     # Buat venv, jalankan tes, tanpa pip download
├── mulai.bat                     # Program utama Windows
├── requirements.txt              # Standard library Python; tidak ada paket pip
├── wifi_lab/
│   ├── controller.py             # Pengirim, RTT, CLI, penerimaan laporan
│   ├── protocol.py               # TCP JSON/payload framing
│   ├── receiver.py               # Timer/byte/RSSI di receiver Python
│   ├── companion.py              # Pendamping Mac dan antrean persisten
│   └── storage.py                # Record JSON, CSV, ringkasan
├── macos/
│   ├── RSSIHelper.swift          # CoreWLAN + izin CoreLocation, app lokal
│   ├── Info.plist
│   ├── build.sh
│   └── jalankan.command
├── esp32/WifiReceiver/
│   ├── WifiReceiver.ino
│   ├── config.example.h          # Salin menjadi config.h lokal
│   └── partitions.csv            # 16 MB: app + LittleFS hasil tertunda
├── tests/                        # Unit dan real TCP loopback, bukan pengukuran radio
├── docs/                         # Protokol, validasi, troubleshooting
└── hasil/                        # Dibuat saat program berjalan; diabaikan Git
```

## 1. Persiapan Windows

1. Pasang **Python 3.11 atau lebih baru**, termasuk **Python Launcher (`py`)**.
   Salin seluruh folder proyek ke Windows. Jalankan `setup.bat`.
   Internet hanya diperlukan untuk mengunduh Python/toolchain terlebih dahulu;
   program ini tidak memasang paket pip.
2. Buka Settings → Network & internet → Mobile hotspot. Atur nama/kata sandi,
   **network band 2,4 GHz**. Aktifkan hotspot. Matikan opsi hotspot otomatis
   dimatikan saat tidak ada client bila tersedia.
3. Pastikan hotspot tetap bisa aktif ketika internet tidak tersedia.
   **Sebagian kombinasi Windows/adaptor menolak hotspot tanpa koneksi sumber.**
   Uji sebelum berangkat; program tidak bisa memperbaiki keterbatasan driver ini.
   Jika driver butuh koneksi sumber untuk aktivasi, siapkan koneksi sumber terpisah
   yang mendukung konfigurasi itu; jangan mengganti diam-diam dengan router ketiga.
   Bila tidak dapat beroperasi tanpa internet, topologi perlu dievaluasi ulang.
4. Jalankan `ipconfig`. Cari IP adaptor hotspot/ICS, biasanya **192.168.137.1**.
   Jangan gunakan IP jaringan internet Windows. Alamat default bisa berbeda.
5. Izinkan Python pada **jaringan lokal hotspot** melalui Windows Firewall.
   Jangan mematikan firewall seluruhnya. Jika perlu aturan terbatas, jalankan
   PowerShell administrator dengan IP/subnet yang benar:

   ```powershell
   New-NetFirewallRule -DisplayName "WiFi Distance Lab" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -LocalAddress 192.168.137.1 -RemoteAddress 192.168.137.0/24 -Profile Any
   ```

   Aturan ini hanya untuk subnet hotspot tersebut. Untuk menghapusnya sesudah uji:
   `Remove-NetFirewallRule -DisplayName "WiFi Distance Lab"`.
6. Dari CMD di folder proyek:

   ```bat
   mulai.bat --ssid "NamaHotspot" --bind 192.168.137.1 --timeout 60 --repetitions 3
   ```

   Program membuat folder sesi, menampilkan **token sesi 32 karakter** dan menunggu
   pendamping. Token berbeda dari kata sandi Wi-Fi. Default: 20 RTT, timeout per
   echo 1 detik; laporan tambahan 10 detik. Dapat diubah dengan
   `--rtt-timeout 1 --report-timeout 10 --connect-timeout 15`.

**Jangan membuka CSV aktif di Excel ketika pengujian masih berjalan.** Windows/Excel
bisa mengunci file sehingga ekspor gagal. Tutup Excel atau buka salinan file.
Record JSON per uji ditulis lebih dahulu dan bisa diekspor lagi saat `--resume`.

## 2. Pendamping MacBook Tahoe

Salin proyek ke Mac. Sebelum eksperimen, pasang **Python 3.11+** dan Apple
**Command Line Tools** (`xcode-select --install`, memerlukan internet saat pemasangan).
Tidak perlu Homebrew/paket pip jika Python sudah tersedia.

1. Hubungkan Mac ke hotspot Windows. Putuskan Ethernet/VPN/tethering yang dapat
   mengalihkan jalur ke IP server. Matikan auto-join jaringan Wi-Fi lain.
2. Dari Terminal di folder proyek:

   ```sh
   zsh macos/build.sh
   zsh macos/jalankan.command
   ```

3. Masukkan SSID persis dan IP hotspot, lalu token sesi dari Windows.
4. Helper lokal **Wi-Fi Distance Lab — RSSI** membuka jendela dan meminta izin
   lokasi. Izinkan di System Settings → Privacy & Security → Location Services.
   Aktifkan akses **Local Network** untuk Python/Terminal bila macOS memintanya.
   Tidak ada lokasi yang dikirim ke internet.
5. Biarkan helper dan terminal terbuka. Pastikan jendela menunjukkan SSID/BSSID
   hotspot Windows dan RSSI dBm. Jika helper belum siap, pembacaan akan kosong
   dengan alasan; Windows tetap dapat menguji transfer.

`.bat` bukan format program macOS. `.command` dapat dibuka dengan Terminal;
menjalankannya melalui `zsh` tidak memerlukan pengubahan executable permission.
Helper dikompilasi untuk **Apple Silicon arm64**, sesuai MacBook M4. Bundle
ditandatangani **ad-hoc lokal**, bukan aplikasi notarized dari App Store.

Perintah manual, jika perlu:

```sh
open macos/build/WiFiRSSIHelper.app --args --output "$PWD/macos/build/rssi.json"
python3 -m wifi_lab.companion --ssid "NamaHotspot" --server 192.168.137.1
```

Helper memakai `CWWiFiClient`/`CWInterface.rssiValue()`, bukan `airport`, `wdutil`,
persentase sinyal, hasil scan jaringan lain, atau perkiraan. Tidak membutuhkan sudo.
Jika Tahoe membatasi data walaupun izin sudah diberikan, alasan disimpan;
jangan mengganti nilai kosong dengan angka buatan. Detail di [troubleshooting](docs/TROUBLESHOOTING.md).

## 3. Firmware ESP32-S3-DevKitC-1 N16R8

Dipilih **Arduino framework** untuk pemasangan mudah di Arduino IDE, dengan API
ESP-IDF bawaan untuk timer dan JSON. Tidak perlu ArduinoJson atau library tambahan.
Core yang dipakai untuk compile check: **esp32 by Espressif Systems 3.3.12**.

1. Pasang Arduino IDE + core ESP32 melalui Boards Manager sebelum ke lapangan.
   URL Boards Manager resmi jika diperlukan:
   `https://espressif.github.io/arduino-esp32/package_esp32_index.json`.
2. Salin `esp32/WifiReceiver/config.example.h` → `config.h`. Isi nama/kata sandi
   hotspot Windows dan IP server. Token dapat diisi di sini atau melalui serial.
3. Buka `WifiReceiver.ino`. Pilih **ESP32S3 Dev Module**:
   - Flash Size: **16 MB**;
   - PSRAM: **Disabled** untuk membuktikan tidak bergantung padanya; N16R8 boleh
     memakai OPI PSRAM kemudian, tetapi gunakan setelan konsisten sepanjang uji;
   - CPU: **240 MHz**;
   - file `partitions.csv` yang disertakan harus berada di folder sketch dan
     digunakan saat build; jangan memilih partisi tanpa filesystem;
   - gunakan USB UART untuk Serial standar, atau USB native dengan
     **USB CDC On Boot: Enabled**, **USB Mode: Hardware CDC and JTAG**;
   - Erase All Flash: **Disabled**, agar hasil tertunda tidak terhapus.
4. Upload firmware. Serial Monitor **115200 baud**, line ending **Newline**.
   Pada pemasangan pertama, jika LittleFS belum terformat, firmware menunggu
   perintah **`FORMAT`**. Ini menghapus filesystem sketch dan **hanya untuk
   inisialisasi yang disengaja**. Jangan format jika mungkin ada hasil tertunda.
   Tekan reset jika pesan awal tidak terlihat.
5. Masukkan token sesi dari Windows tanpa upload ulang:

   ```text
   TOKEN <32-karakter-token-dari-Windows>
   STATUS
   ```

   Token tersimpan di Preferences. Jangan pindah ke token sesi baru sebelum
   laporan sesi lama sudah diakui Windows. SSID/password/IP diubah melalui config.h.
6. Setelah berhasil terhubung, gunakan power bank sebagai daya agar board bisa
   dipindahkan. **USB serial bukan jalur payload atau pengiriman hasil pengukuran.**
   Tidak perlu kabel USB panjang dari Windows.

Alternatif compile check memakai Arduino CLI:

```sh
arduino-cli compile --fqbn esp32:esp32:esp32s3:FlashSize=16M,PSRAM=disabled,CDCOnBoot=cdc esp32/WifiReceiver
```

Firmware menggunakan **buffer payload 4096 byte**. Sampel RSSI dan laporan JSON
terbatas ukurannya; payload 10 MB tidak disimpan di RAM/flash. `WiFi.setSleep(false)`
dipakai konsisten untuk mengurangi pengaruh power saving ESP.

## 4. Pelaksanaan eksperimen

Kelompok maksimal **4 orang**. Bagi tugas: operator Windows, pembawa target,
pengukur jarak, pengawas/penjaga kondisi eksperimen.

1. Pilih tempat terbuka yang aman. Tetapkan tinggi, orientasi, posisi antena,
   sumber daya, dan arah lintasan. Jangan menutupi antena ESP dengan tangan.
2. Windows tetap di titik awal, hotspot 2,4 GHz aktif. Cegah sleep dan perubahan
   power mode otomatis. Jangan mengubah daya/channel/perangkat selama satu seri.
3. Nyalakan hanya satu pendamping, mulai pada **1 meter**, ukur secara fisik.
4. Setelah pendamping terhubung, masukkan `1` di Windows dan Enter. Ini memulai
   20 echo, lalu payload **10.000.000 byte**. Default tiga pengulangan otomatis.
   Jangan memindahkan perangkat selama percobaan berlangsung.
5. Lihat status tiap percobaan. CSV disimpan setiap kali hasil berubah.
6. Pindahkan target ke **2 m, 3 m, 4 m, dst.**, masukkan jarak yang sesuai.
7. Jika gagal, hasil tetap disimpan. Sambungkan kembali jika perlu dan masukkan
   **jarak yang sama**. Nomor pengulangan bertambah, bukan menimpa percobaan lama.
   Program menghentikan batch pada kegagalan pertama untuk memberi kesempatan
   memeriksa/reconnect sebelum mencoba ulang; bukan otomatis melewati titik gagal.
   Bila target terakhir sama sekali tidak dapat reconnect, setelah timeout menunggu
   masukkan **`f <jarak>`**, misalnya `f 12`, untuk mencatat kegagalan koneksi pada
   jarak itu. Ulangi menunggu dan perintah yang sama untuk percobaan ulang. Ini tidak
   menghasilkan RSSI/throughput/byte penerima buatan dan hanya tersedia setelah
   identitas target pernah berhasil dikenali dalam proses Windows yang sama.
8. Jika target harus didekatkan untuk mengirim laporan tertunda, **jangan memulai
   percobaan baru** saat mendekat. Sinkronisasi memakai ID uji lama, sehingga jarak
   pengukurannya tetap jarak gagal, bukan posisi saat laporan dikirim.
9. Perintah `r` di prompt jarak menutup koneksi agar bisa reconnect/ganti target.
   Matikan pendamping sebelumnya dahulu. Ulangi seri dari 1 m untuk target lainnya.
10. `q`/Ctrl+C untuk berhenti. Folder hasil tidak dihapus.

Default 60 detik adalah **deadline total payload**, bukan 60 detik untuk setiap
paket. RTT, handshake, input pengguna dan pemindahan perangkat tidak termasuk
durasi payload. Pada kegagalan, waktu hingga timeout/EOF termasuk durasi parsial.

## 5. Hasil dan rumus

```text
hasil/<tanggal-jam-id>/
├── session.json                 # Konfigurasi/token sesi: jangan dipublikasikan
├── records/<test_id>.json        # Sumber data utama, atomik per percobaan
├── macbook_pengujian.csv
├── esp32_pengujian.csv
├── sampel_rssi.csv
├── sampel_rtt.csv
└── ringkasan.json
```

Satu baris CSV pengujian = satu percobaan, bukan rata-rata tiga percobaan.
Detail nama kolom ada pada `wifi_lab/storage.py:COLUMNS`. Kolom kosong berarti
**tidak diketahui/tidak tersedia**, bukan nol. Waktu UTC berasal dari Windows;
tidak diperlukan sinkronisasi jam target untuk RTT atau throughput.
Teks yang dapat dibaca Excel sebagai formula diberi awalan apostrof pada ekspor
CSV untuk keamanan; nilai asli tetap tersedia dalam record JSON. Nilai numerik
RSSI/throughput/RTT tidak diubah menjadi teks.

### RSSI (dBm)

- Sinyal **hotspot Windows sebagaimana diterima target**.
- Mac: native CoreWLAN; ESP: native `WiFi.RSSI()` station API.
- Interval target sekitar `max(0,25 detik, timeout/240)`, sehingga penyimpanan
  sampel terbatas. Helper Mac memperbarui bacaan tiap 0,2 detik; bacaan helper
  yang identik timestamp-nya tidak dihitung sebagai sampel baru.
- Rata-rata aritmetika **nilai dBm**, minimum, maksimum, jumlah **sampel valid**.
  Ini bukan rata-rata daya linear. Minimum dBm lebih negatif = sinyal lebih lemah.
- Sampel saat gagal/izin ditolak juga tersimpan dengan alasan, tetapi tidak masuk
  statistik valid. Transfer yang sangat cepat mungkin hanya memiliki satu sampel;
  tidak dibuat sampel palsu untuk memenuhi jumlah tertentu.

### Throughput payload aplikasi (Mbps)

```text
throughput_mbps = bytes_received × 8 / duration_s / 1.000.000
```

Target memulai timer monotonik tepat setelah mengirim `payload_ready`, sebelum
pembacaan payload pertama, dan menghentikannya setelah byte terakhir atau gagal.
Windows baru boleh mengirim payload setelah `payload_ready`, sehingga tidak ada
payload prebuffered sebelum fase timer. Durasi termasuk waktu tunggu byte pertama,
penerimaan, serta overhead pencuplikan RSSI; bukan waktu input/RTT/laporan ke Windows.
Python: `perf_counter_ns()`; ESP: `esp_timer_get_time()` resolusi mikrodetik.
Ini **bukan PHY link rate** dan bukan ukuran total paket radio termasuk header.

`bytes_sent_socket` hanya diagnostik di sisi Windows, tidak dipakai dalam rumus.
Transfer parsial tetap memiliki throughput parsial jika byte dan durasi diketahui.

### RTT aplikasi (ms)

Windows mengukur dengan `perf_counter_ns()` dari sebelum mengirim JSON echo hingga
balasan lengkap dengan **ID uji dan sequence yang cocok** diterima. Default
20 percobaan **sebelum transfer**, satu per satu. Balasan terlambat tidak dianggap
balasan sequence berikutnya. RTT mencakup TCP, penjadwalan dan pemrosesan aplikasi.

```text
RTT_ms = (waktu_balasan_ns - waktu_kirim_ns) / 1.000.000
tanpa_balasan_pct = (percobaan - balasan) / percobaan × 100
```

Tidak dibagi dua dan tidak disebut delay satu arah. Persentase ini adalah
**echo aplikasi tanpa balasan sebelum deadline**, bukan packet loss radio/IP;
TCP dapat melakukan retransmisi secara internal. Statistik RTT hanya dari balasan valid.

### Status

| Status | Arti |
|---|---|
| `success` | Penerima mengonfirmasi tepat 10.000.000 byte |
| `transfer_incomplete` | TCP berakhir sebelum target byte |
| `timeout` | Deadline total payload habis di penerima |
| `connection_disconnected` | Koneksi/asosiasi hilang atau gagal sebelum payload |
| `program_error` | Protokol/laporan/kode tidak valid; bukan bukti batas jangkauan |
| `report_timeout` | Windows belum mendapatkan laporan; hasil penerimaan belum diketahui |
| `pending` | Record sudah dibuat, percobaan belum final |

`report_status` dipisahkan: `pending`, `awaiting_recovery`, `received`,
`not_available` (target tidak berhasil terkoneksi, payload belum dimulai).
**Report timeout tidak otomatis berarti payload gagal diterima.** Saat laporan
pulih, record diperbarui dengan ID sama, tidak membuat baris duplikat.

Ringkasan memisahkan jarak sukses terjauh, gagal pertama yang teramati, dan gagal
terkonfirmasi. Konfirmasi memerlukan **minimal dua hasil gagal dari penerima
dan tidak ada sukses pada jarak itu**. Gagal laporan saja bukan konfirmasi radio.
Jika ada sukses setelah gagal pada jarak sama, hasilnya campuran, bukan batas pasti.

## 6. Recovery setelah koneksi/program berhenti

- Mac menyimpan laporan ke `pending/macbook/<test_id>.json`, hanya dihapus setelah
  ACK dari Windows.
- ESP menyimpan **satu laporan tertunda** di LittleFS dan menolak uji baru sampai
  laporan itu diakui. Token tersimpan terpisah di Preferences.
- Windows menulis record JSON atomik, lalu CSV, **baru ACK**. Jika ACK hilang,
  pengiriman ulang memperbarui ID yang sama secara idempoten.
- Gunakan **sesi Windows yang sama** untuk recovery:

  ```bat
  mulai.bat --resume "hasil\<folder-sesi-lama>" --bind 192.168.137.1
  ```

  Token/SSID dibaca dari `session.json`. Gunakan `--timeout`/`--repetitions` lagi
  jika ingin nilai nondefault untuk percobaan baru. Jangan menghapus pending,
  mengganti token, memformat flash, atau membuat sesi baru untuk memaksa uji lanjut.
- Bila target tidak pernah menerima perintah `start`, tidak akan ada laporan target
  untuk ID tersebut. Byte diterima tetap kosong; catatan Windows tetap dipertahankan.
- Jika perangkat mati di tengah payload **sebelum sempat menyimpan laporan**,
  byte parsial tidak dapat dipulihkan setelah reboot. Windows mempertahankan record
  unknown; bukan mengarang ukuran. Raw payload tidak ditulis terus-menerus ke flash
  karena mengubah kinerja dan menambah keausan.

## 7. Memeriksa jalur pengukuran

1. Jendela RSSI Mac atau perintah `STATUS` ESP harus menunjukkan **SSID dan BSSID
   hotspot Windows**, bukan Wi-Fi kampus/rumah. Gunakan nama hotspot unik.
2. Pastikan server bind ke IP adaptor hotspot, dan alamat client yang tampil berada
   pada subnet yang sama. Nonaktifkan jalur alternatif/VPN selama eksperimen.
3. `sampel_rssi.csv` memuat sumber, SSID/BSSID, interface dan waktu relatif. ESP
   mengirim identitas sekali di envelope untuk menghemat SRAM; Windows menambahkannya
   pada baris sampel. Pembacaan kosong tidak ikut rata-rata.
4. Pastikan uji sukses memiliki `target_bytes=bytes_received=10000000` dan
   `transfer_complete=True`. Hitung ulang Mbps dari dua kolom itu dan `duration_s`.
5. Matikan hotspot saat percobaan berjalan: hasil tidak boleh tetap menjadi sukses
   hanya karena socket Windows pernah menerima seluruh data untuk dikirim.
   Dekatkan/nyalakan lagi dan periksa pemulihan laporan parsial.
6. Periksa `sampel_rtt.csv`: 20 sequence dengan nilai atau alasan timeout. RTT harus
   menggunakan endpoint target yang sama dengan transfer, bukan ping internet.
7. Opsional: Wireshark pada adaptor hotspot Windows, filter `tcp.port == 8765`.
   Harus terlihat echo/pong sebelum fase payload dan lalu laporan. Jangan menjumlahkan
   seluruh byte capture sebagai payload: retransmisi/header/control berbeda.

## 8. Contoh CSV dan grafik

[docs/contoh_SIMULASI.csv](docs/contoh_SIMULASI.csv) adalah **contoh buatan** dengan
subset kolom, **bukan hasil pengukuran**. ID diawali `SIMULASI-` dan file dipisahkan
dari direktori hasil nyata. CSV aktual memiliki kolom tambahan identitas/status/sampel.

Untuk laporan, buka CSV di Excel sesudah sesi selesai, lalu buat scatter plot
`distance_m` terhadap `rssi_mean_dbm`, `throughput_mbps`, dan `rtt_mean_ms`.
Pisahkan perangkat; jangan menganggap nilai kosong sebagai nol. Untuk tiga
pengulangan tampilkan semua titik atau rata-rata dengan error bar serta jumlah
percobaan sukses/gagal per jarak. Jangan menghapus kegagalan dari laporan.

## 9. Pengujian dan GitHub

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q wifi_lab tests
```

Di Windows gunakan `.venv\Scripts\python.exe` menggantikan `python3`.
Tes loopback benar-benar mengirim 10 MB melalui TCP lokal, tetapi **bukan**
pengujian RSSI atau radio. Tidak ada generator hasil lapangan simulasi di program.

Sebelum upload, cek `.gitignore`: `config.h`, `hasil/`, `pending/`, `.venv/`,
hasil build helper dan bytecode **tidak dipublikasikan**. Jangan commit dump flash,
kata sandi hotspot atau token. Kalau hasil penelitian ingin dibagikan, ekspor
salinan CSV yang telah ditinjau—bukan `session.json`. Proyek ini belum otomatis
diunggah atau dipublikasikan ke GitHub.

## Keterbatasan utama

- Belum membuktikan hotspot offline Windows, izin Tahoe, dan radio ESP di perangkat
  Anda sampai smoke test perangkat nyata dilakukan.
- RSSI AP adalah pengamatan receiver/driver yang dapat di-cache; tidak identik
  dengan RSSI setiap frame payload dan bukan pengukuran daya terkalibrasi.
- Sampel sangat sedikit pada transfer cepat, driver/OS/power saving, interferensi,
  orientasi antena, suhu, dan halangan memengaruhi hasil. Catat kondisi lapangan.
- RTT sebelum transfer **bukan RTT saat jaringan sedang dibebani**.
- Tidak ada sinkronisasi waktu untuk delay satu arah; tidak ada klaim demikian.
- Pelaporan memakai Wi-Fi uji setelah transfer, bukan jaringan manajemen terpisah.
  Recovery lokal diperlukan saat link gagal. Pemadaman mendadak dapat kehilangan
  byte parsial yang belum sempat dibuat menjadi laporan.
- Serial ESP hanya konfigurasi/daya. Tidak ada payload atau metrik yang secara
  diam-diam melewati USB. Jangan sambungkan kedua target saat eksperimen.

Referensi API resmi: [Python perf_counter](https://docs.python.org/3/library/time.html#time.perf_counter_ns),
[Apple CoreWLAN](https://developer.apple.com/documentation/corewlan),
[Apple CoreLocation](https://developer.apple.com/documentation/corelocation),
[Arduino-ESP32 Wi-Fi](https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html),
[ESP-IDF High Resolution Timer](https://docs.espressif.com/projects/esp-idf/en/stable/esp32s3/api-reference/system/esp_timer.html).
