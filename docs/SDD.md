# SDD — Ứng dụng phân tích 55 cổ phiếu BĐS HOSE + vĩ mô Việt Nam

Phiên bản 1.0 · 2026-11-09 · Trạng thái: đã triển khai và kiểm thử (xem mục 11).

## 1. Mục tiêu

Một web app chạy hoàn toàn trên máy cá nhân (Windows và macOS), không cần cài đặt, cho học sinh/sinh viên không có nền tảng IT:

- Lấy giá mở cửa / đóng cửa (kèm cao, thấp, khối lượng, giá điều chỉnh) hằng ngày của 55 mã trong sheet `DS DN BĐS`, từ 2018-01-02 tới hiện tại.
- Phân tích từng mã theo các cột trong sheet: giá đóng cửa, nợ/tổng TS, nợ/vốn CSH, tổng TS, tăng trưởng doanh thu, tiền/tổng TS, ROA, ROE, EPS, P/E; cộng thêm chỉ số từ giá (lợi suất, CAGR, biến động, sụt giảm tối đa, beta, MA).
- Nút **Làm mới dữ liệu** chỉ tải các ngày còn thiếu; app cũng tự làm mới mỗi lần khởi động.
- Lưu toàn bộ dữ liệu dạng CSV; tải CSV cho 1 mã, 1 nhóm (theo phân khúc hoặc tự chọn) hoặc toàn bộ (ZIP).
- Tab **Vĩ mô**: 7 mục của sheet `Chỉ số vĩ mô`, từ 2018, có đối chiếu chéo và link nguồn.
- Tab **Cài đặt**: API key Claude / Gemini / OpenAI (tuỳ chọn). Không có key app vẫn chạy đầy đủ, dữ liệu lấy bằng code thuần.
- Dữ liệu cũ: khung **đỏ** ghi rõ ngày dữ liệu cuối cùng.
- Song ngữ Việt / Anh, mọi chỉ số có công thức và giải thích, mọi nguồn có link.

Ngoài phạm vi: khuyến nghị mua/bán, tài khoản người dùng, truy cập từ máy khác (server chỉ nghe `127.0.0.1`), dữ liệu trong phiên.

## 2. Đóng gói (đã chốt với người dùng: Python + runtime đóng kèm)

```
BDS-HOSE-App/
  Mo ung dung (Windows).bat     ← bấm đúp trên Windows
  Mo ung dung (Mac).command     ← bấm đúp trên macOS (lần đầu: chuột phải → Open)
  HUONG_DAN.txt                 ← hướng dẫn tiếng Việt
  app/                          ← code + giao diện + dữ liệu CSV có sẵn
  runtime/mac-arm64|mac-x64|windows-x64/python   ← Python 3.12 portable (python-build-standalone)
```

- Code chỉ dùng thư viện chuẩn Python; Chart.js nằm sẵn trong `app/static/vendor/` (không dùng CDN).
- Gói chứng chỉ CA (`core/cacert.pem`) đi kèm để HTTPS chạy được trên runtime portable.
- `tools/build_dist.py` tải runtime (kiểm tra SHA256), bỏ phần thư viện không dùng, tạo thư mục và file ZIP (~92 MB).
- Launcher macOS tự gỡ cờ quarantine; nếu thiếu runtime thì dùng `python3` của máy.

## 3. Kiến trúc

```
Trình duyệt (vanilla JS + Chart.js)
        │  HTTP 127.0.0.1:8686 (tự chuyển cổng kế tiếp nếu bận)
        ▼
server.py (ThreadingHTTPServer, thư viện chuẩn)
  ├─ GET  /api/overview          bảng 55 mã + chỉ số + trạng thái dữ liệu
  ├─ GET  /api/stock/<MÃ>        giá, chỉ số, BCTC theo quý, đối chiếu
  ├─ GET  /api/series?tickers=   chuỗi giá điều chỉnh để so sánh
  ├─ GET  /api/macro             toàn bộ vĩ mô + trạng thái
  ├─ GET  /api/download?kind=prices|fundamentals|both|macro&tickers=A,B|ALL
  ├─ POST /api/refresh           chạy nền: VN-Index → 55 mã → BCTC → vĩ mô
  ├─ GET  /api/job, /api/status  tiến độ, độ mới dữ liệu
  └─ GET/POST /api/settings, POST /api/ai
core/
  net.py          HTTP + retry, dừng sớm khi mất mạng
  store.py        CSV/JSON, ghi file nguyên tử (file tạm → đổi tên)
  prices.py       nguồn giá + đối chiếu + làm mới tăng dần
  fundamentals.py BCTC quý VNDirect
  analysis.py     công thức chỉ số (hàm thuần, có unit test)
  macro.py        IMF, World Bank, Vietcombank, SJC, bảng thủ công
  ai.py           Claude / OpenAI / Gemini qua HTTP
```

POST chỉ chấp nhận yêu cầu từ chính trang của app (kiểm tra `Origin`), chống trang web lạ gọi vào.

## 4. Dữ liệu và lưu trữ (`app/data/`)

| File | Nội dung |
|---|---|
| `tickers.json` | 55 mã, chuyển một lần từ file Excel |
| `prices/<MÃ>.csv`, `prices/VNINDEX.csv` | `date,open,high,low,close,volume,value,adj_open,adj_high,adj_low,adj_close,floor,source,xcheck` – giá nghìn đồng |
| `fundamentals/<MÃ>.csv` | theo quý: tổng TS, nợ phải trả, vốn CSH, tiền, doanh thu thuần, LNST, LNST cty mẹ, vốn góp |
| `macro/cpi.csv, fx.csv, gold.csv, gold_sjc.csv, gdp_annual.csv` | `period,value,unit,source,source_url,xcheck_value,xcheck_source,xcheck` |
| `macro/curated_*.json` | bảng thủ công có link (lãi suất NHNN, GDP quý, văn bản pháp luật) |
| `status.json` | lần làm mới, lỗi theo nguồn, ngày dữ liệu cuối |
| `settings.json` | ngôn ngữ, API key (chỉ trên máy; không đóng gói vào bản phát hành) |

**Làm mới tăng dần.** Đọc ngày cuối trong CSV, tải từ ngày cuối − 7 ngày, gộp theo ngày. Nếu giá điều chỉnh của các ngày trùng thay đổi > 0,1% (có cổ tức/chia tách mới) thì tải lại toàn bộ lịch sử của mã đó để chuỗi điều chỉnh nhất quán.

**Giá gốc và giá điều chỉnh.** `open/close` là giá giao dịch thực tế (đúng nghĩa "giá mở cửa/đóng cửa"); `adj_*` là giá đã điều chỉnh, dùng để tính mọi % thay đổi.

## 5. Nguồn và đối chiếu chéo

| Dữ liệu | Nguồn chính | Đối chiếu | Quy tắc |
|---|---|---|---|
| Giá 55 mã | VNDirect finfo (giá gốc + điều chỉnh) | SSI iBoard, VPS, CafeF (giá gốc 30 phiên gần nhất) | KL khớp lệnh lệch ≤ 2% (lô lẻ); % ngày khớp với giá điều chỉnh **hoặc** giá gốc (≤ 0,5 điểm %) vì mỗi nguồn điều chỉnh cổ tức khác nhau; giá gốc = CafeF (± 1 bước giá) |
| Dự phòng khi VNDirect lỗi | CafeF (giá gốc + điều chỉnh) | SSI, VPS | như trên |
| VN-Index | VNDirect | DNSE (Entrade), SSI | điểm đóng cửa lệch ≤ 0,1% |
| Lạm phát CPI (tháng) | **Cục Thống kê – nso.gov.vn**: thông cáo "Chỉ số giá tiêu dùng, chỉ số giá vàng và chỉ số giá đô la Mỹ" hằng tháng, đọc qua API WordPress của trang; tháng nào thông cáo giá không nêu số so cùng kỳ thì đọc từ báo cáo KT-XH cùng tháng; còn thiếu thì tính từ chính số liệu NSO: (1+yoy[t]) = (1+yoy[t−1])·(1+mom[t])/(1+mom[t−12]). Kết quả: 106/106 tháng từ NSO (101 số công bố + 5 số tính từ số liệu NSO) | IMF SDMX (chỉ để đối chiếu); World Bank (bình quân năm) | ≤ 0,1 điểm %. Hiện 105/105 tháng có IMF đều khớp (số tự tính lệch ≤ 0,01) |
| Lãi suất điều hành | **sbv.gov.vn** (đọc trực tiếp mức đang áp dụng, số quyết định, liên ngân hàng qua đêm) + bảng các lần điều chỉnh từ 2018 | baochinhphu.vn / sbv.gov.vn cho từng quyết định (11/11) | mức trên sbv.gov.vn phải khớp dòng cuối của bảng |
| GDP | Thông cáo NSO (quý, thủ công) | World Bank (năm) | ≤ 0,2 điểm % |
| Tỷ giá USD/VND | **sbv.gov.vn – tỷ giá trung tâm hằng ngày 02/01/2018 → nay** qua API của trang "Biểu đồ tỷ giá trung tâm" (2.180 ngày; bình quân tháng 104/107 tháng. Cơ sở dữ liệu công khai của NHNN không có thông báo 01–03/2025 – đã kiểm tra dữ liệu thô 2.500 bản ghi – nên 3 tháng này dùng tỷ giá chính thức do NHNN báo cáo cho IMF. Ngày lấy theo trường NgayBatDau vì một số tiêu đề ghi sai năm) | IMF bình quân tháng (≤ 1%; 100/100 tháng khớp), Vietcombank (trong biên độ ±5%), World Bank (năm) | Tường lửa NHNN chặn khi gọi dồn dập: app chỉ gọi 1 request mỗi lần làm mới; lịch sử đã đóng gói sẵn |
| Giá vàng | **Chỉ số giá vàng của Cục Thống kê** (% so cùng kỳ, 95/100 tháng) – chỉ số chính thức | Giá vàng miếng SJC (webgia.com dẫn SJC; sjc.com.vn chặn truy cập tự động) và giá thế giới IMF quy đổi – để tham chiếu | Chỉ số NSO đo vàng nhẫn/trang sức nên khác SJC (2022, 2024 phí chênh vàng miếng biến động mạnh): hiển thị cạnh nhau, không gắn LECH |
| Văn bản pháp luật | bảng thủ công, link chính thống **vanban.chinhphu.vn / congbao.chinhphu.vn / Bộ Tư pháp** (22/22 văn bản) | LuatVietnam (bản tham khảo) | mọi link kiểm tra HTTP 200 và có số hiệu văn bản |

Kết quả đối chiếu thực tế lúc đóng gói: 98,6% số phiên giá khớp. Phần lớn chênh lệch nằm ở giai đoạn mã còn giao dịch trên UPCoM (LEC, NTC), nơi các nguồn ghi nhận giá khác nhau. VN-Index có 37/2.207 phiên mà VNDirect khác cả SSI lẫn DNSE; app hiện rõ các phiên này.

## 6. Chỉ số (giải thích đầy đủ trong tab "Giải thích chỉ số")

- Từ giá: % thay đổi 1 tuần/1 tháng/3 tháng/YTD/1 năm/từ 2018, CAGR, độ biến động năm hoá (σ ngày × √252), max drawdown, beta 1 năm so với VN-Index, MA20/50/200, cao/thấp 52 tuần.
- Từ BCTC (theo sheet): Nợ/TS = Nợ phải trả/Tổng TS; Nợ/VCSH; Tổng TS; tăng trưởng doanh thu so cùng kỳ (và TTM); Tiền/TS; ROA = LNST 4 quý / TS bình quân; ROE = LNST 4 quý / VCSH bình quân; EPS = LNST cty mẹ 4 quý / (vốn góp / 10.000); P/E = giá / EPS (để trống khi EPS ≤ 0). TTM chỉ tính khi đủ 4 quý liên tiếp.
- Nguồn thiếu số liệu thì ghi "chưa có", không ước tính.

## 7. Dữ liệu cũ (yêu cầu bắt buộc)

- Phiên kỳ vọng = ngày làm việc gần nhất đã đóng cửa (sau 15:30 giờ VN).
- Cũ nếu ngày cuối của VN-Index < phiên kỳ vọng, **trừ khi** đã có lần kiểm tra thành công sau 17:00 của ngày đó mà nguồn không có dữ liệu mới (ngày nghỉ lễ). Cách này không cần lịch nghỉ lễ cố định.
- Khi cũ: khung đỏ đầu trang "DỮ LIỆU CHƯA CẬP NHẬT: … chỉ tính đến hết ngày dd/mm/yyyy", ô ngày tô đỏ, liệt kê nguồn lỗi. Mỗi mã thiếu phiên mới có nhãn đỏ riêng. Mỗi chỉ số vĩ mô có cảnh báo đỏ riêng khi lần tải lỗi hoặc kỳ mới nhất quá cũ.
- Mất mạng: job dừng sau 3 mã lỗi liên tiếp (khoảng 2 giây), không treo.

## 8. AI (tuỳ chọn)

- Key lưu ở `data/settings.json` (chmod 600 trên macOS); giao diện chỉ hiện 4 ký tự cuối; trường để trống là giữ key cũ.
- Server gọi API nhà cung cấp kèm số liệu tóm tắt của mã/vĩ mô đang xem. Lời nhắc hệ thống yêu cầu chỉ dựa trên số liệu được đưa, không bịa, không khuyến nghị mua bán.
- Model mặc định (có thể sửa trong Cài đặt): Claude `claude-opus-5-5`, OpenAI `gpt-5-mini`, Gemini `gemini-2.5-flash`.
- Việc lấy dữ liệu mới luôn dùng code thuần, không phụ thuộc AI. AI không dùng để tạo số liệu, vì số liệu do AI sinh ra không kiểm chứng được.

## 9. Dữ liệu trong file Excel cần lưu ý (hiển thị trong app, không tự sửa)

1. VIC: sheet ghi "k chọn, vì này là cty mẹ rồi". Theo lựa chọn của người dùng: giữ, gắn nhãn cảnh báo, có tuỳ chọn ẩn.
2. Dòng 45 `NBB` không có tên; dòng 46 `NVT` mang tên "CTCP Đầu tư Năm Bảy Bảy". Đây là tên của NBB; NVT là CTCP BĐS Du lịch Ninh Vân Bay.
3. Mã niêm yết HOSE sau 2018 (VHM, CRE, HPX, SGR, VPI, FIR, SZC, AGG, CKG, BCM, NHA, DXS, KHG, SIP, LEC, NTC): dữ liệu trước đó là UPCoM/HNX nếu có (cột `floor`), biểu đồ có vạch đánh dấu ngày niêm yết.

## 10. Hạn chế đã biết

- Nguồn giá (VNDirect, SSI, VPS, CafeF) và vàng SJC (webgia.com) là API/trang công khai không chính thức, có thể đổi định dạng. App ghi rõ lỗi và chuyển nguồn dự phòng khi có thể.
- Lãi suất NHNN, GDP quý, văn bản pháp luật là bảng thủ công (kiểm tra ngày 09/11/2026), không tự cập nhật. Số GDP quý là số công bố lần đầu.
- Bản Windows được kiểm thử tự động trên máy Windows thật của GitHub Actions (`.github/workflows/test.yml`): build gói, chạy unit test bằng Python đi kèm, mở app bằng file `.bat`, chờ tự làm mới, gọi mọi API và tải CSV/ZIP. Runtime Windows có sẵn vcruntime140.dll nên không cần VC++ Redistributable.
- AI: chưa thử với key thật (người dùng chọn không cung cấp key, 10/11/2026). Đã kiểm chứng tối đa khi không có key: gọi API thật của Claude, OpenAI, Gemini bằng key giả → cả ba trả lỗi xác thực (401/400 "API key not valid"), tức endpoint, header và định dạng request được chấp nhận, và không lộ key trong thông báo lỗi; unit test đọc phản hồi thành công theo đúng cấu trúc của từng nhà cung cấp (kể cả trường hợp Claude từ chối). Tên model OpenAI/Gemini mặc định sửa được trong Cài đặt.
- Nguồn chính thống đã dùng trực tiếp: nso.gov.vn (CPI 106/106 tháng, chỉ số giá vàng 100/100, chỉ số giá USD, GDP), sbv.gov.vn (lãi suất, tỷ giá trung tâm 104/107 tháng), vanban.chinhphu.vn/congbao.chinhphu.vn/Bộ Tư pháp/baochinhphu.vn (22/22 văn bản, 11/11 quyết định lãi suất). Ngoài .gov.vn chỉ còn: 3 tháng tỷ giá 01–03/2025 (NHNN không công bố trong cơ sở dữ liệu công khai → số NHNN báo cáo IMF) và giá vàng miếng SJC dùng để tham chiếu (sjc.com.vn chặn mọi truy cập tự động bằng Cloudflare, kể cả từ máy chủ GitHub; lấy qua webgia.com).
- Lần đầu mở trên macOS/Windows sẽ có cảnh báo "nhà phát triển không xác định" vì không ký số; HUONG_DAN.txt có hướng dẫn.

## 11. Giao diện bảng Tổng quan

- Cột STT và Mã được khoá (sticky) khi kéo ngang.
- Nút "Chọn cột hiển thị": bật/tắt từng cột, có mẫu "Chỉ cột cơ bản", "Giá + tài chính", "Hiện tất cả"; lựa chọn được nhớ trên trình duyệt.

## 12. Kiểm thử đã chạy

- 32 unit test, gồm bộ đọc thông cáo NSO (nhiều kiểu câu qua các năm, chữ Unicode tách, số bị chèn dấu cách) và trang NHNN (`python -m unittest discover -s tests`): gộp dữ liệu, đối chiếu (lô lẻ, ngày chia cổ tức, VN-Index), chỉ số giá và BCTC (so với giá trị tính tay), làm mới tăng dần, dự phòng CafeF, mất mạng giữ dữ liệu cũ, tải lại khi có cổ tức, độ mới dữ liệu/ngày lễ, xuất CSV/ZIP, ẩn API key, quy đổi đơn vị giá vàng.
- Smoke test API thật và tải toàn bộ 55 mã + vĩ mô: không lỗi.
- Kiểm tra giao diện bằng trình duyệt thật (Playwright/Chrome): 7 tab, tiếng Việt/Anh, sáng/tối, màn hình 1400px và 390px, tải CSV/ZIP. Không có lỗi JavaScript.
- Giả lập mất mạng: khung đỏ hiện đúng ngày dữ liệu cuối; từng thẻ vĩ mô báo lỗi riêng.
- Giải nén bản ZIP vào thư mục mới, chạy launcher macOS với runtime đi kèm: khởi động, HTTPS và tự làm mới đều chạy; runtime x64 chạy qua Rosetta.
