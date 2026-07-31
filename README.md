# Hệ thống phân tích cổ phiếu Việt Nam

`VN30 Stock Data Web` là hệ thống thu thập, xử lý, lưu trữ và hiển thị dữ liệu cổ phiếu Việt Nam. Dự án thu thập dữ liệu thị trường bằng Dagster, lưu dữ liệu trung gian vào MinIO, nạp dữ liệu phục vụ web vào PostgreSQL và hiển thị bảng điều khiển bằng FastAPI + React/Vite.

```text
Nguồn dữ liệu -> Dagster ETL -> MinIO Bronze/Silver/Gold -> PostgreSQL warehouse -> FastAPI -> Bảng điều khiển React
```

## Giới thiệu chung

Dự án được xây dựng theo kiến trúc dữ liệu nhiều tầng để tách rõ dữ liệu thô, dữ liệu đã chuẩn hóa và dữ liệu đã sẵn sàng phục vụ ứng dụng. Dagster giữ vai trò điều phối các asset crawl và biến đổi dữ liệu; MinIO lưu các file trung gian theo mô hình Bronze/Silver/Gold; PostgreSQL lưu các bảng warehouse để backend đọc nhanh; giao diện web giúp người dùng tra cứu dữ liệu cổ phiếu, biểu đồ, tin tức và báo cáo phân tích.

Hệ thống hướng tới việc hỗ trợ quá trình phân tích nhóm cổ phiếu VN30 và thị trường Việt Nam bằng một luồng dữ liệu có thể chạy lại, kiểm tra được và dễ mở rộng thêm nguồn dữ liệu mới.

![Giao diện tổng quát hệ thống](https://github.com/user-attachments/assets/4e421b4e-e453-4305-b727-2b74aa08816c)

## Mục tiêu dự án

- Tự động hóa quá trình crawl dữ liệu giá, tin tức, báo cáo tài chính và thông tin doanh nghiệp.
- Chuẩn hóa dữ liệu từ nhiều nguồn thành cùng một cấu trúc để phục vụ phân tích.
- Lưu trữ dữ liệu theo mô hình Bronze/Silver/Gold nhằm dễ theo dõi lineage, kiểm tra chất lượng và tái xử lý khi cần.
- Nạp dữ liệu đã xử lý vào PostgreSQL để backend và dashboard truy vấn ổn định.
- Cung cấp bảng điều khiển web giúp người dùng xem biểu đồ giá, tin tức, thông tin cổ phiếu, trend/social và báo cáo phân tích AI.
- Cung cấp quy trình vận hành rõ ràng để bật hạ tầng, chạy Dagster, crawl dữ liệu và kiểm tra kết quả.

## 1. Thành phần chính

```text
.
|-- docker-compose.yaml          # PostgreSQL + MinIO + khởi tạo bucket MinIO
|-- dagster_home/                # Cấu hình Dagster instance
|-- etl_pipeline/                # Asset Dagster, tài nguyên, crawler, bộ chuẩn hóa
|-- deploy-web/                  # Backend FastAPI + giao diện React/Vite
|-- minio-viewer/                # Web nhỏ để xem file trong thư mục MinIO local
|-- trend/                       # File trend/social dùng cho web
|-- TradingAgents/reports/       # Báo cáo AI tùy chọn cho tab phân tích
|-- docs/                        # Tài liệu kiến trúc, lineage, schema dữ liệu
`-- run-dagster.ps1              # Script bật Dagster local
```

Các cổng mặc định:

| Dịch vụ | URL |
| --- | --- |
| Bảng điều khiển web | `http://localhost:4173` |
| Tài liệu API backend | `http://localhost:8000/docs` |
| Giao diện Dagster | `http://127.0.0.1:3000` |
| MinIO API | `http://localhost:9004` |
| MinIO Console | `http://localhost:9005` |
| MinIO File Viewer | `http://127.0.0.1:8765` |
| PostgreSQL | `localhost:5400` |

## 2. Yêu cầu cài đặt

Cần có:

- Docker Desktop.
- Python 3.11+.
- Node.js 18+ nếu chạy giao diện local bằng Vite.
- PowerShell trên Windows.

Các thông số mặc định trong `.env`:

```env
POSTGRES_DB=postgres
POSTGRES_USER=admin
POSTGRES_PASSWORD=change_me
POSTGRES_HOST=localhost
POSTGRES_PORT=5400
MINIO_ROOT_USER=minioadmin
MINIO_ROOT_PASSWORD=minioadmin
MINIO_ENDPOINT=localhost:9004
DATALAKE_BUCKET=warehouse
```

## 3. Chạy nhanh toàn hệ thống

Mở PowerShell tại thư mục dự án:

```powershell
cd "VN30 Stock Data Web"
```

Khởi động PostgreSQL và MinIO:

```powershell
docker compose up -d
```

Kiểm tra container:

```powershell
docker ps
```

Chạy bảng điều khiển web bằng Docker:

```powershell
cd "VN30 Stock Data Web\deploy-web"
docker compose up --build
```

Mở web tại:

```text
http://localhost:4173
```

Tài liệu API backend nằm tại:

```text
http://localhost:8000/docs
```

## 4. Hướng dẫn sử dụng bảng điều khiển web

Bảng điều khiển web đọc dữ liệu từ PostgreSQL schema `warehouse`. Vì vậy cần chạy Dagster ETL trước hoặc bảo đảm PostgreSQL đã có dữ liệu.

Các khu vực chính trên web:

- Bảng giá và nến: xem dữ liệu mở cửa, cao nhất, thấp nhất, đóng cửa và khối lượng từ bảng `warehouse.warehouse_prices_1d`.
- Thông tin cổ phiếu: đọc tổng quan, cổ đông, ban lãnh đạo và sự kiện từ các bảng warehouse tương ứng.
- Tin tức/sự kiện: đọc bảng `warehouse.warehouse_news`.
- Trend/social: đọc file trong thư mục `trend/`.
- Báo cáo phân tích AI: đọc Markdown report trong `TradingAgents/reports/`.

Quy trình dùng thường ngày:

1. Bật hạ tầng bằng `docker compose up -d` ở thư mục gốc của dự án.
2. Bật Dagster và crawl/materialize dữ liệu mới.
3. Bật web bằng `docker compose up --build` trong `deploy-web`.
4. Mở `http://localhost:4173`.
5. Nếu web chưa hiện dữ liệu mới, tải lại trang hoặc kiểm tra API tại `http://localhost:8000/docs`.

## 5. Trading Agents: cấu hình và chạy báo cáo AI

Module `TradingAgents/` dùng để tạo báo cáo phân tích AI cho từng mã cổ phiếu. Trong project này entrypoint chính là `TradingAgents/main.py`; luồng đang kích hoạt gồm:

```text
Market Analyst -> Fundamentals Analyst -> Sentiment Analyst -> News Analyst -> Bull/Bear Debate -> Coordinator
```

Kết quả được lưu dưới dạng Markdown trong `TradingAgents/reports/`. Backend web đọc thư mục này để hiển thị ở tab báo cáo phân tích AI.

### 5.1. Chuẩn bị cấu hình

Tạo file `.env` từ file mẫu và điền API key của provider muốn dùng. Không commit file `.env` lên GitHub.

```powershell
cd "VN30 Stock Data Web\TradingAgents"
copy .env.example .env
```

Ví dụ cấu hình tối thiểu trong `TradingAgents\.env`:

```env
OPENAI_API_KEY=your_openai_key
TRADINGAGENTS_OUTPUT_LANGUAGE=Vietnamese
TRADINGAGENTS_LLM_PROVIDER=openai
TRADINGAGENTS_DEEP_THINK_LLM=gpt-4.1
TRADINGAGENTS_QUICK_THINK_LLM=gpt-4.1
TRADINGAGENTS_TEMPERATURE=0.0
```

Nếu dùng provider khác, điền biến tương ứng như `GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `OPENROUTER_API_KEY`, rồi truyền `--provider` phù hợp khi chạy.

TradingAgents có thể đọc dữ liệu thị trường từ PostgreSQL warehouse của project. Khi chạy local cùng máy với Docker PostgreSQL mặc định, có thể dùng cấu hình:

```env
TRADINGAGENTS_WAREHOUSE_POSTGRES_HOST=localhost
TRADINGAGENTS_WAREHOUSE_POSTGRES_PORT=5400
TRADINGAGENTS_WAREHOUSE_POSTGRES_DB=postgres
TRADINGAGENTS_WAREHOUSE_POSTGRES_USER=admin
TRADINGAGENTS_WAREHOUSE_POSTGRES_PASSWORD=change_me
TRADINGAGENTS_WAREHOUSE_SCHEMA=warehouse
```

Nếu chạy TradingAgents trong container và PostgreSQL ở host Windows, dùng `host.docker.internal` cho `TRADINGAGENTS_WAREHOUSE_POSTGRES_HOST`.

### 5.2. Cài thư viện

Khuyến nghị dùng virtual environment riêng:

```powershell
cd "VN30 Stock Data Web\TradingAgents"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e .
```

### 5.3. Chạy báo cáo AI đầy đủ

Ví dụ tạo báo cáo cho mã `HPG` tại ngày phân tích `2026-01-29`:

```powershell
cd "VN30 Stock Data Web\TradingAgents"
.\.venv\Scripts\Activate.ps1

python main.py `
  --ticker HPG `
  --date 2026-01-29 `
  --provider openai `
  --model gpt-4.1 `
  --look-back-days 7 `
  --max-steps 8 `
  --debate-rounds 2
```

Sau khi chạy xong, file tổng hợp sẽ nằm tại:

```text
TradingAgents/reports/HPG_research_synthesis_main_2026-01-29.md
```

Các report analyst trung gian cũng được lưu trong `TradingAgents/reports/`, ví dụ market, fundamentals, news và sentiment. Khi mở web dashboard, tab báo cáo AI sẽ đọc các file Markdown này.

### 5.4. Chạy lại nhanh bằng report analyst có sẵn

Nếu đã có đủ report analyst trong `TradingAgents/reports/` và chỉ muốn chạy lại phần Bull/Bear debate:

```powershell
python main.py `
  --ticker HPG `
  --date 2026-01-29 `
  --provider openai `
  --model gpt-4.1 `
  --reuse-analyst-reports
```

Tuỳ chọn này tiết kiệm token và thời gian vì không gọi lại 4 analyst agent.

### 5.5. Chạy từng analyst riêng lẻ

Có thể chạy riêng từng agent để kiểm tra lỗi hoặc tạo từng phần báo cáo:

```powershell
python scripts\run_market_llm_agent.py --ticker HPG --date 2026-01-29 --provider openai --model gpt-4.1
python scripts\run_fundamentals_llm_agent.py --ticker HPG --date 2026-01-29 --provider openai --model gpt-4.1
python scripts\run_news_llm_agent.py --ticker HPG --date 2026-01-29 --provider openai --model gpt-4.1
python scripts\run_sentiment_llm_agent.py --ticker HPG --date 2026-01-29 --provider openai --model gpt-4.1
```

Nếu chỉ cần báo cáo kỹ thuật deterministic từ warehouse, không gọi LLM:

```powershell
python scripts\warehouse_market_agent.py --ticker HPG --date 2026-01-29
```

### 5.6. Thêm phản hồi thủ công cho lần chạy sau

Nếu muốn lưu nhận xét để các lần tổng hợp sau tham khảo:

```powershell
python scripts\add_research_feedback.py `
  --ticker HPG `
  --date 2026-01-29 `
  --issue "Báo cáo cần nhấn mạnh rủi ro biên lợi nhuận thép." `
  --correction "Khi tổng hợp, so sánh thêm xu hướng giá nguyên liệu và sản lượng tiêu thụ."
```

Feedback mặc định được lưu trong thư mục người dùng `~/.tradingagents/`. Có thể truyền `--feedback-path` cho `main.py` nếu muốn dùng file JSONL riêng.

### 5.7. Lỗi thường gặp

- Thiếu API key: kiểm tra file `TradingAgents\.env` hoặc biến môi trường tương ứng với `--provider`.
- Không kết nối được warehouse: kiểm tra PostgreSQL container, port `5400` và các biến `TRADINGAGENTS_WAREHOUSE_*`.
- Web chưa hiện report mới: kiểm tra file `.md` đã nằm trong `TradingAgents/reports/`, sau đó tải lại dashboard.
- Muốn tránh commit report sinh ra: thư mục `TradingAgents/reports/*` đã được ignore, chỉ giữ `.gitkeep`.

## 6. Chạy web local khi không dùng Docker

Backend:

```powershell
cd "VN30 Stock Data Web\deploy-web\backend"
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Giao diện:

```powershell
cd "VN30 Stock Data Web\deploy-web\frontend"
npm install
npm run dev
```

Khi chạy Vite local, giao diện thường nằm ở:

```text
http://localhost:5173
```

Nếu giao diện báo lỗi CORS, kiểm tra biến `CORS_ORIGINS` trong backend `.env` hoặc trong `deploy-web/docker-compose.yml`.

## 7. Xem file MinIO bằng MinIO File Viewer

Viewer này chỉ dùng để xem nhanh cấu trúc file local trong thư mục MinIO, không thay thế bảng điều khiển MinIO Console.

Chạy nhanh từ thư mục gốc của dự án:

```powershell
cd "VN30 Stock Data Web"
.\start-minio-viewer.bat
```

Mở:

```text
http://127.0.0.1:8765
```

Các thao tác trong viewer:

- Chọn bucket ở cột trái để xem cây thư mục.
- Dùng ô tìm kiếm để tìm file, thư mục hoặc path.
- Chọn một item để xem path, loại file, kích thước và thời gian cập nhật.
- Bật công tắc metadata nếu cần xem cả `.minio.sys`.
- Bấm làm mới sau khi Dagster vừa ghi dữ liệu mới.

## 8. Bật Dagster

Cách khuyến nghị:

```powershell
cd "VN30 Stock Data Web"
.\run-dagster.ps1
```

Nếu cần cài package ETL trước khi chạy:

```powershell
cd "VN30 Stock Data Web"
.\run-dagster.ps1 -Install
```

Script sẽ:

- Đặt `DAGSTER_HOME=VN30 Stock Data Web\dagster_home`.
- Chạy Dagster từ thư mục `etl_pipeline`.
- Nạp code location `etl_pipeline.definitions`.

Sau đó mở:

```text
http://127.0.0.1:3000
```

## 9. Crawl dữ liệu tin tức bằng Dagster UI

Asset crawl tin tức chính:

- `bronze/bronze_vietstock_news`: crawl dữ liệu thô Vietstock theo partition ngày.
- `bronze/bronze_vietcap_news`: crawl dữ liệu thô Vietcap theo partition ngày.
- `silver/silver_news`: chuẩn hóa, lọc ticker HOSE, tách một bài có nhiều ticker thành nhiều dòng.
- `gold/gold_news`: giữ dữ liệu đã chuẩn hóa để phục vụ warehouse.
- `warehouse/warehouse_news`: upsert vào PostgreSQL bảng `warehouse.warehouse_news`.
- `bulk_news_refresh`: asset bảo trì để crawl một khoảng ngày, ghi lại các partition Bronze/Silver/Gold và upsert warehouse.

Crawl một ngày bằng UI:

1. Mở Dagster UI tại `http://127.0.0.1:3000`.
2. Vào tab `Assets`.
3. Tìm `warehouse_news` hoặc nhóm asset news.
4. Chọn partition ngày cần crawl, ví dụ `2026-07-03`.
5. Bấm `Materialize selected`.
6. Theo dõi log chạy đến khi trạng thái `Success`.

Crawl nhiều ngày bằng asset maintenance:

1. Trong Dagster UI, tìm asset `bulk_news_refresh`.
2. Bấm `Materialize`.
3. Mở phần config và nhập:

```yaml
ops:
  bulk_news_refresh:
    config:
      start_date: "2026-07-01"
      end_date: "2026-07-03"
      write_warehouse: true
      vietcap_max_rounds: 1200
      vietcap_idle_rounds_to_stop: 60
      vietstock_max_pages: 1200
```

4. Chạy materialize và chờ run hoàn tất.
5. Tải lại bảng điều khiển web để xem tin mới.

## 10. Crawl dữ liệu bằng CLI

Chạy từ thư mục `etl_pipeline`:

```powershell
cd "VN30 Stock Data Web\etl_pipeline"
$env:DAGSTER_HOME="VN30 Stock Data Web\dagster_home"
```

Crawl luồng tin tức cho một partition:

```powershell
dagster asset materialize `
  -m etl_pipeline.definitions `
  --select "bronze_vietstock_news,bronze_vietcap_news,silver_news,gold_news,warehouse_news" `
  --partition "2026-07-03"
```

Crawl hàng loạt một khoảng ngày và upsert warehouse:

```powershell
dagster asset materialize `
  -m etl_pipeline.definitions `
  --select "bulk_news_refresh" `
  --config-json '{"ops":{"bulk_news_refresh":{"config":{"start_date":"2026-07-01","end_date":"2026-07-03","write_warehouse":true,"vietcap_max_rounds":1200,"vietcap_idle_rounds_to_stop":60,"vietstock_max_pages":1200}}}}'
```

Gợi ý khi chạy thử nhanh: giảm `vietcap_max_rounds`, `vietcap_idle_rounds_to_stop` và `vietstock_max_pages` để chạy nhanh hơn.

## 11. Kiểm tra dữ liệu sau khi crawl

Kiểm tra run trong Dagster:

- Trạng thái run phải là `Success`.
- Metadata của asset thường có `num_records` hoặc `rows_loaded`.
- Nếu số bản ghi bằng `0`, kiểm tra ngày crawl có tin hay không và log crawler có lỗi nguồn không.

Kiểm tra MinIO:

```text
http://127.0.0.1:8765
```

Đường dẫn thường gặp:

```text
warehouse/bronze/vietstock_news/<YYYY-MM-DD>.parquet
warehouse/bronze/vietcap_news/<YYYY-MM-DD>.parquet
warehouse/silver/news/<YYYY-MM-DD>.parquet
warehouse/gold/news/<YYYY-MM-DD>.parquet
```

Kiểm tra PostgreSQL bằng Docker:

```powershell
docker exec -it psql psql -U admin -d postgres
```

Trong psql:

```sql
select count(*) from warehouse.warehouse_news;
select source, count(*) from warehouse.warehouse_news group by source order by source;
select * from warehouse.warehouse_news order by date_posted desc limit 10;
```

## 12. Lỗi thường gặp

Port đã được dùng:

- `4173`: giao diện Docker.
- `8000`: FastAPI backend.
- `3000`: Dagster UI.
- `5400`: PostgreSQL host port.
- `9004/9005`: MinIO.

Xử lý:

```powershell
docker ps
```

Hoặc đổi port trong file compose/script tương ứng.

Dagster không nạp được code location:

- Đảm bảo chạy từ `VN30 Stock Data Web\etl_pipeline`.
- Đảm bảo đã set `DAGSTER_HOME`.
- Chạy lại `.\run-dagster.ps1 -Install`.

Web không có dữ liệu:

- Kiểm tra PostgreSQL container `psql` đang chạy.
- Kiểm tra backend docs `http://localhost:8000/docs`.
- Kiểm tra bảng warehouse đã có dữ liệu sau materialize.
- Nếu chỉ mới có dữ liệu MinIO mà chưa có PostgreSQL, cần materialize asset `warehouse_*`.

Crawler chạy lâu:

- Với Vietcap, giảm `vietcap_max_rounds`.
- Với Vietstock, giảm `vietstock_max_pages`.
- Khi chạy chính thức, dùng giá trị lớn hơn để tránh thiếu bài.

## 13. Tắt dịch vụ

Tắt web deploy:

```powershell
cd "VN30 Stock Data Web\deploy-web"
docker compose down
```

Tắt PostgreSQL và MinIO:

```powershell
cd "VN30 Stock Data Web"
docker compose down
```

Tắt Dagster:

- Nếu chạy trong terminal, bấm `Ctrl+C`.
- Nếu chạy nền, tìm process Python/Dagster đang giữ port `3000` rồi dừng process đó.
