# Bukti pelajaran AO #4: baseline rute pin-sha (11 Okt 2026)

Katalog publik 11 Okt: 458 model, 15 gratis teks (harga model nol).
Rute produksi `apodex/apodex-1.1-mini:free via novita/bf16` masih ada;
Qwen/DeepSeek/Llama sudah tidak ada.

## Kode (tanpa kredensial)

* `src/jarvis/assistant/route_baseline.py`: aktif (model + provider +
  hash harga + tanggal verifikasi katalog) + 2 standby
  (`google/gemma-4-31b-it:free`, `nvidia/nemotron-3.5-lightning:free`,
  provider None) + `policy: manual-switch-only`.
* `assistant-catalog` sertakan `"baseline"`: on_baseline /
  pricing_drift / known_standby. Tanpa fallback otomatis — ganti rute
  hanya via edit config → restart → enable; router verifikasi live
  setiap dispatch.

## Tes + gate

* Unit `test_route_baseline.py`: bentuk baseline + 4 kasus
  perbandingan (aktif, drift, standby, asing).
* Gate native 11 Okt: **679 passed / 0 failed** (XML 768, subtests 89),
  schema `0016_memory_projects`, source
  `9371f779b075bd38612bd1818341010134ade8355602d4841d249a913c19f0c8`,
  `verdict: passed`, ruff bersih.
