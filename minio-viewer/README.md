# MinIO File Viewer

Giao diện web nhỏ để xem nhanh cấu trúc file trong thư mục data của MinIO.

## Chạy

Chạy nhanh từ thư mục project:

```powershell
.\start-minio-viewer.bat
```

Script này luôn trỏ viewer tới data MinIO hiện tại:

```text
D:\New folder\FinalProject\minio
```

Hoặc chạy trực tiếp:

```powershell
cd "D:\New folder\FinalProject"
python .\minio-viewer\server.py
```

Mở trình duyệt tại:

```text
http://127.0.0.1:8765
```

Mặc định viewer đọc thư mục:

```text
D:\New folder\FinalProject\minio
```

Nếu muốn trỏ sang thư mục MinIO khác:

```powershell
python .\minio-viewer\server.py --root "D:\path\to\minio"
```

Metadata nội bộ `.minio.sys` được ẩn mặc định. Bật công tắc ở phần Tổng quan nếu cần xem cả metadata.

## Preview dataframe

Click vào các object dạng `.parquet`, `.csv`, `.json`, `.jsonl` hoặc `.ndjson` để xem nhanh:

- số dòng
- số cột
- tên cột
- kiểu dữ liệu
- số dòng preview tùy chọn: 10, 25, 50, 100 hoặc tất cả dòng
- số cột hiển thị tùy chọn: 12 cột, 25 cột hoặc tất cả cột
- hướng xem tùy chọn: từ trên xuống hoặc từ dưới lên

Với object `.parquet` được MinIO lưu dưới dạng thư mục `part.*`, viewer sẽ tự đọc payload bên trong để tạo preview.
