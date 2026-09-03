# **Triển khai thực hiện chuyển đổi pdf sang text**

Tôi đang xây dựng một pipeline dịch sách từ PDF tiếng Anh sang tiếng Việt. Hãy triển khai bước đầu tiên: tạo chương trình Python `book_pdf2text.py` để chuyển toàn bộ nội dung một cuốn sách PDF thành file text.

## Yêu cầu

Chương trình nhận đường dẫn file PDF từ command line và hỗ trợ tham số `-c` / `--columns` để xác định số cột văn bản trên mỗi trang. Ví dụ:

```bash
python book_pdf2text.py book.pdf -c 1
python book_pdf2text.py book.pdf -c 2
```

Chương trình phải đọc PDF theo từng trang và từng block/cột theo đúng thứ tự đọc tự nhiên: từ trên xuống dưới và, nếu có nhiều cột, từ trái sang phải. Với PDF dạng scan, sử dụng OCR để nhận dạng nội dung tiếng Anh. Nếu PDF đã có text layer thì ưu tiên trích xuất trực tiếp khi phù hợp, tránh OCR không cần thiết.

Kết quả của tất cả các trang được nối lại và lưu vào một file `.txt` riêng, mặc định cùng tên với PDF, ví dụ `book.pdf` → `book.txt`. File text chỉ cần giữ nội dung sách và xuống dòng hợp lý; không cần tự động xóa số trang, header, footer, chú thích hoặc các nội dung thừa khác vì tôi sẽ chỉnh sửa thủ công sau.

Sau khi chỉnh sửa, tôi sẽ tự thêm dòng:

```text
==========
```

để phân chia nội dung thành các part. Bước dịch thuật sẽ được xây dựng sau và sẽ sử dụng prompt trong `instructions/en2vi.md`. Hiện tại **chỉ triển khai hoàn chỉnh chức năng PDF → text**, chưa cần viết phần dịch.

## Yêu cầu triển khai

Viết code rõ ràng, dễ bảo trì, có xử lý lỗi cơ bản và thông báo tiến trình theo từng trang. Tự chọn các thư viện Python phù hợp và nêu lệnh cài đặt dependency nếu cần. Không over-engineer và không thêm chức năng ngoài phạm vi trên.

Hãy tạo hoàn chỉnh file `book_pdf2text.py`.
