# BUILD MARKDOWN SUMMARIZATION CLI

## ROLE

Bạn là Senior Python Developer. Hãy xây dựng chương trình Python tóm tắt file Markdown bằng Codex CLI hoặc Claude CLI ở chế độ non-interactive.

- File cần xây dựng: `READBOOK/main/slide_create/summary.py`
- Prompt sử dụng: `READBOOK/instruction/summary_chapter.md`
- Không hard-code prompt trong source code.

## OBJECTIVE

Chương trình nhận một file Markdown hoặc thư mục chứa các file Markdown, chèn nội dung vào `{{MARKDOWN_CONTENT}}`, gửi prompt tới model qua `stdin`, lấy kết quả từ `stdout` và lưu thành file Markdown tóm tắt tương ứng.

Nếu prompt vượt giới hạn 50,000 token, tự động chia nội dung theo Heading 2 (`##`), xử lý lần lượt và ghép lại thành một file hoàn chỉnh.

## CLI

```text
-i, --input       File .md hoặc thư mục chứa Markdown.
-o, --output      Đường dẫn output tùy chọn.
-m, --model       Backend sử dụng: codex hoặc claude.
--overwrite       Cho phép ghi đè output đã tồn tại.
```

Nếu không có `-i`, mặc định sử dụng `./md`.

## RULES

### Rule 1 — Input và Output

- Nếu input là file `.md`, chỉ xử lý file đó; nếu là thư mục, xử lý recursive toàn bộ file `.md`.
- Cấu trúc input thường có dạng `./data/<categories>/.../<name_book>/md/`.
- Nếu không có `-o`, output mặc định là thư mục `sum` cùng cấp với `md`.
- Nếu có `-o`, sử dụng đường dẫn được chỉ định.
- Giữ cấu trúc thư mục tương đối khi xử lý recursive.
- Tên output thêm `_sum` trước extension: `chapter01.md → chapter01_sum.md`.

### Rule 2 — Prompt và Non-interactive

- Đọc prompt từ `READBOOK/instruction/summary_chapter.md` và thay `{{MARKDOWN_CONTENT}}` bằng nội dung cần xử lý.
- Sử dụng `subprocess`, truyền toàn bộ prompt qua `stdin`, không đưa prompt vào command-line argument.
- Với Codex, sử dụng `codex exec ... -` để yêu cầu CLI đọc prompt từ `stdin`.
- Lấy kết quả từ `stdout`, lỗi/diagnostic từ `stderr`, đồng thời kiểm tra return code.
- Tách riêng backend qua các function như `runCodex()`, `runClaude()` và `runModel()`.

Đặc biệt lưu ý cách truyền prompt dài. Có thể tham khảo cách triển khai:

```python
def runCodex(payload: str, cwd: Path, timeout: int) -> str:
    result = subprocess.run(
        [
            "codex",
            "exec",
            "--json",
            "--color",
            "never",
            "--skip-git-repo-check",
            "-",
        ],
        input=payload,
        text=True,
        capture_output=True,
        cwd=cwd,
        timeout=timeout,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())

    return result.stdout
```

Trong đó, `-` là input từ `stdin` và `input=payload` truyền toàn bộ prompt trực tiếp vào process. Không thay cách này bằng việc đưa `payload` thành một argument của command.

### Rule 3 — Giới hạn token

- Mỗi prompt hoàn chỉnh gồm `prompt template + Markdown content` không được vượt quá 50.000 token ≈ 125.000 char.
- Sử dụng ngưỡng an toàn thấp hơn một chút trước khi gửi.
- Nếu nằm trong giới hạn, xử lý file trong một request.

### Rule 4 — Chia nội dung

Nếu vượt giới hạn:

- Chia theo Heading 2 (`##`), trong đó mỗi Heading 2 cùng nội dung thuộc nó là một block.
- Ghép nhiều block liên tiếp nếu tổng prompt vẫn nằm trong giới hạn.
- Giữ nguyên thứ tự nội dung.
- Nếu một block `##` riêng lẻ vẫn quá lớn, tiếp tục chia theo heading thấp hơn hoặc paragraph.

### Rule 5 — Ghép kết quả

Sau khi xử lý các chunk, ghép lại thành một file Markdown duy nhất:

- Giữ đúng thứ tự section.
- Không lặp Heading chính không cần thiết.
- Hợp nhất các mục `## 0. Các thuật ngữ sử dụng` và loại bỏ thuật ngữ trùng.
- Không làm mất code block, bảng hoặc cấu trúc Markdown cần thiết.

Luôn đảm bảo:

```text
1 Markdown input → 1 Markdown summary
```

### Rule 6 — Overwrite và lỗi

- Nếu output tồn tại và không có `--overwrite`, bỏ qua.
- Không lưu file summary chưa hoàn chỉnh nếu model hoặc một chunk xử lý thất bại.
- Khi chạy batch, lỗi một file không làm dừng các file còn lại nếu có thể tiếp tục.
- Hiển thị ngắn gọn trạng thái: file, model, số chunk, thành công/thất bại.

### Rule 7 — Code

- Sử dụng `pathlib.Path`, `argparse`, `subprocess`, UTF-8 và exception handling phù hợp.
- Function dùng camelCase, biến dùng snake_case.
- Chia logic thành các function hợp lý; không đặt toàn bộ xử lý trong `main()`.
- Có `if __name__ == "__main__": main()`.
- Code phải chạy thực tế, không viết pseudo-code.

## DELIVERABLE

Tạo hoàn chỉnh `READBOOK/main/slide_create/summary.py`.

Sau code chỉ giải thích ngắn gọn những quyết định triển khai quan trọng nếu cần.