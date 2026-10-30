# TCP protocol v1

Port default 8765. Semua control frame UTF-8 JSON object satu baris diakhiri LF.
Tidak boleh ada NaN/Infinity. Receiver ESP membatasi control masuk 4096 byte;
server/Python membatasi 131072 byte untuk laporan. Payload bukan JSON dan tidak
memakai delimiter akhir: panjang **10.000.000 byte** adalah framing-nya.
`payload_ready` mencegah payload tiba sebelum receiver menyiapkan timer.

1. Client → `hello`: protocol=1, token, device=`macbook|esp32`, receiver_id, ssid,
   pending_count (ESP 0/1; Python 0..16).
2. Server → `welcome`.
3. Untuk setiap pending: client → `result`, server simpan secara durable → `ack`.
   Unknown ID/identitas ditolak; client mempertahankan laporan, gunakan sesi asli.
4. Server → `start`: test_id, target_bytes, timeout_s, distance_m, repetition.
5. Client → `ready`: test_id.
6. Server → `echo`: test_id, seq. Client → `pong`: test_id, seq. Default 20 kali.
7. Server → `transfer`: test_id, target_bytes, timeout_s.
8. Client → `payload_ready`: test_id. Mulai timer receiver setelah frame ini dikirim.
9. Server → payload biner streaming. Client membaca tepat target byte; tidak
   menunggu socket ditutup. Timeout adalah deadline total, tidak diperbarui tiap read.
10. Client menghentikan timer, menyimpan laporan lokal, lalu → `result`.
11. Server validasi, simpan record/CSV, lalu → `ack`: test_id. Baru client menghapus pending.

Envelope result: `type`, `test_id`, `device`, `receiver_id`, `ssid`, `bssid`, `result`.
Result berisi `bytes_received`, `duration_s`, `transfer_complete`, `status`,
`failure_reason`, `rssi_samples`, `rssi_reason`, `timer`.
Sampel minimal: `elapsed_ms`, `rssi_dbm` (number negatif atau null). Metadata
SSID/BSSID/source per sampel Mac; ESP mengirim identitas sekali di envelope untuk
menghemat SRAM. Windows menambahkan identitas itu ke CSV raw tanpa membuat RSSI.

Jika gagal sebelum payload: bytes_received=0, duration_s=null, before_payload=true,
transfer_complete=false. Jika Windows tidak memiliki laporan receiver, byte dan
durasi adalah null, bukan ukuran dari socket write.

Authentication token mencegah client tidak sengaja, **bukan pengganti TLS**.
Gunakan hotspot berpassword dan terisolasi, jangan expose port ke internet.
TCP/application echo memerlukan trafik dua arah meskipun payload hanya satu arah.
