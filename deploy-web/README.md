# Deploy Web

Bộ web deploy gồm backend, frontend và tab vẽ biểu đồ nến từ dữ liệu đã lưu trong PostgreSQL.

- `backend`: FastAPI đọc dữ liệu nến từ PostgreSQL.
- `frontend`: React + Vite hiển thị giao diện tiếng Việt và biểu đồ nến.
- `docker-compose.yml`: chạy backend/frontend theo cấu hình deploy.

## 1. Backend

Tạo file `deploy-web/backend/.env`:

```env
APP_HOST=0.0.0.0
APP_PORT=8000
POSTGRES_HOST=localhost
POSTGRES_PORT=5400
POSTGRES_DB=postgres
POSTGRES_USER=admin
POSTGRES_PASSWORD=change_me
POSTGRES_SCHEMA=warehouse
POSTGRES_TABLE=warehouse_prices_1d
POSTGRES_TICKER_COLUMN=ticker
POSTGRES_DATE_COLUMN=date
POSTGRES_OPEN_COLUMN=open
POSTGRES_HIGH_COLUMN=high
POSTGRES_LOW_COLUMN=low
POSTGRES_CLOSE_COLUMN=close
POSTGRES_VOLUME_COLUMN=volume
CORS_ORIGINS=http://localhost:4173,http://localhost:5173
```

Chạy:

```bash
cd deploy-web/backend
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 2. Frontend

Chạy:

```bash
cd deploy-web/frontend
npm install
npm run dev
```

## 3. API hiện có

- `GET /api/health`
- `GET /api/tickers`
- `GET /api/candles?ticker=HPG&limit=200`
- `GET /api/candles?ticker=HPG&start_date=2024-01-01&end_date=2025-01-01`

## 4. Docker deploy

Cập nhật biến môi trường trong `deploy-web/docker-compose.yml` nếu cần, sau đó chạy:

```bash
cd deploy-web
docker compose up --build
```

- Frontend: `http://localhost:4173`
- Backend: `http://localhost:8000/docs`

## 5. Ghi chú

- Backend đọc trực tiếp bảng `warehouse.warehouse_prices_1d`.
- Có thể đổi schema, bảng và tên cột qua các biến `POSTGRES_*` trong `.env`.
- Biểu đồ dùng `lightweight-charts`, có nến giá và khối lượng giao dịch.
