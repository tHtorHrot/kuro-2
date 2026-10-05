# Pengujian dan CI

## Apa yang diuji

| Lapisan | Kasus |
|---|---|
| Configuration/secret | URL salah, pepper pendek, host wildcard, timezone salah, debug/docs production, sumber secret ambigu, file hilang/terlalu besar, generator menolak overwrite |
| Crypto | Token acak, HMAC terikat owner, pepper salah, format rusak, pemisahan token API/pairing |
| Policy | Training/retensi/harga tidak jelas ditolak; premium selalu memerlukan persetujuan; restricted tidak ke cloud |
| HTTP | Auth, scope, readiness, error privacy, host allowlist, batas body/waktu, limiter, proxy spoofing, metric cardinality, commit gagal sebelum respons sukses |
| PostgreSQL native | Isolasi baca/tulis dua owner, no-context deny, context reset pada reuse/rollback, hak DDL/role/audit, revoke/expired/suspend, pairing TTL/attempt/race/replay/uniqueness |
| Packaging/deployment | Build wheel/sdist; CI menguji image production, migrasi dua kali, doctor, readiness |

Test suite tidak mengakses akun Telegram, OpenRouter, atau data pribadi. Semua nilai yang
terlihat seperti password pada `compose.test.yaml` adalah kredensial publik untuk cluster
test sementara yang tidak memiliki published port dan tidak digunakan untuk produksi.

Runtime smoke juga memeriksa bahwa pemetaan port API adalah `127.0.0.1:8000`, lalu
memanggil readiness dari host tanpa proxy. Healthcheck di dalam container saja tidak cukup
untuk menerima deployment. Hotfix dan pemeriksaan Windows ada di `HOTFIX_LOCALHOST.md`.

## Unit test

```bash
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/unit
```

HTTP unit test memakai ASGI transport dan stub database terbatas. Itu menguji boundary,
bukan membuktikan perilaku PostgreSQL. Pengujian database menggunakan class Database nyata
dan SQL PostgreSQL melalui driver psycopg.

## Integrasi yang disarankan

```bash
docker compose -f compose.test.yaml up --build --abort-on-container-exit --exit-code-from tests
docker compose -f compose.test.yaml down --volumes
```

Compose test memakai cluster baru dengan data di tmpfs. Bootstrap menolak database yang
namanya tidak berakhiran `_test`, role yang sudah ada, atau schema aplikasi yang sudah ada.
Jangan menjalankan bootstrap terhadap cluster bersama/produksi. `JARVIS_REQUIRE_INTEGRATION=1`
menjadikan URL test yang hilang sebagai kegagalan, bukan skip.

Pada cluster PostgreSQL 16 disposable lain, siapkan database kosong `jarvis_test`, lalu
berikan tiga URL melalui lingkungan lokal yang aman:

| Variabel | Pengguna/kegunaan |
|---|---|
| `JARVIS_TEST_ADMIN_URL` | Administrator cluster test, skema URL `postgresql://` |
| `JARVIS_MIGRATION_DATABASE_URL` | `jarvis_migrator`, URL `postgresql+psycopg://` |
| `JARVIS_TEST_DATABASE_URL` | `jarvis_app`, URL `postgresql+psycopg://` |
| `JARVIS_REQUIRE_INTEGRATION` | `1` |

Semua URL harus menunjuk host/port/database test yang sama. Password pada URL app/migrator
dipakai untuk membuat role baru; jangan memasukkan kredensial produksi.

```bash
uv run python scripts/bootstrap_test_db.py
uv run jarvis migrate
uv run jarvis migrate
uv run pytest --cov=jarvis --cov-report=term-missing
```

Test membuat owner UUID baru per kasus. Gunakan cluster baru untuk setiap keseluruhan run.
Tidak memakai SQLite atau mematikan RLS agar test lewat. Kasus race pairing memerlukan
concurrency dan row locking PostgreSQL native.

## Pemeriksaan SQL tambahan tanpa server native

PGlite menjalankan PostgreSQL dalam WebAssembly. Script opsional di `tests/sql/` menerapkan
SQL Alembic pada engine tersebut dan memeriksa DDL, RLS, serta beberapa hak role.
Ini **bukan pengganti** integrasi native: versi engine berbeda, tidak menguji driver async,
pool, koneksi jaringan, authenticating role, locking lintas koneksi, atau container.

Dengan Node.js dan npm pada mesin pengujian:

```bash
npm install --prefix /tmp/jarvis-pglite-check --save-exact @electric-sql/pglite@0.5.8
JARVIS_MIGRATION_DATABASE_URL=postgresql+psycopg://jarvis_migrator:offline@localhost/jarvis_test uv run alembic upgrade head --sql > /tmp/jarvis-migration.sql
node tests/sql/verify_wasm_schema.mjs /tmp/jarvis-pglite-check/node_modules/@electric-sql/pglite/dist/index.js /tmp/jarvis-migration.sql
```

Kredensial `offline` di atas hanya membentuk URL dialect untuk output SQL; tidak membuat
koneksi jaringan. Script menurunkan session authorization menjadi `jarvis_app` sebelum
menguji haknya. `SET ROLE` dari session superuser saja tidak cukup untuk membuktikan role
switching ditolak, karena session asal masih berwenang mengganti role.

## Audit dependensi

```bash
uv export --frozen --no-dev --no-emit-project -o /tmp/jarvis-runtime-requirements.txt
uv run pip-audit --strict --disable-pip -r /tmp/jarvis-runtime-requirements.txt
uv build --offline
```

Build offline memerlukan build dependencies yang sebelumnya sudah tersedia di cache;
gunakan `uv build` pada lingkungan build baru yang belum memiliki cache.
Audit memeriksa advisory yang diketahui untuk dependensi Python pada saat pemeriksaan;
tidak membuktikan tidak ada celah dan tidak mencakup paket OS, image, atau konfigurasi cloud.

## CI yang disediakan

`.github/workflows/ci.yml` memiliki job unit/lint/audit dan job Compose native integration
serta runtime smoke. Action dikunci commit, akses repository read-only, dan credential
checkout tidak dipertahankan. Workflow baru dapat berjalan setelah proyek ditempatkan pada
repository yang pengguna pilih; tidak ada repository dibuat/didorong otomatis dalam sesi ini.

Pengujian yang gagal harus diperbaiki, bukan di-skip untuk lolos. Jangan mengaktifkan
integrasi model atau menyimpan dokumen nyata sebelum gate yang relevan selesai.

## Referensi implementasi

- [PostgreSQL row security](https://www.postgresql.org/docs/16/ddl-rowsecurity.html)
- [PostgreSQL SET ROLE](https://www.postgresql.org/docs/16/sql-set-role.html)
- [FastAPI dependencies with yield](https://fastapi.tiangolo.com/tutorial/dependencies/dependencies-with-yield/)
- [SQLAlchemy asyncio](https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html)
- [Docker Compose secrets](https://docs.docker.com/compose/how-tos/use-secrets/)
- [PGlite](https://pglite.dev/docs/)

## Cakupan tambahan Tahap 2A

Unit menggunakan `httpx.MockTransport`, tanpa token atau request Telegram nyata: gate
sender/chat/provenance/date, nonce setup, penolakan fallback input yang echo, file secret
LF/rollback/no-overwrite, token/config mismatch, method/host/proxy/redirect, response size,
klasifikasi connect/read/write/5xx/429, validasi update/send, dan lifecycle balasan.
Backup helper diuji dengan subprocess mock: format biner dipertahankan dan file gagal dihapus.

`tests/integration/test_telegram.py` memakai PostgreSQL native: concurrent receipt/pairing,
rollback atomik, foreign update, failed pairing replay, disable/suspend sebelum send,
crash recovery, no retry untuk hasil ambigu, batas retry dan cooldown 429, rate/age limits,
retensi/idle update-ID reset, FORCE RLS dua owner, serta lock poller eksklusif.

CI Windows menambahkan generator token/config Telegram dan backup binary tests.
CI tidak menghubungi akun Telegram nyata; smoke end-to-end bot tetap dilakukan pemilik.
PGlite checks telah diperluas ke kedua tabel baru, template/status/attempt constraints,
foreign key serta hak DELETE yang berbeda untuk receipt dan state.
Laporan terbaru disimpan di `docs/evidence/stage-2a`; bukti lama pada direktori induk
merupakan snapshot historis Tahap 1 dan tidak boleh dibaca sebagai hasil suite terbaru.

## Cakupan Tahap 2B

`test_assistant_router.py` menguji metadata fail-closed, unit harga USD/token vs per-juta,
fixed origin, zero-price free routes, ZDR/no-training, redirect/retry, response-cost/provider,
restricted/secret/context, consent digest dan UTF-16 Telegram. `test_assistant_graph_setup.py`
menguji percabangan LangGraph (tanpa konten di state), tidak ada premium tanpa approval,
tidak retry, konfigurasi file LF/no-overwrite/rollback dan pemilihan metadata teks gratis.

`test_assistant.py` memakai PostgreSQL asli untuk journal+outbox+memory, concurrent consent,
budget, expiry/replay, clear saat in-flight, pembatalan karena profil/revoke, crash recovery,
freeze, daily limit, retention termasuk request gagal sebelum snapshot, RLS dan lock worker.
Network model dan Telegram dimock; tidak ada biaya nyata pada suite ini. CI Windows
mencakup generator konfigurasi 2B. Bukti terbaru: `docs/evidence/stage-2b`, bukan hasil 2A.


## Gate Tahap 3

Image `tests` menyediakan Poppler dan Tesseract eng+ind. `compose.test.yaml`
menjalankan PostgreSQL serta Qdrant sementara, mencoba upgrade database berisi contoh
2B ke 3, memigrasi secara idempoten, lalu menjalankan suite dengan native integration
wajib. Jangan gabungkan compose.test.yaml dengan overlay runtime. Di host tanpa
PostgreSQL, 53 tes DB dapat skip; itu bukan bukti tes native lulus. Tes Qdrant terpisah
memerlukan JARVIS_TEST_QDRANT=1 pada service test terisolasi.

Lihat STAGE_3_VERIFICATION.md untuk hasil aktual pembuat paket dan KNOWLEDGE_WINDOWS.md
untuk gate Windows sebelum migrasi instalasi pemilik. Bukti versi lama tetap historis.
