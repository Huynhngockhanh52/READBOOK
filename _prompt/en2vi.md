# Task: Build `main.en2vi.py` for technical English-to-Vietnamese book translation

Xây dựng một chương trình Python hoàn chỉnh có tên: `./main/en2vi.py`

Chương trình dùng để dịch các file sách kỹ thuật từ tiếng Anh sang tiếng Việt bằng nhiều backend/model khác nhau, hỗ trợ cả API và CLI interactive/non-interactive.

## 1. Coding instructions

Trước khi viết code, **bắt buộc đọc và tuân thủ toàn bộ quy định trong**: `.claude/CLAUDE.md` để hiểu các quy tắc cấu trúc tên file, cách đặt tên hàm, tên biến

```text

```

Các yêu cầu trong `.claude/CLAUDE.md` có mức ưu tiên cao đối với:

* coding style;
* naming convention;
* cấu trúc source code;
* cách tổ chức function/class;
* logging;
* error handling;
* comment/docstring;
* path handling;
* subprocess handling;
* các quy tắc khác liên quan đến repository.

Không được bỏ qua file này.

Sau khi đọc `CLAUDE.md`, hãy khảo sát cấu trúc repository hiện tại để tái sử dụng các helper, config loader hoặc convention sẵn có nếu phù hợp, thay vì tạo implementation trùng lặp không cần thiết.

---

# 2. Objective

`main.en2vi.py` là CLI tool dùng để dịch sách kỹ thuật từ English sang Vietnamese.

Các sách chủ yếu thuộc các lĩnh vực:

* Artificial Intelligence;
* Machine Learning;
* Large Language Models;
* Cybersecurity;
* Information Security;
* Computer Science;
* Software Engineering;
* Networking;
* Cryptography;
* các chủ đề công nghệ liên quan.

Bản dịch được sử dụng về sau như tài liệu **song ngữ**, vì vậy yêu cầu quan trọng nhất là:

1. dịch đầy đủ;
2. sát nghĩa từng câu;
3. không tự ý tóm tắt;
4. không bỏ đoạn;
5. không thêm nội dung ngoài văn bản tác giả;
6. vẫn phải tự nhiên, khoa học và mạch lạc trong tiếng Việt;
7. bảo toàn cấu trúc logic của sách.

---

# 3. Translation terminology rules

Prompt dịch chính được đặt tại:

```text
instruction/en2vi_prompt.md
```

`main.en2vi.py` phải đọc nội dung file này và sử dụng nó làm instruction/prompt nền cho model.

Ngoài nội dung trong `en2vi_prompt.md`, workflow phải bảo đảm model hiểu các quy tắc sau.

## 3.1. Technical terms

Khi một thuật ngữ kỹ thuật xuất hiện lần đầu, nên dịch theo dạng:

```text
bộ chuyển đổi (transformer)
```

Sau lần đầu, chỉ cần dùng:

```text
transformer
```

Không cần lặp lại:

```text
bộ chuyển đổi (transformer)
```

ở mọi lần xuất hiện sau đó.

Ưu tiên giữ nguyên các thuật ngữ tiếng Anh đã trở thành thuật ngữ chuẩn trong lĩnh vực kỹ thuật nếu dịch ra tiếng Việt làm câu khó hiểu hoặc sai thông lệ chuyên ngành.

Ví dụ:

```text
transformer
token
embedding
prompt
fine-tuning
inference
attention
zero-day
payload
sandbox
exploit
```

Model phải xét ngữ cảnh chuyên ngành trước khi quyết định dịch hay giữ nguyên thuật ngữ.

---

## 3.2. Abbreviations

Với abbreviation/acronym xuất hiện lần đầu, sử dụng dạng:

```text
mô hình ngôn ngữ lớn (Large Language Model - LLM)
```

Các lần sau chỉ sử dụng:

```text
LLM
```

Tương tự với các thuật ngữ như:

```text
Retrieval-Augmented Generation - RAG
Natural Language Processing - NLP
Generative Adversarial Network - GAN
Intrusion Detection System - IDS
```

Không mở rộng lại abbreviation một cách không cần thiết trong cùng tài liệu.

---

# 4. Input modes

Chương trình phải hỗ trợ hai cách chỉ định input.

## 4.1. Single file

Cho phép truyền trực tiếp một file `.txt`.

Ví dụ:

```bash
python main.en2vi.py ../data/LLM/Hands_on_LLM/text/chapter_01.txt
```

Hoặc nếu thiết kế CLI phù hợp hơn:

```bash
python main.en2vi.py -i ../data/LLM/Hands_on_LLM/text/chapter_01.txt
```

Hãy ưu tiên CLI rõ ràng, nhất quán và dễ sử dụng.

---

## 4.2. Directory

Option:

```text
-i
--input
```

phải cho phép chỉ định một directory.

Nếu input là directory thì:

* tìm các file `.txt` trong directory;
* dịch toàn bộ các file hợp lệ;
* thứ tự file phải deterministic;
* nên sort theo filename/path trước khi xử lý;
* không xử lý các file không phải `.txt`.

Ví dụ:

```bash
python main.en2vi.py -i ../data/LLM/Hands_on_LLM/text/
```

---

# 5. Output path

Option:

```text
-o
--output
```

dùng để chỉ định output directory.

Ví dụ:

```bash
python main.en2vi.py \
  -i ../data/LLM/Hands_on_LLM/text/ \
  -o ../data/LLM/Hands_on_LLM/tran/
```

Nếu không cung cấp `-o`, chương trình phải tự xác định output mặc định.

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

Quy tắc:

1. lấy parent của thư mục chứa input;
2. tạo directory:

```text
tran/
```

3. đổi extension `.txt` thành `.md`;
4. đổi hậu tố filename về dạng `_vi.md`.

Ví dụ:

```text
chapter_01.txt
```

thành:

```text
chapter_01_vi.md
```

Nếu tên file đã có các suffix đặc biệt, hãy xử lý nhất quán và tránh sinh các tên kiểu:

```text
file_vi_vi.md
```

---

# 6. Overwrite option

Cần hỗ trợ:

```text
--overwrite
```

Mặc định:

```text
overwrite = False
```

Nếu output file đã tồn tại và **không có `--overwrite`**:

* không được ghi đè;
* skip file đó;
* log rõ lý do.

Ví dụ:

```text

```

Nếu có:

```bash
--overwrite
```

thì:

* cho phép tạo lại file;
* xóa/truncate nội dung cũ trước khi dịch;
* không append vào bản dịch cũ.

---

# 7. Model selection

Option:

```text
-m
--model
```

phải hỗ trợ chính xác 5 backend:

```text
gemini
codex
claude
non-codex
non-claude
```

Nên validate bằng `choices`.

Ví dụ:

```bash
python main.en2vi.py -i ... -m gemini
```

---

# 8. Gemini backend

Với:

```text
-m gemini
```

sử dụng Gemini API.

Thông tin cấu hình phải được load từ:

```text
./config/.env
```

Không hard-code API key, API endpoint hoặc model name trong source code.

Hãy kiểm tra repository/config hiện tại để xác định tên biến môi trường đã được sử dụng. Nếu chưa có convention thì thiết kế rõ ràng, ví dụ:

```env
GEMINI_API_KEY=...
GEMINI_API_URL=...
GEMINI_MODEL=...
```

hoặc tên tương đương phù hợp với repository.

Chương trình cần:

* validate config;
* báo lỗi rõ nếu thiếu biến;
* không print API key vào terminal/log;
* xử lý API error;
* xử lý timeout;
* xử lý empty response;
* có retry hợp lý cho transient error nếu phù hợp với coding guideline của project.

---

# 9. CLI model modes

Có bốn CLI backend:

```text
codex
claude
non-codex
non-claude
```

Cần phân biệt rõ **interactive mode** và **non-interactive mode**.

---

# 10. Interactive Codex

Với:

```text
-m codex
```

workflow mong muốn về mặt logic là:

```text
start Codex session
      │
      ├── send instruction/en2vi_prompt.md
      │
      ├── send session_1
      │
      ├── receive translation_1
      │
      ├── send session_2
      │
      ├── receive translation_2
      │
      ├── ...
      │
      └── send session_n
             ↓
         receive translation_n
```

Tức là:

```text
prompt
  ↓
session 1
  ↓
session 2
  ↓
...
  ↓
session n
```

Tất cả translation sessions của **một input file** phải thuộc cùng một conversation/session nếu CLI cho phép, để model giữ được context, đặc biệt là:

* terminology;
* abbreviations;
* cách dịch;
* chapter context;
* thuật ngữ đã giới thiệu trước đó.

Không tạo một conversation hoàn toàn độc lập cho mỗi chunk nếu backend interactive hỗ trợ giữ session.

Chương trình cần lấy response từ stdout hoặc cơ chế output chính thức của CLI một cách ổn định.

Không parse terminal output bằng những assumptions mong manh nếu CLI có machine-readable/output mode phù hợp.

---

# 11. Interactive Claude

Với:

```text
-m claude
```

workflow tương tự `codex`:

```text
start Claude session
      │
      ├── send instruction/en2vi_prompt.md
      ├── send session_1
      ├── receive translation_1
      ├── send session_2
      ├── receive translation_2
      └── ...
```

Một input `.txt` nên sử dụng một conversation/session xuyên suốt nếu Claude CLI hỗ trợ.

Hãy kiểm tra CLI hiện có trên môi trường/repository để sử dụng đúng command, flag và session mechanism thực tế.

Không tự bịa CLI flag.

---

# 12. Non-interactive Codex

Với:

```text
-m non-codex
```

sử dụng Codex ở chế độ non-interactive bằng dạng command tương ứng với:

```bash
codex exec "..."
```

Mỗi translation session là một subprocess/request độc lập.

Do đó request phải có dạng:

```text
instruction/en2vi_prompt.md
+
current translation session
```

Tức là:

```text
(prompt + session_1)
(prompt + session_2)
...
(prompt + session_n)
```

Không chỉ gửi prompt một lần vì các lần `codex exec` không chia sẻ context theo assumption mặc định.

Nếu cần bổ sung một lượng nhỏ context để bảo đảm consistency giữa các chunks, chỉ thực hiện khi có thiết kế rõ ràng và không làm vượt giới hạn request.

---

# 13. Non-interactive Claude

Với:

```text
-m non-claude
```

sử dụng dạng:

```bash
claude -p "..."
```

hoặc cách non-interactive chính thức tương ứng với phiên bản Claude CLI thực tế.

Mỗi session phải gửi:

```text
instruction/en2vi_prompt.md
+
current translation session
```

tương tự `non-codex`.

Không assume các subprocess độc lập có conversation memory.

---

# 14. Character limit

Giới hạn chính:

```text
50,000 characters / translation message
```

xấp xỉ:

```text
~10K tokens
```

Đây là giới hạn theo **characters**, không phải tokenizer.

Khai báo thành constant rõ ràng, ví dụ:

```python
MAX_SESSION_CHARS = 50_000
```

hoặc tên phù hợp với `.claude/CLAUDE.md`.

Không sử dụng magic number rải rác trong source code.

---

# 15. Source block structure

Các `.txt` đầu vào đã được preprocess trước.

Các block lớn được phân tách bởi separator:

```text
==========
```

tức là:

```python
"=" * 10
```

Ví dụ:

```text
Chapter 1. Introduction
...

==========
1. Large Language Models
...

==========
1.1. Language Modeling
...

==========
...
```

Chương trình phải:

1. đọc toàn bộ file;
2. split thành blocks theo delimiter;
3. loại bỏ block rỗng sinh ra do separator;
4. không làm mất nội dung trong block;
5. bảo toàn đúng thứ tự block.

Trước khi dịch, log:

```text
Input file: ...
Total blocks: N
```

---

# 16. Group blocks into translation sessions

Sau khi có danh sách blocks, gom các blocks liên tiếp thành các translation sessions.

Mục tiêu:

```text
mỗi session <= 50,000 chars
```

trong trường hợp bình thường.

Thuật toán cần hoạt động theo thứ tự:

```text
block_1
block_2
block_3
...
block_n
```

Ví dụ:

```text
block_1 = 12,000 chars
block_2 = 15,000 chars
block_3 = 17,000 chars
block_4 = 20,000 chars
```

thì có thể tạo:

```text
session_1:
block_1 + block_2 + block_3
≈ 44,000 chars

session_2:
block_4
≈ 20,000 chars
```

Không được reorder blocks để tối ưu packing.

Đây là sequential grouping, không phải bin packing.

---

# 17. Oversized block

Nếu một block riêng lẻ lớn hơn:

```text
50,000 chars
```

thì **không tự cắt block đó thành các đoạn nhỏ một cách mù quáng**.

Theo yêu cầu hiện tại:

```text
oversized block -> one standalone session
```

Ví dụ:

```text
block_7 = 62,000 chars
```

thì:

```text
session_4 = block_7
```

và log warning:

```text
[WARN] Block 7 exceeds 50,000 characters and will be sent as a standalone session.
```

Sau đó tiếp tục grouping các block còn lại bình thường.

Lý do: block đã được preprocess theo cấu trúc nội dung và không muốn làm đứt ngữ cảnh bên trong block.

Tuy nhiên implementation phải cô lập logic grouping thành function riêng để sau này dễ bổ sung strategy chia oversized block.

---

# 18. Session boundaries

Khi ghép nhiều blocks thành một session, phải giữ ranh giới đủ rõ để model nhận biết các block riêng biệt.

Có thể tái sử dụng delimiter:

```text
==========
```

giữa các blocks.

Không được nối:

```text
block1 + block2
```

mà làm mất line break hoặc khiến hai câu dính nhau.

Ví dụ session:

```text
<block 1>

==========

<block 2>

==========

<block 3>
```

---

# 19. Heading reconstruction

Input là plain `.txt`, nên heading Markdown chưa tồn tại.

Model phải chuyển các heading numbering thành Markdown heading.

Quy tắc chính:

```text
Chapter 1. ...
```

→

```markdown
# Chapter 1. ...
```

hoặc bản dịch tương ứng:

```markdown
# Chương 1. ...
```

Numbered section:

```text
1. ...
```

→

```markdown
## 1. ...
```

Subsection:

```text
1.1. ...
```

→

```markdown
### 1.1. ...
```

Tiếp tục theo độ sâu numbering:

```text
1.1.1.
```

→

```markdown
#### 1.1.1. ...
```

v.v.

Model cần dựa vào ngữ cảnh để tránh hiểu nhầm:

```text
1. Apple
2. Banana
```

trong một normal numbered list thành heading.

Không nên cố chuyển heading hoàn toàn bằng regex trong Python trước khi dịch nếu điều đó có nguy cơ phá cấu trúc sách.

Nên giao cho translation model nhận diện heading dựa trên:

* numbering;
* surrounding content;
* chapter structure;
* semantic context.

Python chịu trách nhiệm truyền instruction rõ ràng cho model và bảo toàn output Markdown.

---

# 20. Preserve technical content

Bản dịch phải đặc biệt cẩn thận với:

* source code;
* shell commands;
* command-line arguments;
* filenames;
* paths;
* environment variables;
* API names;
* function names;
* class names;
* package names;
* URLs;
* mathematical expressions;
* equations;
* JSON;
* YAML;
* XML;
* Markdown code fences;
* tables;
* configuration examples.

Không dịch nội dung code.

Ví dụ:

```bash
pip install transformers
```

phải giữ nguyên.

Tên như:

```text
AutoTokenizer.from_pretrained()
OPENAI_API_KEY
/etc/passwd
```

phải giữ nguyên.

---

# 21. Translation output

Mỗi model call trả về bản dịch Markdown của session tương ứng.

Program phải append output đó ngay vào file:

```text
*_vi.md
```

theo đúng thứ tự session.

Ví dụ:

```text
session_1 -> append
session_2 -> append
session_3 -> append
...
```

Không cần giữ toàn bộ bản dịch của cuốn sách trong RAM rồi mới ghi ra file.

Mục tiêu là hỗ trợ các input rất lớn.

Sau mỗi translation session thành công:

1. append output;
2. flush dữ liệu xuống file;
3. log progress.

Ví dụ:

```text
[3/17] Translating session...
[3/17] Done - 43,812 input chars
```

---

# 22. Do not corrupt output on failure

Nếu một session lỗi:

* không append partial/garbled output vào `.md`;
* log rõ session index;
* log exception/message hữu ích;
* chương trình không được giả vờ rằng session thành công.

Hãy thiết kế error handling sao cho có thể xác định:

```text
file
block range
session index
model/backend
```

đang lỗi.

Không đưa secret/API key vào error log.

Nếu retry được áp dụng, chỉ append output sau khi request thực sự thành công.

---

# 23. Resume-friendly design

Vì sách có thể rất dài và translation có thể chạy nhiều session, hãy thiết kế code theo hướng dễ bổ sung/resume.

Ít nhất:

* session grouping phải deterministic;
* session index rõ ràng;
* không append duplicate content trong cùng execution;
* output được flush sau từng session;
* `--overwrite` có semantics rõ ràng.

Nếu repository hiện tại đã có checkpoint/resume convention, ưu tiên áp dụng nó.

Không tự tạo một hệ thống checkpoint quá phức tạp nếu chưa cần thiết, nhưng architecture không được khiến việc thêm resume về sau trở nên khó khăn.

---

# 24. Context consistency

Đối với interactive mode:

```text
codex
claude
```

cần cố gắng duy trì cùng conversation cho toàn bộ một file để model nhớ:

* thuật ngữ đã dịch;
* acronym đã giới thiệu;
* phong cách dịch;
* context từ section trước.

Đối với:

```text
non-codex
non-claude
gemini
```

nếu backend implementation không duy trì conversation state, mỗi request phải đủ instruction để tự dịch session hiện tại đúng yêu cầu.

Không được silently assume context tồn tại khi backend thực tế stateless.

---

# 25. Translation prompt flow

## Interactive

Luồng bắt buộc về mặt logic:

```text
SYSTEM/INITIAL:
instruction/en2vi_prompt.md

USER:
session_1

ASSISTANT:
translation_1

USER:
session_2

ASSISTANT:
translation_2

...

USER:
session_n

ASSISTANT:
translation_n
```

---

## Non-interactive

Mỗi call:

```text
instruction/en2vi_prompt.md

<clear separator>

session_i
```

Ví dụ logic:

```text
request_1 = prompt + session_1
request_2 = prompt + session_2
...
request_n = prompt + session_n
```

Phải có separator rõ giữa instruction và source text để model không nhầm source text là instruction.

---

# 26. End-of-file glossary / definitions

Sau khi dịch xong toàn bộ nội dung của một file, cuối file Markdown cần bổ sung một phần tổng hợp các thuật ngữ/định nghĩa đáng chú ý.

Ví dụ:

```markdown
---

# Thuật ngữ và khái niệm cần lưu ý

## Transformer
...

## Retrieval-Augmented Generation (RAG)
...

## Zero-day vulnerability
...
```

Mục đích của phần này là để sau này có thể sử dụng làm:

```text
summary
```

Chỉ chọn những:

* khái niệm khó;
* thuật ngữ kỹ thuật quan trọng;
* khái niệm mới xuất hiện;
* acronym quan trọng;
* thuật ngữ dễ gây nhầm lẫn.

Không cần liệt kê mọi thuật ngữ trong chương.

Các định nghĩa phải:

* ngắn gọn;
* chính xác;
* dựa trên ngữ cảnh của nội dung vừa dịch;
* không bịa thông tin không có căn cứ.

---

# 27. Glossary generation strategy

Phần glossary chỉ được sinh **sau khi tất cả translation sessions của file đã hoàn thành thành công**.

Thiết kế workflow sao cho có thể thu thập các candidate terms trong quá trình dịch hoặc thực hiện một final model request phù hợp.

Không yêu cầu đưa toàn bộ một cuốn sách rất lớn vào final prompt nếu vượt context limit.

Ưu tiên một strategy có khả năng scale, ví dụ:

```text
translation session
      ↓
translation
      ↓
optional candidate terms
      ↓
accumulate terms
      ↓
final glossary generation/deduplication
```

hoặc giải pháp tương đương.

Nếu để model trả candidate terms cùng translation, phải có format rõ ràng và **không được để metadata/candidate terms lẫn vào nội dung bản dịch chính**.

Có thể sử dụng structured delimiter hoặc structured response rồi parse.

Hãy chọn implementation ổn định, đơn giản và dễ maintain.

---

# 28. Do not alter the translated content for glossary extraction

Glossary extraction không được làm thay đổi:

* nội dung dịch;
* heading;
* paragraph;
* code;
* sequence của sách.

Translation và metadata extraction nên được tách biệt rõ trong implementation.

---

# 29. CLI design

Sử dụng `argparse` hoặc CLI framework đã được repository chuẩn hóa.

Tối thiểu phải có:

```text
-i / --input
-o / --output
-m / --model
--overwrite
-h / --help
```

Model choices:

```text
gemini
codex
claude
non-codex
non-claude
```

Help message phải đủ rõ để người dùng hiểu cách chạy.

Ví dụ:

```bash
python main.en2vi.py \
    -i ../data/LLM/Hands_on_LLM/text \
    -m non-codex
```

Ví dụ single file:

```bash
python main.en2vi.py \
    -i ../data/LLM/Hands_on_LLM/text/chapter_01.txt \
    -m gemini
```

Ví dụ custom output:

```bash
python main.en2vi.py \
    -i ../data/LLM/Hands_on_LLM/text \
    -o ../data/LLM/Hands_on_LLM/translated \
    -m claude \
    --overwrite
```

---

# 30. Recommended internal architecture

Không bắt buộc sử dụng đúng các tên dưới đây nếu `.claude/CLAUDE.md` quy định khác, nhưng code phải được tách logic rõ ràng tương đương:

```text
parse arguments
      ↓
load configuration
      ↓
load translation prompt
      ↓
resolve input files
      ↓
for each input file:
    resolve output path
    read source
    split blocks
    build sessions
    initialize backend
    translate sessions
    append translations
    generate glossary
    append glossary
      ↓
summary
```

Các responsibility nên tách thành function/class hợp lý, ví dụ:

```text
loadConfig()
loadPrompt()
resolveInputFiles()
resolveOutputPath()
splitBlocks()
groupBlocksIntoSessions()
translateSession()
appendTranslation()
generateGlossary()
processFile()
main()
```

Tên thực tế phải tuân thủ `.claude/CLAUDE.md`.

Không viết toàn bộ logic vào một `main()` khổng lồ.

---

# 31. Backend abstraction

Năm model mode có workflow khác nhau nhưng phần xử lý file giống nhau.

Do đó nên có abstraction rõ ràng, ví dụ:

```python
class TranslationBackend:
    ...
```

với implementation:

```text
GeminiBackend
CodexInteractiveBackend
ClaudeInteractiveBackend
CodexNonInteractiveBackend
ClaudeNonInteractiveBackend
```

hoặc một thiết kế tương đương phù hợp coding conventions hiện tại.

Phần:

```text
file reading
block splitting
session grouping
output writing
```

không được duplicate năm lần.

---

# 32. Subprocess requirements

Khi chạy:

```text
codex
claude
codex exec
claude -p
```

phải:

* sử dụng `subprocess` an toàn;
* tránh `shell=True` nếu không thực sự cần;
* capture stdout/stderr đúng cách;
* preserve Unicode;
* kiểm tra exit code;
* xử lý executable không tồn tại;
* xử lý timeout nếu phù hợp;
* tránh deadlock khi output lớn;
* không làm mất response multiline;
* không quote command sai khi chạy trên Windows/Linux.

Nếu interactive CLI cần pseudo-terminal hoặc cơ chế đặc biệt, hãy khảo sát capability thực tế trước khi implementation.

**Không giả lập interactive session bằng cách gọi nhiều subprocess độc lập rồi coi chúng như một conversation.**

Nếu CLI hiện tại không hỗ trợ interaction theo cách đơn giản với `subprocess.Popen`, hãy sử dụng mechanism thực sự phù hợp với CLI/version cài đặt và giải thích lựa chọn trong code/comment ngắn gọn.

---

# 33. Large prompt handling

Không truyền prompt dài qua command-line argument nếu có nguy cơ:

* vượt OS command-line length;
* lỗi quoting;
* lỗi newline;
* lỗi Unicode.

Đặc biệt cần chú ý với:

```text
50,000 chars
```

và:

```text
prompt + 50,000 chars
```

Nếu Codex/Claude CLI hỗ trợ stdin thì ưu tiên stdin hoặc cơ chế input chính thức phù hợp.

Ví dụ, không nên mặc định triển khai:

```python
subprocess.run(["codex", "exec", huge_prompt])
```

nếu CLI hỗ trợ nhận input qua stdin an toàn hơn.

Hãy kiểm tra command usage thực tế.

---

# 34. File encoding

Input/output phải xử lý Unicode ổn định.

Mặc định ưu tiên:

```text
UTF-8
```

Output Markdown tiếng Việt phải giữ đúng dấu.

Xử lý BOM nếu cần theo convention hiện có.

---

# 35. Newline handling

Khi append session translations:

* đảm bảo giữa hai translation outputs có newline hợp lý;
* không làm hai paragraph/session dính nhau;
* không tự ý thêm separator gây ảnh hưởng cấu trúc sách nếu không cần thiết.

Nên normalize ở mức tối thiểu.

---

# 36. Logging/progress

CLI cần hiển thị đủ thông tin để theo dõi tiến trình.

Ví dụ:

```text
Model: non-codex
Input: chapter_01.txt
Blocks: 74
Translation sessions: 11

[1/11] Translating 47,821 chars...
[1/11] Done
[2/11] Translating 49,102 chars...
[2/11] Done
...
Generating glossary...
Done.

Output: .../tran/chapter_01_vi.md
```

Với nhiều file:

```text
[File 2/14] chapter_02.txt
```

Không log toàn bộ source text hoặc translated content ra terminal trừ khi debug mode thực sự cần.

Không log secrets.

---

# 37. Validation

Trước khi dịch một file, validate:

* input tồn tại;
* input đúng `.txt`;
* prompt file tồn tại;
* output directory có thể tạo;
* selected model hợp lệ;
* config backend đầy đủ;
* CLI executable tương ứng tồn tại khi dùng CLI backend.

Nếu lỗi configuration xảy ra, fail với message rõ ràng thay vì traceback khó hiểu, trừ khi debug mode được bật theo convention repository.

---

# 38. Empty files and empty blocks

Nếu input file rỗng:

```text
[SKIP] Empty input file: ...
```

Không gọi model.

Nếu delimiter tạo block rỗng:

* loại block rỗng;
* không tạo empty session.

---

# 39. Preserve ordering

Đây là yêu cầu bắt buộc.

Nếu blocks:

```text
B1, B2, B3, B4, B5
```

thì output phải luôn tương ứng:

```text
T(B1), T(B2), T(B3), T(B4), T(B5)
```

Không dùng parallel translation nếu điều đó:

* làm thay đổi thứ tự;
* phá interactive context;
* làm thuật ngữ không nhất quán.

Ưu tiên correctness và consistency hơn tốc độ.

---

# 40. Translation integrity

Không để model trả các câu kiểu:

```text
Here is the translation:
```

```text
Sure, I can translate this:
```

```text
Bản dịch như sau:
```

vào file Markdown.

Output của từng translation request phải chỉ chứa **nội dung sách đã dịch dưới dạng Markdown**, không có conversational preamble/postamble.

Prompt phải nhấn mạnh điều này.

Nếu backend vẫn sinh wrapper có thể xác định chắc chắn, chỉ sanitize khi an toàn. Không viết heuristic quá aggressive làm mất nội dung thật.

---

# 41. No summarization during translation

Translation session tuyệt đối không được:

* summarize;
* shorten;
* omit examples;
* omit footnotes;
* omit captions;
* omit explanations;
* merge multiple paragraphs thành một summary;
* simplify technical arguments quá mức.

Phải dịch đầy đủ source session.

---

# 42. Maintain author intent

Bản dịch phải giữ:

* tone;
* logical emphasis;
* contrasts;
* uncertainty;
* warnings;
* qualifications;
* examples;
* technical precision.

Ví dụ:

```text
may
might
can
must
should
typically
approximately
in general
```

không được dịch như các mức độ chắc chắn tương đương nhau.

---

# 43. Output summary

Sau khi hoàn thành execution, CLI nên báo summary tương tự:

```text
Translation completed.

Files discovered : 12
Files translated : 10
Files skipped    : 2
Files failed     : 0
Output directory : ...
```

Nếu có lỗi, liệt kê ngắn gọn file lỗi.

---

# 44. Requirements for generated code

Hãy trực tiếp tạo file:

```text
main.en2vi.py
```

Không chỉ mô tả pseudocode.

Code phải:

* runnable;
* không chứa placeholder kiểu `TODO: implement`;
* không để function quan trọng chưa implement;
* type hint hợp lý nếu project convention sử dụng;
* tuân thủ `.claude/CLAUDE.md`;
* tránh dependency không cần thiết;
* xử lý path cross-platform bằng `pathlib`;
* có `main()` entry point;
* có error handling rõ ràng.

---

# 45. Inspect actual CLI capabilities first

Trước khi implementation phần Codex/Claude CLI, hãy kiểm tra command/help/version thực tế có sẵn trong environment, ví dụ các khả năng tương đương:

```text
codex --help
codex exec --help
claude --help
```

Mục đích là xác định chính xác:

* interactive invocation;
* non-interactive invocation;
* stdin support;
* session/resume support;
* output format;
* flags;
* cách capture stdout.

**Không được tự tưởng tượng flag hoặc API của CLI.**

Nếu implementation cần khác với mô tả conceptual ở trên do CLI thực tế, hãy giữ nguyên semantics mong muốn nhưng sử dụng command chính xác của CLI.

---

# 46. Verify after implementation

Sau khi tạo `main.en2vi.py`, thực hiện ít nhất:

1. syntax check;
2. kiểm tra `--help`;
3. test logic `splitBlocks()`;
4. test session grouping quanh ngưỡng `50_000`;
5. test oversized block;
6. test output path derivation;
7. test `--overwrite`;
8. test empty file;
9. test directory input;
10. test invalid model/config;
11. nếu có thể, dry-run hoặc mock backend để kiểm tra end-to-end mà không tiêu tốn API/token không cần thiết.

Đặc biệt test các boundary:

```text
49,999 chars
50,000 chars
50,001 chars
```

và trường hợp:

```text
session_current + delimiter + next_block
```

vượt giới hạn.

Phải tính delimiter/newline overhead khi grouping để session bình thường thực sự không vượt `50_000 chars`.

---

# 47. Do not make unrelated changes

Chỉ sửa/tạo các file thực sự cần thiết để hoàn thành task.

File chính bắt buộc:

```text
main.en2vi.py
```

Nếu cần thêm dependency/config/helper, trước tiên kiểm tra repository hiện tại.

Không refactor các phần không liên quan.

Không thay đổi `.claude/CLAUDE.md`.

Không thay đổi nội dung sách nguồn.

Không commit secret hoặc API token.

---

# 48. Final response

Sau khi hoàn thành, báo cáo ngắn gọn:

1. file đã tạo/sửa;
2. architecture chính;
3. cách 5 backend hoạt động;
4. cách block được gom thành session;
5. cách output path được xác định;
6. cách chạy CLI với một vài ví dụ;
7. những test đã thực hiện;
8. bất kỳ limitation thực tế nào của Codex/Claude CLI nếu phát hiện trong quá trình implementation.

Quan trọng: **hãy thực hiện implementation và kiểm thử thực tế, không chỉ đưa ra đề xuất hoặc pseudocode.**
