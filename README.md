# cardkit – dựng thiệp theo layer

Công cụ tạo bộ thiệp cưới dưới dạng **các layer PNG cùng khung, chồng lên là khớp**, để web của khách ghép, sửa chữ và làm hiệu ứng.

## Cài đặt và mở tool (macOS / Windows)

Không cần cài Python hay gõ lệnh lập trình: lần đầu mở, tool tự tải bộ chạy riêng (Python 3.12 + thư viện, cần mạng, 3–5 phút) vào thư mục riêng của nó, không đụng gì trên máy. Từ lần sau mở trong vài giây.

### macOS

1. Mở **Terminal** (bấm ⌘ + Space, gõ `Terminal`, Enter).
2. Dán lệnh sau rồi Enter (thay `<địa chỉ repo>` bằng link người bán gửi):
   ```bash
   git clone <địa chỉ repo> ~/ThiepTool && open ~/ThiepTool
   ```
   Máy chưa có git thì macOS hiện bảng *"cài công cụ dòng lệnh"* → bấm **Cài đặt**, đợi xong rồi dán lại lệnh trên.
3. Trong thư mục **ThiepTool** vừa mở: **bấm đúp `MoTool-Mac.command`**. Cửa sổ Terminal hiện lên – để nguyên trong lúc dùng tool; trình duyệt tự mở bàn làm việc.
   - Báo *"không có quyền"* / không mở được: trong Terminal gõ `bash ~/ThiepTool/MoTool-Mac.command`.

### Windows

1. Chưa có git: cài **Git for Windows** tại <https://git-scm.com/download/win> (cứ bấm Next).
2. Mở **PowerShell** (bấm phím Windows, gõ `PowerShell`), dán lệnh rồi Enter:
   ```powershell
   git clone <địa chỉ repo> "$HOME\ThiepTool"; explorer "$HOME\ThiepTool"
   ```
3. Trong thư mục **ThiepTool**: **bấm đúp `MoTool-Windows.bat`**. Cửa sổ đen hiện lên – để nguyên trong lúc dùng tool.

### Cập nhật và dữ liệu

- **Tự cập nhật**: mỗi lần mở, tool tự lấy bản mới (`git pull`); mất mạng thì vẫn mở bản đang có.
- **Dữ liệu của bạn** (mẫu thiệp, font tự thêm, thiệp đã xuất) nằm ở `Documents/ThiepTool` – **ngoài** thư mục tool, nên cập nhật, xoá hay tải lại thư mục tool không mất gì.
- Không dùng git: tải ZIP của repo về, giải nén rồi bấm đúp như trên – chạy được nhưng **không tự cập nhật**. Trên macOS bản tải từ web bị chặn lần đầu: *System Settings → Privacy & Security → Open Anyway* (hoặc dùng lệnh `bash …/MoTool-Mac.command`).
- Bộ chạy nằm ở `~/Library/Application Support/ThiepTool` (macOS) hoặc `%LOCALAPPDATA%\ThiepTool` (Windows) – xoá thư mục này nếu muốn cài lại từ đầu.

## Ý tưởng cốt lõi: ghép, không tách

Mọi cách "cho AI vẽ cả thiệp rồi tách layer" đều hỏng (nhoè, lệch, thừa/thiếu hoa văn, càng sửa càng sai), vì tách một ảnh đã phẳng là bài toán **không có lời giải chính xác**. Công cụ này làm ngược lại:

| Thành phần | Ai làm | Vì sao |
|---|---|---|
| Nền | AI vẽ **riêng**, không hoa văn, không chữ | không cần căn chỉnh |
| Hoa văn | AI vẽ **từng món riêng** (1 góc, 1 khung, 1 dải phân cách…) | mỗi món được trọn độ phân giải; code lật 1 góc thành 4 góc đối xứng tuyệt đối |
| Viền, đường kẻ, trục | **code vẽ** | thẳng tắp, sắc ở mọi kích thước |
| Chữ | **code dựng bằng font thật** (Chromium) | dấu tiếng Việt đúng 100%, đổi tên khách trong vài giây |

Các layer khớp nhau vì **code** đặt vị trí, không phụ thuộc AI. AI chỉ còn làm việc nó giỏi nhất: vẽ một vật thể đẹp đứng riêng.

---

## Cài đặt cho máy phát triển (dữ liệu ngay trong thư mục mã)

```bash
pip install -r requirements.txt
```

```bash
python -m playwright install chromium
```

Chạy `python -m cardkit studio` (hoặc tự tạo `MoTool.bat` gọi lệnh này – file đó không đưa lên repo). Ở chế độ này mẫu, thiệp xuất, font tự thêm nằm ngay trong `kits/`, `output/`, `fonts/` – các thư mục này bị `.gitignore` chặn, không lọt vào repo giao khách.

## Cách dùng: Bàn làm việc (không cần gõ lệnh)

**Bấm đúp nút mở** (`MoTool-Mac.command` / `MoTool-Windows.bat`) → trình duyệt mở bàn làm việc (tắt bằng cách đóng cửa sổ Terminal / cửa sổ đen). Trang chính có 3 việc, mỗi việc đi theo từng bước.

### Việc 1 – Thiết kế mới: AI lên bản thiết kế theo yêu cầu, không khuôn cố định

Khách viết yêu cầu tự do, **AI quyết định mọi thứ**: bao nhiêu thiệp (thiệp mời, thiệp cảm ơn, banner web…), khổ (dọc, ngang, vuông, px cho web), **hình dáng** (có sẵn hoặc đường cắt tự vẽ: trái tim, vỏ sò, cái vé…), những **món hoa văn** nào (AI tự đặt tên, tự mô tả), **bố cục từng phương án**, ô chữ, **ô ảnh cưới**, font, màu. Tool chỉ lo phần máy móc: đọc và tự sửa bản thiết kế, báo lỗi bố cục, gom món để vẽ, tách nền, ghép, dựng chữ bằng font thật.

| Bước | Làm gì |
|---|---|
| ① Yêu cầu | Gõ yêu cầu (hoặc bấm gợi ý nhanh) → *Chép tin nhắn* → dán vào **một chat mới** trên ChatGPT → chép nguyên câu trả lời dán về → *Đọc bản thiết kế* |
| ② Bản thiết kế | Thấy ngay **bản phác** mọi thiệp × phương án (chưa cần vẽ ảnh nào). Bộ thiệp **luôn có ít nhất 4 trang cùng khổ – Bìa · Thông tin hai gia đình · Thiệp mời · Cảm ơn** (prompt bắt buộc, mỗi thiệp mang `role`; thiệp khách xin thêm như banner, trái tim đứng sau 4 trang này). AI làm thiếu trang → tool báo *"còn thiếu: …"* và soạn sẵn tin nhắn thêm trang (dùng lại hoa văn đã có, không phải vẽ lại). Tool tự báo lỗi bố cục (chữ tràn mép / ra ngoài hình, chữ đè chữ, chữ đè giữa hoa văn, chữ quá nhỏ) và soạn sẵn **tin nhắn sửa lỗi**. Muốn thêm phương án hay sửa theo ý → chép tin nhắn → gửi vào cùng chat → dán câu trả lời mới → *Cập nhật* (món đã vẽ, phương án đã chỉnh tay được giữ) |
| ③ Vẽ hoa văn | Gửi tiếp các tin nhắn vẽ vào **cùng chat**; mỗi ảnh tải về kéo vào ô của nó (hoặc kéo tất cả một lần). Món lớn vẽ riêng, món nhỏ gộp tờ rồi tự cắt và gán tên |
| ④ Kết quả | Thiệp thật của mọi phương án; *✎ Chỉnh* để kéo thả tinh chỉnh; → *Làm thiệp cho khách* |

**Chi phí vẽ:** chỉ hoa văn tốn công vẽ (mỗi phong cách vẽ 1 lần, dùng lại cho mọi thiệp nhờ phóng to, lật, xoay, đối xứng). Số thiệp, số phương án bố cục, hình dáng, khổ, ô chữ là dữ liệu – thêm bao nhiêu cũng không phải vẽ lại.

**Ô ảnh cưới:** bộ file giao khách có `pieces/anh__<id>.png` (mặt nạ của ô, cùng khung với các layer) và mục `photos` trong `manifest.json`; ảnh đặt giữa `01_nen` và `02_hoa_van`.

**Font chữ** (nút *Aa Font chữ* ở trang chính): kéo file `.ttf .otf .woff .woff2` vào là thêm được (woff/woff2 tự đổi sang ttf). Tool tự kiểm tra **đủ dấu tiếng Việt** (thiếu thì AI không dùng), **quyền nhúng** (font cấm nhúng bị đánh dấu), **giấy phép** ghi trong font (OFL hay không – bộ file giao khách có kèm file font và giấy phép), tự đoán nhóm *viết tay / có chân / không chân / trang trí* (sửa được). Ô *mô tả cho AI* giúp AI biết khi nào nên chọn font đó. Trong trình chỉnh, từng ô chữ chọn được font riêng (mục *Font*). Font đang dùng ở mẫu nào thì không xoá được; font có sẵn của tool không xoá được. Thông tin sửa tay lưu ở `fonts/fonts.json`.

Mẫu tạo theo cách cũ (danh mục món cố định) vẫn dùng được; nút *Vẽ tiếp* ở trang chính mở bước vẽ của chúng.

### Việc 2 – Làm thiệp cho khách (~1 phút)

① **Chọn mẫu** → ② **Hình dáng & bố cục**: mẫu từ bản thiết kế hiện các thiệp × phương án của nó (mặc định *Theo thiết kế* – mỗi thiệp đúng hình và khổ riêng; vẫn đổi được sang hình khác) → ③ **Thông tin khách**: khổ (mặc định theo thiết kế), điền tên/ngày/địa chỉ (để trống = giữ chữ mẫu; ô cùng id dùng chung cho mọi thiệp) → ④ **Xuất** → xem trước, mở thư mục giao khách.

**Hình dáng thiệp** (cắt cả 3 layer, viền chạy song song mép hình): Chữ nhật · Bo góc · Vòm · Góc lõm · Oval · Răng cưa · Cắt góc. Dòng lệnh: `--shape vom`.

**Thư viện bố cục** – mỗi bố cục hiện bằng ảnh xem trước dựng từ chính mẫu đang chọn; chọn nhiều bố cục để làm cả bộ cùng phong cách: Khung chữ lồng · Vòm hoa · Tối giản · Hoa góc chéo · Hoa hai bên · Vòng hoa quanh tên · Thiệp mời · Thông tin hai gia đình · Cảm ơn. Bố cục không hợp hình đang chọn (vd. Thiệp mời với Vòm) tự dùng hình mặc định của nó và ghi rõ trên thẻ. Bố cục có sẵn sinh bằng `python tools/make_layouts.py` (chạy lại được).

**Chỉnh bố cục kéo thả** – nút *✎ Chỉnh bố cục* trên mỗi thẻ, hoặc thẻ *＋ Tự làm bố cục mới* (bắt đầu từ thiệp trống):

| Thao tác | Cách làm |
|---|---|
| Di chuyển | bấm chọn rồi kéo (tự hút vào trục giữa thiệp) · phím mũi tên để nhích, giữ Shift nhích xa |
| Đổi cỡ | kéo chấm xanh · hoặc thanh *Cỡ* / *Cỡ chữ* / *Rộng ô* |
| Hoa văn | đổi món, lật ngang/dọc, đối xứng (2 bản trái–phải, trên–dưới, 4 góc), độ đậm, lớp trên/dưới, nhân đôi |
| Ô chữ | tên ô (khách thấy ở bước ③), chữ mẫu, kiểu chữ, căn lề, nghiêng |
| Viền | chọn *Viền* ở danh sách: số nét, cách mép, độ dày, màu |
| Thêm / ẩn / xoá | lưới *Thêm vào thiệp* (món mẫu có) · *+ Ô chữ* · *+ Viền* · nút *Ẩn* ở danh sách · Delete · **Ctrl+Z** hoàn tác |
| Đổi hình dáng | hàng nút phía trên thiệp |
| Xem bản thật | dựng bằng đúng bộ máy xuất thiệp (~2 giây) để so |

*Lưu bố cục* → bố cục có sẵn được giữ nguyên, bản chỉnh lưu thành **bố cục riêng** (`layouts/<tên>.json`) và được chọn sẵn trong thư viện; bố cục riêng lưu đè hoặc xoá được. Bố cục dùng chung cho mọi mẫu – mẫu thiếu món thì dùng món thay như thường.

**Khổ thiệp** (dọc, ngang hay vuông): A5 14,8×21 · 15×21 · 13×18 · 12×18 · 10×15 · vuông 15×15 · A5 ngang cm (in **300 DPI**), **điện thoại 9:16** (1080×1920 px), **banner web 16:9** (1920×1080 px), hoặc **tuỳ chỉnh** rộng × cao (cm). Bố cục tự giãn theo khổ: vị trí các món giãn theo chiều dọc/ngang, còn hoa văn và chữ giữ đúng tỉ lệ – không méo. Dòng lệnh: `render <mẫu> <loại> --size 12x18` (hoặc `phone`, `11.5x17`, `720x1280px`).

### Việc 3 – Đăng lên Icard (kho mẫu thiệp online)

Đăng mẫu thành **mẫu thiệp trên Icard** (adminapi.icards.com.vn) – khách hàng Icard chọn mẫu và tự sửa tên, ngày trong editor của Icard. Cần tài khoản Icard quyền **admin** hoặc **designer** (đăng hoa văn vào thư viện: chỉ admin).

| Bước | Làm gì |
|---|---|
| ① Chọn mẫu | mẫu đã vẽ xong hoa văn |
| ② Trang & ô chữ | mặc định chọn sẵn **bộ 4 trang chuẩn của Icard: Bìa · Gia đình · Thiệp mời · Cảm ơn** (bố cục `cam_on` trong thư viện; mẫu "Thiết kế mới" thì mỗi thiệp cùng khổ một trang); bấm để bỏ/thêm (thứ tự bấm = thứ tự trang; trang 1 = bìa, ảnh đại diện) · khổ chung · hoa văn **Gộp vào nền** (gọn, khách khó làm lệch) hay **Lớp rời** (mỗi món một ảnh, khách kéo/xoá được) · từng ô chữ: **Sửa được** (khách đổi nội dung, chữ một màu – chọn màu) / **Tên khách** (Icard tự điền tên từng khách mời theo link gửi; ô `khach` mặc định là loại này) / **Khoá** (giữ chữ ánh kim, in vào thiệp) / **Bỏ** · *Dựng xem trước*: vẽ lại đúng cách Icard vẽ + ảnh đại diện |
| ③ Thông tin | đăng nhập Icard (mật khẩu chỉ gửi thẳng tới Icard, không lưu – tắt tool là phải đăng nhập lại) · tiêu đề · danh mục / nhóm / loại (lấy trực tiếp từ Icard) · *Hiển thị ngay* (mặc định **tắt** = đăng nháp, duyệt trên trang admin Icard rồi bật) · tuỳ chọn đăng từng món hoa văn vào thư viện tài nguyên Icard |
| ④ Đăng | up ảnh → đăng font còn thiếu → tạo mẫu; xong có nút mở editor admin Icard |

**Đăng lại = cập nhật đúng mẫu cũ** (mã mẫu lưu ở `kits/<mẫu>/icard.json`, tách theo server); ảnh không đổi không up lại (Icard không tự dọn ảnh thừa). Mẫu đã bị xoá trên Icard thì tạo mới.

Tool tự lo những chỗ Icard khác cardkit:

- **Font**: font biến thiên (Cormorant…) tách thành bản tĩnh đúng độ đậm (`Cormorant Garamond 600`); số thẳng hàng (lining-nums) được "đóng băng" vào file font (`… Lining`) vì Icard vẽ chữ bằng Canvas không bật được tính năng font. Font trùng tên trên Icard thì dùng luôn.
- **Vị trí chữ**: hộp chữ được đặt để đường chân chữ trùng bản cardkit theo đúng công thức vẽ của Icard (dòng cao 1,3 × cỡ chữ, căn giữa dọc); chữ in hoa ghi sẵn in hoa; chữ lồng `G|N` → `G | N`.
- **Không làm được trên Icard** (tool cảnh báo): giãn chữ (letter-spacing), chữ ánh kim/đổ bóng cho ô *Sửa được* – muốn giữ thì đặt ô đó sang *Khoá*.
- Ô ảnh cưới → ảnh giữ chỗ để khách thay (oval → khung tròn).
- Khung trang 454 px rộng như các mẫu có sẵn trên Icard (đổi được ở *Nâng cao*); chữ nghiêng giữ nghiêng.
- Ảnh đại diện dựng theo đúng quy cách thumbnail của Icard (600×400, ≥2 trang thì trang 2 nằm lệch sau).

Dòng lệnh (hàng loạt): `python -m cardkit icard preview <mẫu>` (không cần mạng; mặc định bộ 4 trang, `--pages` để tự chọn) · `python -m cardkit icard push <mẫu> --category "Thiệp Mời" --group "Thiệp Cưới" --type "Cổ Điển" --user <tài khoản>` (mật khẩu hỏi khi chạy hoặc `$ICARD_PASSWORD`; thêm `--orn layers`, `--lock chu_long`, `--drop …`, `--active`, `--assets`).

### Danh mục món – khách chọn bao nhiêu cũng được

Gói chọn nhanh: **Tối giản (5 món)** · **Tiêu chuẩn (10 món)** · **Đầy đủ (22 món)**. Món không chọn thì bố cục **dùng món cùng dáng thay vào**, không có thì **bỏ trống** (bàn làm việc liệt kê rõ trước khi xuất).

| Mã | Món | Nhóm | Ghi chú | Thiếu thì dùng |
|---|---|---|---|---|
| `nen` | Nền giấy | Bắt buộc | phủ kín thiệp, không hoa văn, không chữ | — (bỏ qua) |
| `goc` | Góc thiệp | Cơ bản | vẽ 1 góc trên-trái, tool tự lật ra 4 góc | — (bỏ qua) |
| `khung` | Khung chữ lồng (bìa) | Cơ bản | khung lớn, rỗng giữa để đặt chữ lồng | — (bỏ qua) |
| `div_dai` | Dải phân cách dài | Cơ bản | nét dài mảnh, hoạ tiết nhỏ ở giữa | — (bỏ qua) |
| `hoa_nho` | Hoa văn nhỏ | Cơ bản | hoạ tiết nhỏ dùng điểm xuyết nhiều chỗ | — (bỏ qua) |
| `nhanh` | Nhành lá cạnh thiệp | Thêm | nhành dọc mép trái, tool lật sang phải | — (bỏ qua) |
| `div_tren` | Dải phân cách ngắn | Thêm | ngắn, gọn | `div_dai` |
| `vuong_mien` | Hoa văn đầu thiệp (ngang) | Thêm | dải hoa văn lớn trên cùng thiệp | — (bỏ qua) |
| `div_hoa` | Dải hoa văn đầu cột | Thêm | dải trang trí cầu kỳ trên tiêu đề cột | `div_dai` |
| `khung_va` | Khung nhỏ chữ 'và' | Thêm | khung nhỏ dựng đứng, rỗng giữa | — (bỏ qua) |
| `hoa_cuoi` | Hoa văn cuối thiệp | Thêm | kết thúc phía dưới thiệp | `hoa_nho` |
| `la_va` | Nhành lá nhỏ cạnh chữ 'và' | Chi tiết nhỏ | nhành nhỏ nằm ngang | `hoa_nho` |
| `div_duoi` | Dải phân cách vừa | Chi tiết nhỏ | dài vừa | `div_dai`, `div_tren` |
| `div_tieude` | Dải phân cách tiêu đề | Chi tiết nhỏ | trên/dưới tiêu đề lớn | `div_hoa`, `div_dai` |
| `div_mini` | Dải phân cách mini | Chi tiết nhỏ | rất ngắn | `div_tren`, `div_dai` |
| `div_cuoi` | Dải phân cách cuối | Chi tiết nhỏ | phía dưới hai tên | `div_hoa`, `div_dai` |
| `mat_day` | Mặt dây đầu trục | Chi tiết nhỏ | hoạ tiết dọc nhỏ ở đầu trục giữa | `hoa_nho` |
| `hoa_giua` | Hoa nhỏ giữa hai tên | Chi tiết nhỏ | hoạ tiết rất nhỏ | `hoa_nho` |
| `vong_hoa` | Vòng hoa quanh tên | Thêm | vòng hoa tròn, rỗng giữa | — (bỏ qua) |
| `vom_hoa` | Vòm hoa | Thêm | hoa lá chạy theo đường vòm phía trên | `vuong_mien` |
| `bo_hoa` | Bó hoa góc | Thêm | cụm hoa lớn đặt chéo góc | `goc` |
| `day_hoa` | Dải hoa dọc | Thêm | dải hoa chạy dọc mép | `nhanh` |

Cách cũ (prompt mẹ → ChatGPT trả JSON → `import-brief`) vẫn dùng được bằng dòng lệnh; `PROMPT_ME.txt` là bản mặc định.

### Bộ demo có sẵn

```bash
python -m cardkit demo
```

Dựng lại bộ xanh lục từ `mau/1.jpg` + `mau/2.jpg` cho 2 khách (~1 phút) → `output/xanh_lily/`: `sheet.png` (4 ô: nền · hoa văn · chữ · ghép), `preview.html` (bật/tắt layer, chạy thử hiệu ứng).

> Asset của bộ demo được **cắt từ ảnh JPEG 1054px** (thiệp cũ) – chính là bài toán "tách từ ảnh phẳng" không có lời giải chính xác: hơi mềm, lá nhạt hơn, phẳng hơn bản gốc. Asset do AI vẽ **riêng từng món trên nền màu đặc** không gặp các vấn đề này.

---

## Dùng bằng dòng lệnh

```text
master-prompt "ý tưởng" [--goi toi_gian|tieu_chuan|day_du | --mon goc,khung,...]  → PROMPT_ME.txt
import-brief tra_loi_chatgpt.txt   → tạo bộ mới + PROMPTS.md
ingest <bộ>                        → raw/ → assets/ (tách nền, dọn rác, ảnh kiểm tra trong assets/_qc/)
render <bộ> <loại> --data khach.json [--scale 0.5] [--no-pieces]
check <bộ> <loại> · prompts <bộ> · init <bộ> · extract … · generate … · studio · demo
```

Ảnh tải từ ChatGPT đặt đúng tên vào `kits/<bộ>/raw/<mã món>.png`. Prompt yêu cầu ChatGPT xuất **nền trong suốt thật**, không được thì nền màu đặc #0000FF/#FF00FF, cấm ô caro. Kiểu nào tool cũng **lọc lại lần nữa**: ảnh trong suốt thật vẫn được dọn hạt lấm tấm, quầng tối, viền ám màu; ảnh có kênh trong suốt nhưng **viền ngoài vẫn là nền đặc** (AI làm nửa vời) được tách nền theo màu như thường. Tool còn tự nhận: nền **màu bão hoà** (xanh dương/hồng tím/cyan – tách theo hiệu màu, khử ánh màu phông), nền trung tính, ô caro **vẽ giả**; tự báo khi hoa văn **chạm mép ảnh** hoặc **còn ám màu phông**.

---

## Tận dụng thiệp cũ đã ưng

```bash
python -m cardkit extract xanh_lily mau/3.jpg
```

→ `kits/xanh_lily/extract/3_candidates.png` (ảnh đánh số các cụm) + `3_spec.json`. Sửa spec: đặt tên, `"keep": true`, chỉnh `box`, thêm `erase` để xoá chữ nằm trong hộp; thêm `"layout": "thiep_moi"` để sinh luôn **bản nháp bố cục**. Rồi:

```bash
python -m cardkit extract xanh_lily --spec kits/xanh_lily/extract/3_spec.json
```

Xem `kits/xanh_lily/extract/1_spec.json` và `2_spec.json` làm ví dụ đầy đủ.

---

## Bộ file giao khách

```text
output/<kit>/<loại>[__<khách>]/
  01_nen.png        nền, không trong suốt
  02_hoa_van.png    hoa văn + viền, trong suốt, cùng khung
  03_text.png       chữ mẫu, trong suốt, cùng khung
  ghep.png          ảnh hoàn chỉnh
  pieces/           TỪNG MẢNH riêng (mỗi góc, khung, dải phân cách, mỗi ô chữ) – cùng khung
  manifest.json     vị trí (bbox) từng mảnh, thông số từng ô chữ (font, cỡ, màu, căn lề, đường chân chữ)
  fonts/            font + giấy phép OFL (được phép dùng thương mại, phân phối kèm)
  preview.html      trang xem thử
```

Cách web của khách dùng:

- **Đơn giản:** chồng 3 PNG theo thứ tự 01 → 02 → 03.
- **Sửa chữ trực tiếp:** chồng 01 + 02, dựng chữ bằng HTML theo `manifest.json → texts` (font trong `fonts/`).
- **Hiệu ứng động:** dùng `pieces/` + `bbox` trong manifest làm tâm xoay/phóng (xem cách `preview.html` làm).

---

## Tham chiếu định dạng

### Layout – `ornaments` (vẽ theo thứ tự, trên cùng là cuối danh sách)

| type | Trường | Ghi chú |
|---|---|---|
| `asset` | `asset`, `x`, `y`, `w`, `h`, `anchor` | **Ô w×h**: món nào đặt vào cũng được thu vừa trong ô, giữ tỉ lệ (`"fit": "stretch"` để kéo giãn; chỉ cho `w` hoặc `h` thì theo tỉ lệ ảnh) · `anchor`: tl tc tr cl **c** cr bl bc br – điểm neo của món trong ô (góc dùng `tl`, nhành mép trái dùng `cl`) · `mirror`: `x` / `y` / `xy` · `flip`: `h` / `v` · `opacity` · `shadow: false` |
| `rule` | `x`, `y`, `length`, `thickness`, `orient` (`h`/`v`), `fill`, `fade` | đường kẻ mảnh, mờ dần 2 đầu |
| `border` | `lines: [{inset, width}]`, `fill` | viền nhiều nét, chạy theo mép hình dáng thiệp |

Món còn nhận `rotate` (độ, chiều kim đồng hồ; bản đối xứng tự xoay ngược). Bố cục có thể mang `size` (khổ riêng), `shape` (tên hình hoặc `{"path": "M…Z"}` theo toạ độ khung) và `photos` (ô ảnh: `x`, `y` tâm, `w`, `h`, `shape`). Mọi món / ô chữ đều nhận `"hidden": true` (ẩn khi xuất – trình chỉnh dùng nút *Ẩn*). Đầu file bố cục: `title`, `mo_ta` (hiện trong thư viện), `shapes` (các hình hợp với bố cục), `shape_default`, `key_items` (món chính – mẫu thiếu thì thẻ báo "Mẫu chưa có…").

### Layout – `texts`

| Trường | Ý nghĩa |
|---|---|
| `id` | khoá để thay nội dung từ file dữ liệu khách |
| `style` | tên kiểu chữ trong `kit.json → text_styles` |
| `cx`, `cy` | tâm ngang · tâm **chữ hoa** (không đổi khi đổi tên → chữ không nhảy) |
| `w` | **vùng an toàn theo mực thật** – chữ dài hơn sẽ tự thu nhỏ, kể cả nét uốn của font viết tay |
| `size` | cỡ chữ (px của khung) |
| `align` | `center` / `left` / `right` (giữ mép neo) |
| `group` | các ô cùng nhóm dùng chung một cỡ (vd. tên cô dâu & chú rể) |
| `dy` | nhích dọc thủ công |

Văn bản nhiều dòng: dùng `\n`. Chữ lồng: kiểu có `separator` và nội dung `"G|N"`.

### Kit – dọn rác khi tách nền

Mọi asset hoa văn (kể cả ảnh AI đã có nền trong suốt) đều được dọn: **hạt lấm tấm rời rạc** (vân nền, nhiễu JPEG, pixel lạc) luôn bị bỏ; **mép** lấy sắc màu theo lõi nét liền kề (hết viền ám màu nền). Tuỳ chọn `drop_baked_shadow` trong `kit.json` xử lý **bóng tối AI vẽ sẵn**:

| Giá trị | Tác dụng |
|---|---|
| `true` (mặc định) | bỏ pixel tối mà chưa đặc (quầng bóng quanh nét) |
| `{"max_lum": 40, "max_alpha": 1.0}` | bỏ cả pixel tối **đặc** – dùng khi hoa văn của kit không có màu đen (vàng/kem trên nền tối) |
| `{"max_lum": 40, "max_alpha": 1.0, "edge_lum": 65}` | thêm: bỏ quầng xám bán trong suốt – cẩn thận, có thể ăn mất lá/chi tiết màu tối nhạt |
| `false` | giữ nguyên (kit có hoa văn màu tối/đen) |

Tuỳ chọn này dùng chung cho `extract` và `ingest`, nên đổi xong hãy chạy lại cả hai.

### File dữ liệu khách

```json
{ "texts": { "ten_1": "Phúc An", "ten_2": "Ngọc Mai", "ngay": "26 . 12 . 2026" } }
```

Một file dùng chung cho **cả bộ thiệp** – ô nào layout không có thì bỏ qua.

---

## Giai đoạn 2: tự động qua API (khi số lượng lớn)

Bước ② (viết bộ prompt) và ⑤ (vẽ từng món) sẽ được tự động; các bước khác giữ nguyên.

```bash
python -m cardkit generate vang_mau_don
```

Cần biến môi trường `OPENAI_API_KEY`. Ảnh ghi thẳng vào `raw/` (hoa văn xin **nền trong suốt thật**), các bước sau giữ nguyên.
**Chưa được kiểm thử thực tế** (lúc xây dựng không có API key) – chạy thử 1 món trước: `python -m cardkit generate vang_mau_don goc`.

## Phóng to asset nhỏ (tuỳ chọn)

Tải `realesrgan-ncnn-vulkan` (bản Windows) giải nén vào `tools/realesrgan-ncnn-vulkan/`, rồi:

```bash
python -m cardkit ingest vang_mau_don --force --upscale-to 1200
```

## Xử lý sự cố

| Hiện tượng | Cách xử lý |
|---|---|
| `Không mở được Chromium` | `python -m playwright install chromium` |
| Ảnh xuất có hạt lấm tấm / mảng đen / viền ám màu | chạy lại `ingest --force` (bản mới tự dọn); với thiệp cũ chạy lại cả `extract --spec`. Còn mảng đen → xem `drop_baked_shadow` |
| Asset báo "ô caro giả" | ChatGPT vẽ caro thay vì trong suốt → yêu cầu vẽ lại (nền trong suốt thật, hoặc nền màu đặc – prompt đã ghi sẵn) |
| "chạm mép ảnh" | AI vẽ sát mép, dễ bị cụt → tạo lại, nhấn mạnh "generous empty margins" |
| "bị phóng to … mềm nét" | asset nhỏ so với kích thước hiển thị → tạo lại lớn hơn hoặc dùng Real-ESRGAN |
| "font … thiếu ký tự" | đổi sang font có đủ bộ tiếng Việt (các font trong `fonts/` đều đủ) |
| Nhóm chữ tự thu nhỏ nhiều | nội dung khách quá dài → nới `w` hoặc rút gọn |
| Soi lỗi chữ | `render … --debug` giữ trang HTML dựng chữ trong `_build/` |

## Gửi tool cho khách (Mac + Windows)

**Cách 1 – repo git (khuyên dùng, khách tự cập nhật):** đẩy repo này lên GitHub/GitLab (repo riêng tư thì mời khách vào), gửi khách link + mục *Cài đặt và mở tool* ở đầu README. `.gitignore` chỉ cho đi mã nguồn, font + bố cục có sẵn và script khởi động (`MoTool-Mac.command`, `MoTool-Windows.bat` → `release/app/run.sh|run.ps1`); `.gitattributes` giữ đúng xuống dòng cho script Mac/Windows dù khách cấu hình git thế nào. Đẩy bản mới lên là lần mở sau khách tự có. Thêm bố cục / font có sẵn mới thì nhớ thêm vào danh sách cho phép trong `.gitignore` (test `test_gitignore_ships_builtins_only` sẽ nhắc).

**Cách 2 – gói zip:**

```bash
python tools/build_release.py
```

→ `dist/ThiepTool-<phiên bản>.zip` (~1 MB). Khách giải nén, bấm đúp **Mở Tool (Mac)** hoặc **Mở Tool (Windows)**; file **Hướng dẫn.html** trong gói chỉ từng bước (kể cả bước cho phép mở lần đầu trên macOS).

- **Lần đầu** (cần mạng, 3–5 phút): script tự tải bộ chạy [uv](https://docs.astral.sh/uv/) → Python 3.12 → thư viện (`release/app/requirements-app.txt`) vào thư mục riêng của tool (Mac: `~/Library/Application Support/ThiepTool`, Windows: `%LOCALAPPDATA%\ThiepTool`) – không đụng Python hay cài đặt hệ thống. Từ lần sau mở trong vài giây; đổi thư viện ở bản mới thì tự cài lại.
- **Dựng chữ** dùng Chrome / Edge có sẵn trên máy; máy không có thì tự tải bản Chromium gọn (một lần).
- **Dữ liệu của khách** ở `Documents/ThiepTool` (mẫu, font tự thêm, thiệp xuất trong `output/`) – gửi bản mới chỉ cần thay thư mục tool.
- Gói **không** chứa mẫu, ảnh, thiệp đã xuất của máy đóng gói; chỉ có font và bố cục có sẵn.
- macOS chặn lần đầu vì tool chưa ký số của Apple (khách bấm "Vẫn mở" một lần, xem Hướng dẫn). Muốn hết hẳn bước này cần tài khoản Apple Developer để ký và công chứng (notarize) bản Mac.

Các file khởi động nằm trong `release/` (`Mở Tool (Mac).command` → `app/run.sh`, `Mở Tool (Windows).bat` → `app/run.ps1`, khởi động Python ở `cardkit/launch.py`).

## Kiểm thử

```bash
python -m pytest tests -q
```

## Cấu trúc mã

```text
cardkit/
  studio.py      bàn làm việc (server cục bộ 127.0.0.1) + studio.html (trang chính + 2 việc theo bước)
  plan.py        gộp món thành tờ + kịch bản tin nhắn cho 1 chat ChatGPT
  sheets.py      cắt tờ thành từng món (thứ tự đọc, ghép mảnh rời, báo thiếu/thừa/chạm mép)
  launch.py      khởi động bản giao khách (dữ liệu ở Documents/ThiepTool, kiểm tra trình duyệt dựng chữ)
  fontlib.py     thư viện font: font có sẵn + font tự thêm (kiểm dấu tiếng Việt, quyền nhúng, giấy phép, nhóm chữ)
  design.py      bản thiết kế linh động: prompt cho AI, đọc & tự sửa JSON, kiểm lỗi bố cục, mẫu + phương án
  sizes.py       khổ thiệp (cm → px ở 300 DPI, điện thoại 9:16, banner web, tuỳ chỉnh; dọc/ngang/vuông)
  shapes.py      hình dáng thiệp (có sẵn + đường cắt SVG tự do) + viền song song mép hình (distance transform)
  catalog.py     danh mục món, gói chọn nhanh, chuỗi món thay thế
  kitgen.py      tạo mẫu từ ý tưởng; tự đo màu nền/màu chữ từ ảnh; (cách cũ) nạp JSON từ prompt mẹ
  keying.py      tách nền: phông màu bão hoà (hiệu màu + khử ánh phông) · nền trơn/vân (I = α·F + (1−α)·B) · dọn rác
  extract.py     rút asset + dựng lại nền + sinh bố cục nháp từ thiệp phẳng có sẵn
  ingest.py      raw/ → assets/ + báo cáo + ảnh QC
  prompts.py     prompt mẹ, prompt từng món (khung kỹ thuật theo vai trò), tự chọn màu phông tách nền
  generate.py    OpenAI Images API (giai đoạn 2)
  icard/         đăng lên Icard: convert (manifest → templateData, giả lập renderer Icard, thumbnail) ·
                 fonts (bản tĩnh, đóng băng lining-nums) · client (API admin Icard) · publish (điều phối, icard.json)
  layout.py      neo, kích thước, nhân bản đối xứng (hàm thuần)
  raster.py      layer nền + hoa văn (Pillow, đặt ảnh 1:1)
  textlayer.py   layer chữ (Chromium): vùng an toàn theo mực, nhóm đồng cỡ
  export.py      điều phối render, manifest, sheet, preview
tools/make_layouts.py   sinh thư viện bố cục có sẵn trong layouts/
tools/build_release.py  đóng gói bản giao khách dist/ThiepTool-<phiên bản>.zip
release/                nút mở cho Mac/Windows, Hướng dẫn.html, script khởi động, thư viện cần cài
```
