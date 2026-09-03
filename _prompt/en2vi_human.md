# Task: Build `main/en2vi.py` for technical English-to-Vietnamese book translation

Hãy xây dựng file Python `main/en2vi.py` dùng để dịch các file sách kỹ thuật từ tiếng Anh sang tiếng Việt. Trước khi viết code, bắt buộc đọc và tuân thủ các quy định về cách viết code trong `.claude/CLAUDE.md`. Không chỉ mô tả giải pháp mà phải trực tiếp tạo file Python hoàn chỉnh và có thể chạy được.

## 1. Yêu cầu dịch thuật

Các tài liệu chủ yếu thuộc lĩnh vực công nghệ, AI, Machine Learning, Cybersecurity, Information Security và bảo mật. Bản dịch phải khoa học, mạch lạc, sát nghĩa với từng câu tiếng Anh và dịch đầy đủ nội dung vì kết quả sẽ được sử dụng làm tài liệu song ngữ. 
Vì bản dịch được sử dụng về sau như tài liệu **song ngữ**, vì vậy yêu cầu quan trọng nhất là:
1. dịch đầy đủ;
2. sát nghĩa từng câu;
3. không tự ý tóm tắt;
4. không bỏ đoạn;
5. không thêm nội dung ngoài văn bản tác giả;
6. vẫn phải tự nhiên, khoa học và mạch lạc trong tiếng Việt;
7. bảo toàn cấu trúc logic của sách.

Với thuật ngữ chuyên ngành, lần đầu có thể dịch theo dạng `bộ chuyển đổi (transformer)`, sau đó chỉ sử dụng `transformer`. Với từ viết tắt, lần đầu sử dụng dạng `mô hình ngôn ngữ lớn (Large Language Model - LLM)`, sau đó chỉ sử dụng `LLM`. Những thuật ngữ đã phổ biến trong lĩnh vực kỹ thuật như `transformer`, `token`, `embedding`, `prompt`, `fine-tuning`, `payload`, `sandbox`, `exploit`... có thể giữ nguyên khi việc dịch sang tiếng Việt làm mất tính chính xác hoặc khó hiểu.

Với abbreviation/acronym xuất hiện lần đầu, sử dụng dạng: mô hình ngôn ngữ lớn (Large Language Model - LLM), các lần sau chỉ cần sử dụng LLM

Phải giữ nguyên source code, command, path, filename, API, function/class name, environment variable, URL, công thức và các nội dung kỹ thuật không nên dịch.

Prompt dịch chính được lưu tại `instruction/en2vi_prompt.md`.

## 2. Input và output

Chương trình nhận input bằng `-i` hoặc `--input`. Input có thể là một file `.txt` hoặc một thư mục. Nếu là thư mục thì dịch toàn bộ file `.txt` trong đó theo thứ tự filename, đồng thời, không xử lý các file không phải `.txt`

Hỗ trợ `-o` hoặc `--output` để chỉ định thư mục đầu ra. Nếu không có `-o`, output mặc định được xác định bằng cách lùi lên một cấp so với thư mục chứa file nguồn rồi tạo thư mục `tran`.

Ví dụ input:

```text
../data/LLM/Hands_on_LLM/text/file_text.txt
```

thì output mặc định phải là:

```text
../data/LLM/Hands_on_LLM/tran/file_vi.md
```

Tức là:

```text
Hands_on_LLM/
├── text/
│   └── file_text.txt
└── tran/
    └── file_vi.md
```

Tên file output sử dụng dạng `<tên_file>_vi.md`.

Hỗ trợ `--overwrite`. Mặc định không ghi đè file đã tồn tại; nếu file output đã tồn tại thì skip (`[SKIP] Output already exists: ...`). Khi có `--overwrite`, cho phép tạo lại file từ đầu, xóa/truncate nội dung cũ trước khi dịch, và không append bản dịch cũ.

## 3. Lựa chọn model

Sử dụng `-m` hoặc `--model` với 5 lựa chọn: `gemini`, `codex`, `claude`, `non-codex`, `non-claude`.

`gemini`: sử dụng Gemini API. API token, API endpoint và MODEL được load từ `./config/env.py`. Không hard-code thông tin này trong source code.
from config.env import API_GEMINI_KEY, MODEL_35, MODEL, INSTRUCTION_TRANSLATE_RESEARCH,MODEL_31_PRE

`codex`: sử dụng Codex CLI theo interactive session. Với mỗi file cần tạo hoặc duy trì một session để luồng tương tác có dạng `prompt -> session 1 -> session 2 -> ... -> session n`.

`claude`: tương tự `codex`, sử dụng Claude CLI và duy trì interactive session cho từng file.
Với 02 tùy chọn `codex` và `claude`, ta cần tạo một terminal (sub process, sau đó tương tác để lấy stdout, việc này tạo sẽ lưu giữ các phiên với nhau)

`non-codex`: sử dụng Codex ở non-interactive mode, tương đương `codex exec`. Mỗi lần gọi độc lập phải gửi `prompt + session hiện tại`.

`non-claude`: sử dụng Claude ở non-interactive mode, tương đương `claude -p`. Mỗi lần gọi độc lập phải gửi `prompt + session hiện tại`.
Với 02 tùy chọn `non-codex` và `non-claude`, ta cần lấy stdout từng lần và viết tiếp vào file cho từng session

Đối với `codex` và `claude`, prompt trong `instruction/en2vi_prompt.md` chỉ gửi khi khởi tạo session, sau đó lần lượt gửi từng translation session. Đối với `non-codex` và `non-claude`, mỗi subprocess độc lập phải gửi lại `instruction/en2vi_prompt.md` cùng nội dung session cần dịch.

Trước khi implement Codex/Claude backend, kiểm tra CLI thực tế bằng các lệnh help tương ứng để sử dụng đúng option và cơ chế session; không tự giả định hoặc tự tạo flag không tồn tại. Khi truyền nội dung lớn, ưu tiên stdin hoặc cơ chế phù hợp thay vì đưa toàn bộ 50.000 ký tự trực tiếp vào command-line argument nếu có nguy cơ vượt giới hạn của hệ điều hành.

## 4. Phân chia block và session

Mỗi file `.txt` đã được chia thành các block bằng delimiter `===========`. Chương trình đọc file, tách thành các block, bỏ block rỗng và giữ nguyên thứ tự.

Sau đó gom các block liên tiếp thành các translation session. Mỗi session có giới hạn tối đa khoảng `50_000` characters. Một session có thể chứa nhiều block miễn tổng kích thước không vượt giới hạn. Phải tính cả delimiter/newline dùng khi ghép block.

Không được thay đổi thứ tự block để tối ưu kích thước session.

Nếu một block riêng lẻ đã lớn hơn `50_000` characters thì không chia nhỏ block đó; đặt riêng block đó thành một session và log warning, sau đó tiếp tục xử lý các block còn lại.

Ví dụ nếu các block lần lượt có kích thước `12K`, `15K`, `17K`, `20K` thì có thể tạo session đầu gồm ba block đầu khoảng `44K`, session sau chứa block `20K`.

Trước khi dịch cần hiển thị số lượng block và số lượng session của file để dễ kiểm tra.

## 5. Chuyển thành Markdown

Input hiện tại là `.txt`, nhưng output phải là Markdown `.md`.

Model cần nhận biết cấu trúc heading dựa trên numbering và ngữ cảnh. `Chapter 1. ...` tương ứng heading cấp 1; `1. ...` tương ứng heading cấp 2; `1.1. ...` tương ứng heading cấp 3; `1.1.1. ...` tương ứng heading cấp 4 và tiếp tục tương tự.

Cần phân biệt heading với numbered list thông thường dựa trên ngữ cảnh, không được biến mọi dòng bắt đầu bằng số thành heading.

Output của model chỉ được chứa nội dung bản dịch Markdown, không thêm các câu như `Here is the translation`, `Bản dịch như sau` hoặc các lời giải thích ngoài nội dung sách.

## 6. Ghi kết quả

Mỗi translation session sau khi nhận được output thành công phải được append ngay vào file `.md` theo đúng thứ tự. Không cần giữ toàn bộ bản dịch của file trong RAM rồi mới ghi.

Luồng xử lý cơ bản là `đọc file -> tách block -> gom session -> gửi session cho model -> nhận bản dịch -> append vào file -> xử lý session tiếp theo`.

Nếu một session lỗi thì không được ghi partial output lỗi vào file. Cần báo rõ file và session đang lỗi.

Với nhiều file, xử lý lần lượt từng file. Không chạy song song nếu việc đó làm mất context hoặc làm thay đổi thứ tự.

## 7. Tổng hợp thuật ngữ cuối file

Sau khi toàn bộ nội dung của một file đã dịch thành công, thêm một phần cuối file để tổng hợp các thuật ngữ hoặc định nghĩa khó hiểu, quan trọng hoặc mới xuất hiện trong nội dung vừa dịch. Phần này sau này sẽ được sử dụng cho `summary`.

Không cần tổng hợp mọi thuật ngữ. Chỉ chọn các khái niệm đáng chú ý và trình bày ngắn gọn, chính xác, dễ hiểu. Không được làm thay đổi nội dung bản dịch phía trên.

Có thể thiết kế việc thu thập các thuật ngữ trong quá trình dịch để tránh phải đưa toàn bộ file rất lớn trở lại model ở cuối.

## 8. Yêu cầu implementation

Tổ chức code rõ ràng và tuân thủ `.claude/CLAUDE.md`. Tách riêng các phần xử lý input/output, split block, group session và backend translation thay vì viết toàn bộ vào một hàm `main()`.

CLI tối thiểu hỗ trợ `-i/--input`, `-o/--output`, `-m/--model`, `--overwrite`.

Chương trình cần xử lý UTF-8, sử dụng `pathlib` cho path, kiểm tra input/config cần thiết, xử lý lỗi subprocess/API rõ ràng và không log API token.

Sau khi hoàn thành `./main/en2vi.py`, hãy kiểm tra syntax, chạy `--help`, đồng thời test logic chia session với các trường hợp dưới `50_000`, đúng `50_000`, vượt `50_000` và block riêng lẻ lớn hơn giới hạn.

Cuối cùng, báo cáo ngắn gọn các file đã tạo hoặc sửa, cách tổ chức chương trình, cách 5 model backend hoạt động và ví dụ command để chạy chương trình.
