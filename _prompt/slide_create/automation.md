# Task: Xây dựng `book_task.py` điều phối pipeline chuẩn bị bài giảng

Hãy đọc cấu trúc project hiện tại và xây dựng chương trình:

`book_task.py`

Mục tiêu là điều phối toàn bộ quy trình từ sách PDF/EPUB đến PowerPoint, đồng thời tự xử lý trường hợp Codex/Claude hết quota.

## Câu lệnh

```bash
python book_task.py -i <book_path> -m codex -t pdf
```

Ví dụ:

```bash
python book_task.py \
    -i ../data/book.pdf \
    -m codex \
    -t pdf \
    --non-check \
    --overwrite \
    -o ../data/output
```

Các tham số:

```text
-i, --input       Đường dẫn sách đầu vào
-m, --model       codex hoặc claude
-t, --type        pdf hoặc epub
-o, --output      Output tùy chọn
--non-check       Không chờ người dùng kiểm tra/chỉnh sửa DOCX
--overwrite       Cho phép ghi đè khi chạy lần đầu
```

Trước khi viết code, hãy đọc CLI và cấu trúc thực tế của:

```text
pipeline_pdf.py
pipeline_epub.py
slide_create/pipeline.py
```

Không tự giả định tham số nếu có thể đọc trực tiếp từ code hiện tại.

---

# 1. Luồng tổng quát

Dựa vào `-t`:

```text
pdf
 ↓
pipeline_pdf.py

epub
 ↓
pipeline_epub.py
```

Sau bước này sẽ có thư mục output chứa DOCX cuối cùng của quá trình xử lý sách.

Quy trình tổng thể:

```text
BOOK
 │
 ▼
pipeline_pdf.py / pipeline_epub.py
 │
 ▼
DOCX đã xử lý
 │
 ├── Chờ người dùng kiểm tra/chỉnh sửa
 │
 └── hoặc --non-check
          │
          ▼
        done/
          │
          ▼
slide_create/pipeline.py
          │
          ▼
       PowerPoint
```

`book_task.py` chỉ làm nhiệm vụ điều phối. Không viết lại logic của các pipeline hiện có.

---

# 2. Trường hợp KHÔNG có `--non-check`

Đây là chế độ mặc định.

Ở lần chạy đầu:

```text
book_task.py
    ↓
pipeline_<type>.py
    ↓
tạo DOCX
    ↓
DỪNG
```

Không tự chạy `slide_create/pipeline.py`.

Người dùng sẽ tự kiểm tra và chỉnh sửa DOCX.

Sau khi chỉnh sửa xong, người dùng tự tạo hoặc chuyển kết quả đã duyệt vào thư mục:

```text
done/
```

Thư mục `done` nằm cùng cấp với thư mục output cuối của pipeline xử lý sách.

Sau đó người dùng chạy lại chính câu lệnh:

```bash
python book_task.py -i <book_path> -m codex -t pdf
```

Khi chạy lại, chương trình phải kiểm tra trước:

```text
done/ tồn tại?
```

Nếu `done/` tồn tại:

```text
done/
 ↓
slide_create/pipeline.py
 ↓
tạo slide
```

Không chạy lại `pipeline_<type>.py` nếu bước xử lý sách đã hoàn thành.

Nếu `done/` chưa tồn tại:

```text
Thông báo đang chờ người dùng kiểm tra/chỉnh sửa tài liệu
↓
DỪNG
```

Không chạy pipeline slide.

---

# 3. Trường hợp có `--non-check`

Nếu sử dụng:

```bash
--non-check
```

thì không chờ người dùng kiểm tra DOCX.

Sau khi:

```text
pipeline_<type>.py
```

hoàn thành, tự động lấy kết quả DOCX cuối cùng và chuẩn bị thư mục:

```text
done/
```

theo đúng cấu trúc mà `slide_create/pipeline.py` yêu cầu.

Sau đó tiếp tục ngay:

```text
pipeline_<type>.py
        ↓
      done/
        ↓
slide_create/pipeline.py
        ↓
      PPTX
```

Không dừng giữa hai bước.

---

# 4. Phát hiện trạng thái để tránh chạy lại

`book_task.py` phải dựa vào file/thư mục đầu ra hiện có để xác định bước nào đã hoàn thành.

Ví dụ:

```text
Nếu chưa có output của pipeline_<type>
    → chạy pipeline_<type>

Nếu đã có output nhưng chưa có done/
    → không chạy lại pipeline_<type>
    → thông báo chờ người dùng kiểm tra
    → dừng

Nếu đã có done/
    → chạy slide_create/pipeline.py

Nếu slide output đã hoàn thành
    → báo hoàn thành
```

Không cần xây dựng checkpoint phức tạp nếu trạng thái có thể xác định từ filesystem.

---

# 5. Xử lý `--overwrite`

`--overwrite` chỉ áp dụng cho lần chạy chủ động ban đầu của người dùng.

Nếu chương trình bị hết quota và scheduler chạy lại `book_task.py`, câu lệnh resume phải bỏ:

```text
--overwrite
```

Ví dụ ban đầu:

```bash
python book_task.py \
    -i book.pdf \
    -m codex \
    -t pdf \
    --non-check \
    --overwrite \
    -o output
```

Khi tự động chạy lại:

```bash
python book_task.py \
    -i book.pdf \
    -m codex \
    -t pdf \
    --non-check \
    -o output
```

Mục tiêu là tận dụng những file đã hoàn thành và tiếp tục từ trạng thái hiện tại.

---

# 6. Xử lý hết quota

Khi gọi subprocess, phải thu thập:

```text
return code
stdout
stderr
```

Nếu phát hiện lỗi liên quan đến quota hoặc usage limit, ví dụ:

```text
usage limit
quota exceeded
rate limit
limit reached
try again after
retry after
resets at
```

thì xem đây là trạng thái tạm thời, không phải lỗi pipeline.

Luồng:

```text
Quota exceeded
      ↓
xác định thời điểm chạy lại
      ↓
tạo Windows Scheduled Task
      ↓
thoát chương trình
      ↓
đến thời điểm retry
      ↓
chạy lại book_task.py
      ↓
tiếp tục dựa trên trạng thái filesystem
```

Ưu tiên lấy thời gian retry/reset trực tiếp từ thông báo lỗi.

Nếu không xác định được thời gian reset, mặc định:

```text
retry sau 60 phút
```

Đặt giá trị này thành hằng số để dễ thay đổi.

Sử dụng Windows Task Scheduler thông qua:

```text
schtasks
```

Task phải có tên ổn định theo cuốn sách để tránh tạo nhiều lịch trùng nhau.

---

# 7. Lỗi không phải quota

Nếu subprocess trả lỗi nhưng không thuộc nhóm quota:

```text
in command đã chạy
in return code
in stdout
in stderr
exit != 0
```

Sau đó dừng.

Không tạo lịch retry.

Không che lỗi.

---

# 8. Khi chạy thành công

Khi toàn bộ quá trình cần thiết đã hoàn thành:

```text
pipeline_<type>
        +
slide_create/pipeline.py
```

thì:

```text
xóa Scheduled Task của job này nếu tồn tại
↓
in đường dẫn output cuối
↓
exit code = 0
```

Nếu chương trình chỉ hoàn thành bước xử lý sách và đang chờ người dùng kiểm tra DOCX thì không coi đó là lỗi.

---

# 9. Cách tổ chức code

Giữ code đơn giản và dễ đọc.

Có thể tổ chức:

```python
parseArgs()
getPaths()
buildCommand()
runProcess()
isQuotaError()
getRetryTime()
getTaskName()
scheduleRetry()
removeScheduledTask()
hasBookOutput()
hasDone()
prepareDone()
runBookPipeline()
runSlidePipeline()
main()
```

Không cần bắt buộc đúng toàn bộ tên hàm trên nếu cấu trúc khác hợp lý hơn.

Ưu tiên dùng:

```python
sys.executable
```

để chạy đúng Python interpreter hiện tại.

Khi scheduler gọi lại `book_task.py`, sử dụng đường dẫn tuyệt đối tới script và bảo toàn các tham số ban đầu, ngoại trừ việc loại bỏ:

```text
--overwrite
```

---

# 10. Logic mong muốn

```text
START
  │
  ▼
Parse arguments
  │
  ▼
Kiểm tra trạng thái hiện tại
  │
  ├── đã có done/
  │       │
  │       ▼
  │   chạy slide pipeline
  │
  ├── đã có output sách nhưng chưa có done/
  │       │
  │       ├── có --non-check
  │       │       ↓
  │       │   tạo/copy done/
  │       │       ↓
  │       │   chạy slide pipeline
  │       │
  │       └── không có --non-check
  │               ↓
  │           thông báo chờ kiểm tra
  │               ↓
  │              STOP
  │
  └── chưa có output sách
          │
          ▼
      chạy pipeline_<type>
          │
          ├── có --non-check
          │       ↓
          │   chuẩn bị done/
          │       ↓
          │   chạy slide pipeline
          │
          └── không có --non-check
                  ↓
              thông báo hoàn thành bước 1
                  ↓
                 STOP
```

Trong bất kỳ subprocess nào:

```text
Success
   → tiếp tục

Quota Error
   → schedule retry
   → STOP

Other Error
   → report error
   → STOP
```

Hãy triển khai trực tiếp vào project hiện tại và giữ thay đổi tối thiểu đối với các pipeline đang có.

Điểm quan trọng của phiên bản này là `done/` trở thành **mốc xác nhận của người dùng**:

không có done/ = chưa được duyệt
có done/       = được phép tạo slide

Nhờ vậy lần chạy thứ hai của `book_task.py` không cần thêm cờ kiểu `--continue` hay `--resume`.