# Markdown to DOCX Conversion with Word Template

Hãy xây dựng file Python `./main/md2docx.py` dùng để chuyển các file Markdown đã dịch sang DOCX dựa trên template có sẵn tại `./sample/sample.docx`.

Trước khi viết code, bắt buộc đọc và tuân thủ các quy định trong `.claude/CLAUDE.md`. Hãy trực tiếp tạo file Python hoàn chỉnh và có thể chạy được, không chỉ mô tả pseudocode.

## 1. Mục tiêu

Input là các file `.md` đã được tạo từ bước dịch thuật trước đó. Chương trình cần đọc nội dung Markdown và đưa nội dung vào file DOCX dựa trên template `./sample/sample.docx`.

Không tạo một file Word hoàn toàn mới về mặt style. Phải **copy file `sample.docx` sang thư mục output và đổi tên theo file đích**, sau đó sử dụng bản copy này làm template làm việc. Cách này đảm bảo file mẫu gốc không bị thay đổi hoặc bị khóa sử dụng, đồng thời mỗi file output có một template riêng để xử lý độc lập.

Các thành phần Markdown phải ánh xạ sang các style có sẵn trong template như sau:

* `# ...` → style `Heading 1`
* `## ...` → style `KC H2`
* `### ...` → style `KC H3`
* `#### ...` → style `KC H4`
* paragraph thông thường → style `KC NORMAL`
* code block → style `Command`
* definition block dạng blockquote → style `KC DEF`

Ví dụ Markdown:

`# Title`

`## 1. Giới thiệu`

`Đây là nội dung...`

`### 1.1. Phạm vi nghiên cứu`

`Nội dung...`

`#### 1.1.1. Dữ liệu đầu vào`

thì trong DOCX phải tương ứng:

* `Title` → `Heading 1`
* `1. Giới thiệu` → `KC H2`
* `Đây là nội dung...` → `KC NORMAL`
* `1.1. Phạm vi nghiên cứu` → `KC H3`
* `Nội dung...` → `KC NORMAL`
* `1.1.1. Dữ liệu đầu vào` → `KC H4`

Ký hiệu Markdown như `#`, `##`, `###`, `####` không được xuất hiện trong nội dung DOCX.

## 2. Input và output

Chương trình nhận input bằng `-i` hoặc `--input`.

Input có thể là một file `.md` hoặc một thư mục. Nếu input là thư mục thì xử lý toàn bộ file `.md` trong thư mục theo thứ tự filename và không xử lý các file có extension khác.

Hỗ trợ `-o` hoặc `--output` để chỉ định output directory.

Nếu không có `-o`, output mặc định được xác định bằng cách lùi lên một cấp so với thư mục chứa file nguồn rồi tạo thư mục `docx`.

Ví dụ input `../data/LLM/Hands_on_LLM/tran/file_vi.md` thì output là `../data/LLM/Hands_on_LLM/docx/file.docx`.

Cấu trúc tương ứng:

`Hands_on_LLM/tran/file_vi.md` → `Hands_on_LLM/docx/file.docx`

Khi tạo tên output, bỏ extension `.md`. Nếu filename kết thúc bằng `_vi` thì bỏ luôn suffix `_vi`.

Ví dụ:

* `file_vi.md` → `file.docx`
* `chapter_01_vi.md` → `chapter_01.docx`
* `appendix.md` → `appendix.docx`

Không sinh tên kiểu `file_vi.docx` nếu input có suffix `_vi`.

## 3. Overwrite

Hỗ trợ option `--overwrite`.

Mặc định không ghi đè file đã tồn tại. Nếu output đã tồn tại thì skip và hiển thị:

`[SKIP] Output already exists: <path>`

Nếu có `--overwrite`, cho phép tạo lại output từ đầu.

Không append nội dung vào file DOCX cũ.

## 4. Xử lý Markdown

Cần parse Markdown đủ để bảo toàn cấu trúc tài liệu, không đơn giản chỉ ghi từng dòng thành paragraph.

Tối thiểu phải xử lý đúng:

* heading cấp 1 đến cấp 4;
* paragraph thông thường;
* dòng trống giữa các paragraph;
* unordered list;
* ordered list;
* bold;
* italic;
* inline code;
* fenced code block;
* definition/blockquotes.

Với paragraph và nội dung nằm trong list, ưu tiên giữ định dạng inline như `**bold**`, `*italic*` và `` `inline code` `` thay vì đưa nguyên ký hiệu Markdown vào DOCX.

### Code block

Các khối code được bao bởi fenced code block như ` ``` `, ` ```python `, ` ```bash `, ` ```text ` hoặc language identifier khác phải được chuyển thành paragraph sử dụng style `Command`.

Nội dung code phải được giữ nguyên, bao gồm indentation, khoảng trắng, ký tự đặc biệt và xuống dòng. Không đưa các dấu ` ``` ` vào DOCX và không dịch hoặc tự sửa code.

Nếu một code block gồm nhiều dòng, có thể tạo nhiều paragraph `Command` hoặc sử dụng cách biểu diễn phù hợp với template, miễn nội dung và thứ tự các dòng code được giữ chính xác.

Inline code dạng `` `code` `` nằm trong paragraph thông thường không được biến toàn bộ paragraph thành style `Command`; chỉ code block riêng biệt mới sử dụng style `Command`.

### Definition block

Các khối định nghĩa được biểu diễn bằng Markdown blockquote phải sử dụng style `KC DEF`.

Ví dụ:

`> Definition: Transformer là một kiến trúc mạng neural...`

hoặc:

`> **Definition**`

`> Transformer là một kiến trúc...`

phải được đưa vào DOCX bằng style `KC DEF` và loại bỏ ký hiệu `>` của Markdown.

Nếu definition block gồm nhiều dòng liên tiếp bắt đầu bằng `>`, phải xem chúng là cùng một khối định nghĩa và giữ đúng thứ tự nội dung.

Không áp dụng `KC DEF` một cách máy móc cho mọi trường hợp nếu blockquote rõ ràng chỉ là một trích dẫn thông thường. Ưu tiên nhận diện các block có dấu hiệu định nghĩa như `Definition`, `Định nghĩa` hoặc cấu trúc tương đương. Với blockquote thông thường không phải định nghĩa, giữ nội dung mà không làm mất dữ liệu.

Không để các ký hiệu Markdown như `#`, `**`, `*`, backtick, fenced code marker hoặc `>` xuất hiện trong DOCX nếu chúng chỉ có vai trò formatting.

Không tự thay đổi, tóm tắt hoặc dịch lại nội dung. Nhiệm vụ của bước này chỉ là chuyển nội dung Markdown sang DOCX.

Nếu gặp Markdown feature chưa hỗ trợ, ưu tiên giữ nguyên nội dung văn bản thay vì làm mất dữ liệu.

## 5. Template và styles

Template mặc định là `./sample/sample.docx`.

Trước khi xử lý, kiểm tra template tồn tại và kiểm tra các style bắt buộc:

* `Heading 1`
* `KC H2`
* `KC H3`
* `KC H4`
* `KC NORMAL`
* `Command`
* `KC DEF`

Nếu thiếu style cần thiết, báo lỗi rõ tên style bị thiếu thay vì tự tạo một style mới với định dạng không xác định.

Nội dung mới phải được thêm vào document dựa trên template nhưng không được làm thay đổi định nghĩa style gốc trong `sample.docx`.

Sử dụng thư viện Python phù hợp, ưu tiên `python-docx` nếu repository chưa có giải pháp khác.

## 6. Luồng xử lý

Luồng chính:

`parse arguments -> resolve input files -> copy sample.docx -> parse Markdown -> map Markdown elements to Word styles -> save DOCX`

Với mỗi file input:

`file.md -> copy template -> insert converted content -> save output.docx`

Không để nội dung của file trước xuất hiện trong file tiếp theo khi xử lý cả thư mục. Mỗi input `.md` phải tạo một DOCX độc lập dựa trên template sạch.

Tách các responsibility thành function phù hợp thay vì viết toàn bộ logic trong `main()`.

## 7. CLI và kiểm thử

CLI tối thiểu hỗ trợ:

`-i / --input`

`-o / --output`

`--overwrite`

`-h / --help`

Sử dụng `pathlib` để xử lý path và UTF-8 khi đọc Markdown.

Cần xử lý rõ các trường hợp:

* input không tồn tại;
* input không phải `.md`;
* directory không có file `.md`;
* `sample.docx` không tồn tại;
* thiếu style trong template;
* output đã tồn tại;
* lỗi khi đọc hoặc ghi DOCX.

Hiển thị progress ngắn gọn, ví dụ:

`[1/10] Processing chapter_01_vi.md`

`[DONE] .../docx/chapter_01.docx`

Sau khi hoàn thành, kiểm tra ít nhất:

1. syntax của `main/md2docx.py`;
2. `--help`;
3. input là một file;
4. input là một directory;
5. mapping `#`, `##`, `###`, `####` sang đúng style;
6. paragraph dùng `KC NORMAL`;
7. fenced code block sử dụng style `Command` và không còn dấu ` ``` `;
8. inline code không làm toàn bộ paragraph chuyển thành `Command`;
9. definition block sử dụng style `KC DEF` và không còn ký hiệu `>`;
10. `file_vi.md` tạo thành `file.docx`;
11. `--overwrite`;
12. file output mở được bằng Word và sử dụng đúng các style từ `sample/sample.docx`.

Chỉ sửa hoặc tạo các file thực sự cần thiết. Không thay đổi `sample/sample.docx`, `.claude/CLAUDE.md` hoặc các file Markdown nguồn.

Sau khi hoàn thành, báo cáo ngắn gọn file đã tạo, cách Markdown được ánh xạ sang style Word, cách xử lý code/definition block, cách xác định output path và một vài ví dụ command để chạy chương trình.