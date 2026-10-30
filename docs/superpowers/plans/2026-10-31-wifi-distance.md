# Wi-Fi Distance Lab Implementation Plan

> **For agentic workers:** Use superpowers-executing-plans inline. Steps use checkbox syntax.

**Goal:** Eksperimen Windows ke Mac/ESP dengan hasil otomatis, tanpa data palsu.
**Architecture:** Server Python Windows mengirim payload dan mengukur RTT;
target menerima dan melaporkan RSSI/throughput melalui protokol TCP berframing.
**Tech Stack:** Python 3.11+, Swift/CoreWLAN, Arduino-ESP32 3.3.12.
**Spec:** `docs/design.md`

## Global Constraints
- Payload 10.000.000 byte; buffer 4096 byte pada ESP; timeout awal 60 detik.
- RSSI dBm asli di target; RTT 20 kali sebelum transfer; tidak membuat data nyata palsu.
- Simpan gagal/parsial, recovery by ID, 1 atau 3 pengulangan, CLI BAT Windows.

## Review Focus
- JSON/payload terfragmentasi atau digabung oleh TCP: tidak kehilangan byte.
- Koneksi putus sebelum laporan: byte tidak ditebak dan laporan pulih by ID.
- Invalid/absent RSSI: kosong dengan alasan, bukan 0 dBm palsu.
- Timeout total, bukan timeout reset setiap paket; RTT terlambat tidak bergeser seq.
- Laporan duplikat/identitas salah: idempoten dan tidak menimpa uji lain.

## Task 1: Protocol, receiver and storage
Files: `wifi_lab/protocol.py`, `receiver.py`, `storage.py`, `tests/test_lab.py`.
Interfaces: JSON newline <= 131072 byte; payload length exact; `receive_payload`,
`Store.begin/update`, `summarize`. Tests socketpair fragmentation, timeout,
disconnect, formula, atomic recovery, input validation.
- [x] Write/run failing unittest suite.
- [x] Implement protocol/receiver/store, rerun suite green.

## Task 2: Windows coordinator + Python Mac companion
Files: `wifi_lab/controller.py`, `companion.py`, BAT/requirements.
Interfaces: hello(token,device,pending), ack, start, ready, echo/pong,
transfer(size,timeout), result. Tests real loopback successful 10 MB, recovery,
RSSI unavailable, RTT loss. Persist before ACK.
- [x] Write/run failing loopback tests.
- [x] Implement CLI/server and companion; run all tests.

## Task 3: Native adapters
Files: `macos/RSSIHelper.swift`, app plist/build/launch scripts,
`esp32/WifiReceiver/WifiReceiver.ino`, config example.
- [x] Check native API contracts from SDK, add adapter tests.
- [x] Implement helper and firmware using shared wire contract.
- [x] Compile Swift and ESP if toolchains available; record untested hardware.

## Task 4: Documentation and final validation
Files: README, protocol docs, sample CSV labelled simulation, verification notes.
- [x] Document install, offline operation, failure recovery, identities and caveats.
- [x] Run unittest, compile checks, review source independently, fix regressions.

## Execution ledger
User approved implementation in this session. New independent project, no existing
repository modified. No commits/push requested; leave files ready for review/upload.
Ruling: use native inline execution, not more approval rounds: user explicitly asked to build.

Task 1 complete: protocol/store/receiver tests, fragmentation, formula, timeout,
partial EOF, raw exports, atomic upsert. Test expectation corrected to allow
partial recv (the test initially incorrectly assumed one recv returns all bytes).
Task 2 complete: full 10 MB TCP test, RTT, ID recovery, durable ACK queue and CLI.
Task 3 complete: Swift app compiles/signs; ESP sketch compiles PSRAM disabled.
Ruling: use installed Arduino-ESP32 3.3.12 rather than provisional 3.3.2 so compile
checks use the actual available SDK. Cost: user should install documented version.
Ruling: LittleFS stores report, Preferences only token; NVS is unsuitable for
large raw RSSI JSON. Cost: first-use filesystem initialization and fixed partitions.
Task 4 complete: docs + independent review, token malformed regression RED→GREEN;
added late echo, lost ACK, no-connect recording, safe CSV and RTT attempt-count tests.
Final verification: 24 unittest tests PASS, compileall PASS, both CLI help PASS,
Swift build/sign PASS, ESP compile PASS (947461-byte sketch, 50480-byte globals).
No hardware radio/Windows execution tested; no GitHub push or commits performed.
