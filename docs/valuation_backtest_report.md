# Backtest định giá từ warehouse

- Mốc tín hiệu hợp lệ: 2021-09-30 đến 2024-12-31
- Số mốc quý quét được từ giá: 20
- Số mốc quý có đủ dữ liệu định giá: 14
- Số tín hiệu hợp lệ: 5,730
- Coverage trung bình mỗi kỳ: 409 mã
- Tránh look-ahead: BCTC quý giả định có sau 45 ngày, BCTC Q4/năm sau 90 ngày.
- Universe lọc nhanh: market cap > 500 tỷ và turnover proxy > 100,000.

## Hiệu suất theo phương pháp

| score            | horizon           |    n |   periods |   top_return |   bottom_return |   long_short |   hit_rate |   rank_ic |
|:-----------------|:------------------|-----:|----------:|-------------:|----------------:|-------------:|-----------:|----------:|
| upside_12m       | actual_return_12m | 5702 |        14 |       0.0876 |         -0.0124 |       0.1001 |     0.5590 |    0.1238 |
| dcf_upside       | actual_return_12m | 5360 |        14 |       0.0662 |         -0.0302 |       0.0964 |     0.5351 |    0.1101 |
| dcf_upside       | actual_return_6m  | 5374 |        14 |       0.0329 |         -0.0212 |       0.0541 |     0.4983 |    0.0882 |
| ev_ebitda_upside | actual_return_12m | 3793 |        14 |       0.0820 |          0.0360 |       0.0460 |     0.5484 |    0.0995 |
| upside_12m       | actual_return_6m  | 5716 |        14 |       0.0275 |         -0.0055 |       0.0330 |     0.5122 |    0.0732 |
| dcf_upside       | actual_return_3m  | 5380 |        14 |       0.0244 |          0.0035 |       0.0208 |     0.5281 |    0.0697 |
| pe_pb_upside     | actual_return_12m | 5648 |        14 |       0.0524 |          0.0361 |       0.0164 |     0.5260 |    0.0376 |
| upside_12m       | actual_return_3m  | 5722 |        14 |       0.0191 |          0.0108 |       0.0084 |     0.5225 |    0.0519 |

## Cách đọc

- `top_return`: lợi suất trung bình của nhóm 20% upside cao nhất.
- `bottom_return`: lợi suất trung bình của nhóm 20% upside thấp nhất.
- `long_short`: chênh lệch top minus bottom, càng cao càng tốt.
- `rank_ic`: tương quan Spearman giữa upside dự báo và lợi suất tương lai.
