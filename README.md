# Auroelic

Dashboard monitoring server real-time. Backend FastAPI + psutil membaca data langsung dari OS, frontend HTML/CSS/JS murni (tanpa build step), data dikirim lewat WebSocket, riwayat disimpan di SQLite.

## Menjalankan
    cp .env.example .env     # sesuaikan bila perlu
    ./run.sh                 # membuat venv, memasang dependensi, menjalankan server
Buka http://127.0.0.1:8000. Untuk akses jarak jauh, set `AUROELIC_HOST=0.0.0.0` dan WAJIB isi `AUROELIC_TOKEN`, serta pasang di belakang HTTPS (reverse proxy).

## API (header `Authorization: Bearer <token>` bila token diaktifkan)
- GET /api/health (tanpa auth), /api/snapshot, /api/system, /api/history?range=5m|1h|6h|24h, /api/alerts?status=all|open|resolved&limit=
- GET/PUT /api/settings (batas warning/critical CPU, memori, disk)
- WS /ws?token=...

## Struktur
backend/app: config, collector (psutil), store (SQLite), alerts (engine), main (API/WS). frontend: index.html, style.css, app.js.

## Catatan
- Memori terpakai = total - available (tanpa cache), persentase disk memakai rumus `df` (used/(used+free)).
- Partisi yang tidak bisa dibaca dilewati, tidak dipalsukan. Penyebab alert CPU/memori diambil dari proses teratas.
