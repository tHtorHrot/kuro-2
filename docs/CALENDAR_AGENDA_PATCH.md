# Patch tampilan agenda Calendar — 4 Oktober 2026

Untuk instalasi aktif `A:\Kuro2\kuro-main`, project Docker `personal-jarvis` dan schema
`0008_executor_binding`. Pengguna sudah berhasil melakukan OAuth, grant baca revisi 2,
scheduler healthy, serta melihat hasil bot yang cocok dengan Google Calendar.

## Hasil yang dituju

Contoh ilustrasi (bukan data kalender pengguna):

```text
Jadwal Senin, 5 Oktober 2026 (WIB)

• 09.00–10.00 — Rapat tim
• 13.30–14.00 — Review proyek
• Sepanjang hari — Cuti
```

Zona diambil dari action yang dibuat berdasarkan profil pemilik, bukan zona server.
Tanggal tambahan muncul bila acara lintas hari. Acara tanpa jam lengkap mendapat
keterangan eksplisit; tidak ditebak. Agenda panjang dipotong pada batas acara dengan
jumlah acara tersisa. ID provider tetap tersimpan pada journal, tetapi tidak tampil
di daftar jadwal. Formatter tidak memanggil LLM/Google, menambah izin, atau mengubah
argumen/status/result action. Balasan operasi create/delete/approval belum diubah.

Perbaikan `tmpfs` mengikuti perubahan pengguna yang sudah berhasil:

```yaml
tmpfs: /tmp:size=16m,mode=1777
```

## Terapkan

1. Ekstrak **isi** `KURO-Calendar-Readable-Agenda.zip` langsung ke `A:\Kuro2\kuro-main`.
   Gabungkan folder dan timpa file patch dengan nama sama. ZIP tidak memiliki lapisan
   folder `kuro-main` tambahan dan tidak memuat credential.
2. Jalankan blok PowerShell berikut untuk build image runtime dan recreate assistant.
   Scheduler yang sudah sehat tetap memakai grant/token saat ini. Startup assistant
   dapat melanjutkan permintaan yang tertunda sesuai mekanisme existing.

```powershell
& {
    $ErrorActionPreference = 'Stop'
    Set-Location 'A:\Kuro2\kuro-main'
    $config = Get-Content -Raw -LiteralPath '.\.secrets\telegram_config.json' | ConvertFrom-Json
    $env:JARVIS_OWNER_ID = ([guid]$config.owner_id).ToString()
    $kuroAgendaArgs = @(
        '-p', 'personal-jarvis',
        '-f', 'compose.yaml',
        '-f', 'compose.telegram.yaml',
        '-f', 'compose.assistant.yaml',
        '-f', 'compose.knowledge.yaml',
        '-f', 'compose.calendar.yaml',
        '--profile', 'assistant'
    )
    function Invoke-KuroAgenda {
        & docker compose @kuroAgendaArgs @args
        if ($LASTEXITCODE -ne 0) { throw 'Pembaruan agenda gagal; periksa error di atas.' }
    }
    Invoke-KuroAgenda config --quiet
    Invoke-KuroAgenda build assistant
    Invoke-KuroAgenda up -d --no-deps --no-build --force-recreate --wait --wait-timeout 180 assistant
    Invoke-KuroAgenda exec -T assistant jarvis assistant-status
}
```

3. Kirim `apa jadwalku besok?` lagi ke chat privat bot. Pesan lama tidak ditulis ulang.
   Cocokkan tanggal/jam/judul dengan Google Calendar. Laporkan balasan baru; judul boleh
   disamarkan. Tidak perlu mengulang setup OAuth, grant, migrasi, atau `down`.

## Verifikasi dan batas

- 16 tes terarah lulus (formatter dan existing Stage 4 checks); lint/format bersih.
- Semua mount tmpfs pada Compose yang tersedia diperiksa sebagai lokasi absolut.
- Assertion integrasi read kini memeriksa judul/zona pada balasan dan ID pada journal.
  Native integration/Docker tidak dijalankan ulang di lingkungan asisten.
- 444 tes Docker sebelumnya dan read E2E dilaporkan lulus oleh pengguna sebelum patch.
  Penerimaan tampilan baru tetap menunggu hasil pada instalasi pengguna.
- Scope tetap baca saja. Stage 4 belum dibekukan; Stage 5–8 belum selesai.

Rujukan semantik:
- https://docs.docker.com/reference/compose-file/services/#tmpfs
- https://developers.google.com/workspace/calendar/api/v3/reference/events
