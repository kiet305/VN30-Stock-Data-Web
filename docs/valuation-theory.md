# Nền tảng lý thuyết cho phần định giá

Tài liệu này mô tả cơ sở lý thuyết và cách project áp dụng các phương pháp định giá cổ phiếu trong dashboard. Phần định giá hiện được triển khai chủ yếu ở backend `deploy-web/backend/app/services/market_data.py`, hiển thị ở `deploy-web/frontend/src/components/StockValuationPanel.tsx` và dùng dữ liệu đã chuẩn hóa từ các bảng warehouse.

## 1. Mục tiêu của module định giá

Module định giá không cố gắng đưa ra một giá trị tuyệt đối duy nhất, mà kết hợp nhiều góc nhìn để ước tính giá mục tiêu trong 6 tháng và 12 tháng:

- Thị giá hiện tại phản ánh kỳ vọng tức thời của thị trường.
- Phương pháp so sánh multiples phản ánh cách thị trường đang định giá doanh nghiệp và nhóm ngành.
- Phương pháp DCF phản ánh giá trị nội tại dựa trên dòng tiền tự do tương lai.
- Upside cho biết biên chênh lệch giữa giá mục tiêu và thị giá hiện tại.

Công thức upside tổng quát:

```text
Upside (%) = (Giá mục tiêu / Thị giá hiện tại - 1) * 100
```

Dashboard dùng upside 12 tháng để xếp tín hiệu cổ phiếu theo hướng tích cực, trung lập hoặc rủi ro.

## 2. Dữ liệu đầu vào

Phần định giá dùng các nhóm dữ liệu chính sau:

| Nhóm dữ liệu | Nguồn trong project | Vai trò |
| --- | --- | --- |
| Giá thị trường | `warehouse_prices_1d` | Lấy close price, market cap, P/E, P/B hiện tại. |
| Chỉ số tài chính | `warehouse_ticker_metric` | Lấy EPS, BVPS, ROE, ROA, ROS và chỉ số ngành. |
| Báo cáo tài chính | `warehouse_reports` | Lấy doanh thu, lợi nhuận, vốn chủ, nợ, tiền mặt, CFO, CapEx. |
| Thông tin doanh nghiệp | `warehouse_overview` | Lấy ngành, tiểu ngành, số cổ phiếu lưu hành. |

Về mặt pipeline, các chỉ số như EPS, BVPS, ROE, ROA, ROS được tạo ở tầng Gold rồi ghi vào warehouse. Backend chỉ đọc dữ liệu đã sẵn sàng để giảm chi phí tính toán trên mỗi request.

## 3. Phương pháp multiples

Phương pháp multiples dựa trên nguyên lý: doanh nghiệp có đặc điểm tương đồng thường được thị trường định giá quanh một vùng hệ số tương đồng. Project dùng ba nhóm multiples chính: P/E, P/B và EV/EBITDA.

### 3.1. P/E

P/E đo giá cổ phiếu so với lợi nhuận trên mỗi cổ phiếu:

```text
P/E = Giá thị trường / EPS
```

Giá mục tiêu theo P/E:

```text
Target P/E = EPS dự phóng * P/E tham chiếu
```

Trong project, EPS được điều chỉnh theo tăng trưởng lợi nhuận 6 tháng hoặc 12 tháng:

```text
EPS dự phóng = EPS hiện tại * (1 + tăng trưởng lợi nhuận)
```

P/E được giới hạn trong khoảng hợp lý để tránh ngoại lệ quá lớn làm méo kết quả định giá.

### 3.2. P/B

P/B đo giá cổ phiếu so với giá trị sổ sách trên mỗi cổ phiếu:

```text
P/B = Giá thị trường / BVPS
```

Giá mục tiêu theo P/B:

```text
Target P/B = BVPS dự phóng * P/B tham chiếu
```

BVPS được điều chỉnh theo tăng trưởng vốn chủ sở hữu:

```text
BVPS dự phóng = BVPS hiện tại * (1 + tăng trưởng vốn chủ)
```

P/B đặc biệt hữu ích với các doanh nghiệp có tài sản/vốn chủ lớn và với ngành ngân hàng, nơi lợi nhuận chịu ảnh hưởng mạnh từ cấu trúc bảng cân đối.

### 3.3. Kết hợp P/E và P/B

Project kết hợp P/E và P/B theo trọng số:

```text
Target P/E-P/B = 70% * Target P/E + 30% * Target P/B
```

Ý nghĩa:

- P/E được ưu tiên vì phản ánh khả năng tạo lợi nhuận.
- P/B vẫn được giữ để phản ánh nền tảng tài sản và vốn chủ.
- Nếu một thành phần thiếu dữ liệu, hàm trung bình có trọng số chỉ dùng các thành phần còn hợp lệ.

### 3.4. EV/EBITDA

EV/EBITDA định giá doanh nghiệp ở cấp độ toàn bộ enterprise value thay vì chỉ vốn hóa cổ phần:

```text
EV = Market cap + Nợ ròng
Nợ ròng = Nợ phải trả - Tiền và tương đương tiền
EV/EBITDA = EV / EBITDA trailing
```

Do dữ liệu khấu hao có thể không đầy đủ, project dùng EBITDA proxy:

- Ưu tiên lợi nhuận hoạt động ước tính từ doanh thu, giá vốn, chi phí bán hàng và chi phí quản lý.
- Nếu không đủ dữ liệu, fallback sang lợi nhuận trailing nếu lợi nhuận dương.

Giá mục tiêu theo EV/EBITDA:

```text
EBITDA dự phóng = EBITDA trailing * (1 + tăng trưởng lợi nhuận)
Equity value = EBITDA dự phóng * EV/EBITDA tham chiếu - Nợ ròng
Target EV/EBITDA = Equity value / Số cổ phiếu lưu hành
```

Project dùng EV/EBITDA ngành làm benchmark nếu có; nếu thiếu, dùng chính EV/EBITDA của mã.

### 3.5. Multiples tổng hợp

Với doanh nghiệp không phải ngân hàng:

```text
Target multiples = 75% * Target P/E-P/B + 25% * Target EV/EBITDA
```

Lý do dùng tỷ trọng này:

- P/E và P/B là dữ liệu phổ biến, ổn định hơn với nhiều mã.
- EV/EBITDA bổ sung góc nhìn cấu trúc vốn và hiệu quả vận hành.
- Tỷ trọng 25% cho EV/EBITDA giúp mô hình có thêm chiều sâu nhưng không bị phụ thuộc quá nhiều vào EBITDA proxy.

## 4. Phương pháp DCF

DCF, tức Discounted Cash Flow, dựa trên nguyên lý giá trị nội tại của doanh nghiệp bằng hiện giá của dòng tiền tự do tương lai.

### 4.1. Dòng tiền tự do

Project ước tính dòng tiền tự do trailing theo công thức:

```text
FCF = CFO + CapEx
```

Trong dữ liệu báo cáo lưu chuyển tiền tệ, CapEx thường là dòng tiền ra nên có dấu âm. Vì vậy cộng CFO với CapEx cho ra dòng tiền tự do sau đầu tư tài sản cố định.

Nếu FCF trực tiếp không hợp lệ hoặc không dương, project dùng fallback:

```text
FCF fallback = 65% * lợi nhuận trailing
```

Nếu lợi nhuận trailing không dương nhưng doanh thu dương:

```text
FCF fallback = 6% * doanh thu trailing
```

Dòng tiền dùng cho DCF được gọi là `normalized_fcf`.

### 4.2. Tỷ lệ chiết khấu

Tỷ lệ chiết khấu phản ánh rủi ro và chi phí vốn. Project ước tính theo đòn bẩy tài chính:

```text
Leverage = Nợ phải trả / Vốn chủ sở hữu
Discount rate = 10,5% + Leverage * 1,8%
```

Kết quả được giới hạn trong vùng:

```text
9,5% <= Discount rate <= 16%
```

Ý nghĩa:

- Doanh nghiệp càng nhiều nợ so với vốn chủ thì rủi ro tài chính càng cao.
- Tỷ lệ chiết khấu cao hơn làm hiện giá dòng tiền thấp hơn.
- Giới hạn trên/dưới giúp mô hình bớt nhạy với dữ liệu bất thường.

### 4.3. Tăng trưởng dự phóng và tăng trưởng dài hạn

Tăng trưởng dự phóng ưu tiên dùng tăng trưởng lợi nhuận 12 tháng; nếu thiếu thì dùng tăng trưởng doanh thu. Giá trị này được giới hạn:

```text
-3% <= tăng trưởng dự phóng <= 18%
```

Tăng trưởng dài hạn, hay terminal growth, được lấy bằng 25% tăng trưởng dự phóng và cũng được giới hạn:

```text
1% <= terminal growth <= 4%
```

Cách làm này phản ánh giả định tăng trưởng cao hiện tại sẽ giảm dần khi doanh nghiệp bước vào trạng thái dài hạn.

### 4.4. Chiết khấu dòng tiền 5 năm

Project dự phóng dòng tiền trong 5 năm. Tốc độ tăng trưởng từng năm giảm dần từ tăng trưởng dự phóng về terminal growth:

```text
Cash flow năm n = FCF chuẩn hóa * (1 + growth năm n)^n
PV năm n = Cash flow năm n / (1 + discount rate)^n
```

Sau năm thứ 5, project dùng mô hình Gordon Growth để tính terminal value:

```text
Terminal value = FCF năm 5 * (1 + terminal growth) / (discount rate - terminal growth)
```

Giá mục tiêu DCF:

```text
Target DCF = (Tổng hiện giá dòng tiền + hiện giá terminal value) / Số cổ phiếu lưu hành
```

Trong code, dữ liệu báo cáo thường ở đơn vị tỷ đồng/triệu cổ phiếu nên giá mục tiêu được nhân hệ số `1_000_000 / issue_share` để đưa về đơn vị giá trên mỗi cổ phiếu.

### 4.5. Target DCF 6 tháng

DCF là phương pháp dài hạn, nên project không lấy toàn bộ target DCF cho khung 6 tháng. Thay vào đó, target DCF 6 tháng đi nửa đường từ thị giá hiện tại đến target DCF 12 tháng:

```text
Target DCF 6T = Thị giá hiện tại + (Target DCF 12T - Thị giá hiện tại) * 50%
```

Giả định này giúp target 6 tháng bớt cực đoan so với target dài hạn.

## 5. Blend multiples và DCF

Với doanh nghiệp không phải ngân hàng, project kết hợp:

```text
Target blended = 60% * Target multiples + 40% * Target DCF
```

Nếu không có đủ dữ liệu DCF, trọng số DCF bằng 0 và phương pháp multiples nhận 100% trọng số.

```text
Nếu có DCF:
  multiple_weight = 60%
  dcf_weight = 40%

Nếu không có DCF:
  multiple_weight = 100%
  dcf_weight = 0%
```

Cách blend này giúp cân bằng giữa:

- Định giá tương đối theo thị trường và ngành.
- Định giá nội tại theo dòng tiền.
- Khả năng chịu lỗi khi dữ liệu dòng tiền thiếu hoặc bất thường.

## 6. Xử lý riêng cho ngân hàng

Ngân hàng có mô hình kinh doanh khác doanh nghiệp phi tài chính:

- Nợ trong ngân hàng chủ yếu là tiền gửi và nguồn vốn kinh doanh, không thể diễn giải giống nợ vay doanh nghiệp sản xuất.
- EBITDA không phù hợp để đo hiệu quả ngân hàng.
- DCF dựa trên CFO/CapEx thường không phản ánh đúng hoạt động tín dụng.

Vì vậy project loại DCF và EV/EBITDA cho nhóm ngân hàng. Giá mục tiêu ngân hàng dùng:

```text
Target ngân hàng = 65% * Target P/B điều chỉnh ROE + 35% * Target P/E
```

P/B benchmark được điều chỉnh theo chất lượng sinh lời:

```text
ROE adjustment = ROE mã / ROE ngành
P/B điều chỉnh = P/B ngành * ROE adjustment
```

Trong code, `ROE adjustment` được giới hạn từ 0,75 đến 1,20; P/B sau điều chỉnh được giới hạn từ 0,4 đến 3,0. Điều này phản ánh quan điểm:

- Ngân hàng có ROE cao hơn ngành xứng đáng P/B cao hơn.
- Ngân hàng có ROE thấp hơn ngành nên bị chiết khấu P/B.
- Giới hạn giúp tránh định giá quá nhạy với dữ liệu ROE ngành bị nhiễu.

## 7. So sánh ngành và premium

Project dùng so sánh ngành để đặt từng cổ phiếu vào bối cảnh tương đối.

Premium được tính:

```text
Premium (%) = (Chỉ số của mã / Chỉ số ngành - 1) * 100
```

Ví dụ:

- P/E premium dương nghĩa là mã đang giao dịch đắt hơn ngành theo P/E.
- P/B premium âm nghĩa là mã đang giao dịch rẻ hơn ngành theo P/B.
- ROE cao hơn ngành có thể biện minh cho P/B cao hơn.

Các chỉ số so sánh gồm P/E, P/B, ROE, ROA, ROS và EV/EBITDA nếu có dữ liệu.

## 8. Xếp hạng triển vọng và rủi ro

Endpoint `/api/valuation-rankings` tính định giá cho danh sách mã theo dõi, sau đó tách thành hai nhóm:

- Nhóm triển vọng: các mã có upside 12 tháng cao nhất.
- Nhóm rủi ro: các mã có upside 12 tháng thấp nhất hoặc âm.

Frontend `ValuationMarketPanel` hiển thị:

- Thị giá hiện tại.
- Target blended 12 tháng.
- Upside 12 tháng.
- EV/EBITDA của mã so với ngành nếu có.

Mục đích của bảng xếp hạng không phải thay thế phân tích đầu tư, mà giúp người dùng nhanh chóng phát hiện mã có biên định giá đáng chú ý để phân tích sâu hơn.

## 9. Diễn giải kết quả trên dashboard

Các trường chính trong `StockValuation` có ý nghĩa:

| Trường | Ý nghĩa |
| --- | --- |
| `current_price` | Thị giá hiện tại lấy từ giá đóng cửa mới nhất. |
| `target_price_6m` | Giá mục tiêu blended 6 tháng. |
| `target_price_12m` | Giá mục tiêu blended 12 tháng. |
| `upside_6m`, `upside_12m` | Chênh lệch phần trăm giữa target và thị giá. |
| `multiple_target_price_*` | Giá mục tiêu từ nhóm multiples. |
| `pe_pb_target_price_*` | Giá mục tiêu từ P/E và P/B. |
| `ev_ebitda_target_price_*` | Giá mục tiêu từ EV/EBITDA. |
| `dcf_target_price` | Giá mục tiêu DCF 12 tháng/dài hạn. |
| `dcf_target_price_6m` | Target DCF đã làm mềm cho khung 6 tháng. |
| `discount_rate` | Tỷ lệ chiết khấu dùng trong DCF. |
| `terminal_growth` | Tăng trưởng dài hạn dùng trong terminal value. |
| `normalized_fcf` | Dòng tiền tự do chuẩn hóa. |
| `industry_comparison` | So sánh chỉ số của mã với ngành. |
| `method` | Mô tả phương pháp định giá đang áp dụng. |

Trên thang bull/bear, project đang dùng ngưỡng thực dụng:

- Upside 12 tháng từ 15% trở lên: bullish.
- Upside 12 tháng từ -10% trở xuống: bearish.
- Khoảng giữa: trung lập.

## 10. Giới hạn của mô hình

Phần định giá trong project là mô hình hỗ trợ phân tích, không phải khuyến nghị đầu tư tự động. Một số giới hạn cần lưu ý:

- Dữ liệu báo cáo tài chính có thể thiếu, trễ hoặc sai mapping criteria.
- P/E, P/B, EV/EBITDA bị ảnh hưởng mạnh bởi chu kỳ ngành và chất lượng lợi nhuận.
- DCF rất nhạy với giả định tăng trưởng, discount rate và normalized FCF.
- EBITDA trong project là proxy, không phải EBITDA kiểm toán đầy đủ.
- Ngành có ít mã so sánh sẽ làm benchmark ngành kém ổn định.
- Các yếu tố định tính như quản trị, rủi ro pháp lý, chu kỳ hàng hóa, lãi suất và tin tức chưa được đưa trực tiếp vào công thức.

Vì vậy, kết quả định giá nên được dùng như một lớp sàng lọc ban đầu, kết hợp thêm phân tích báo cáo tài chính, tin tức, xu hướng kỹ thuật và bối cảnh vĩ mô.

## 11. Gợi ý kiểm chứng mô hình

Để đánh giá chất lượng phần định giá, có thể kiểm chứng theo các hướng sau:

1. So sánh target blended với report phân tích của công ty chứng khoán cho cùng kỳ.
2. Backtest nhóm upside cao/thấp theo lợi suất 3 tháng, 6 tháng và 12 tháng.
3. Kiểm tra riêng từng ngành để tránh dùng một bộ trọng số cho mọi đặc thù kinh doanh.
4. Theo dõi độ nhạy của DCF khi thay đổi discount rate, terminal growth và normalized FCF.
5. Kiểm tra các mã thiếu dữ liệu để biết lỗi đến từ price, reports, metric hay overview.

## 12. Tóm tắt công thức chính

```text
Upside = (Target / Current price - 1) * 100

Target P/E = EPS * (1 + earnings growth) * P/E
Target P/B = BVPS * (1 + book growth) * P/B
Target P/E-P/B = 70% * Target P/E + 30% * Target P/B

EV = Market cap + Liabilities - Cash
Target EV/EBITDA = (EBITDA * (1 + growth) * EV/EBITDA benchmark - Net debt) / Shares

Target multiples = 75% * Target P/E-P/B + 25% * Target EV/EBITDA

FCF = CFO + CapEx
Discount rate = clamp(10,5% + leverage * 1,8%, 9,5%, 16%)
Terminal growth = clamp(projection growth * 25%, 1%, 4%)
Target DCF = PV(FCF năm 1-5) + PV(Terminal value)

Target blended = 60% * Target multiples + 40% * Target DCF

Target ngân hàng = 65% * Target P/B điều chỉnh ROE + 35% * Target P/E
```
