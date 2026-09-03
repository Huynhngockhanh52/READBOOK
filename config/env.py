API_GEMINI_KEY = "AIzaSyBDbh3evynsy1sqtJq6h0UhnfrgSVy3C9s"
# MODEL = "gemini-3.1-flash-live-preview"
# MODEL = "gemini-2.5-pro"
MODEL = "gemini-3-flash-preview"
MODEL_35 = "gemini-3.5-flash"
MODEL_25 = "gemini-2.5-flash"
MODEL_31_PRE = "gemini-3.1-flash-lite-preview"
# =================== XEM THÊM ====================
# Link: https://aistudio.google.com/rate-limit?timeRange=last-28-days
FULL_MODELS = [
    "gemini-2.5-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite-preview"
]


ST_PAGE = 13
EN_PAGE = None
PAGES_PER_REQUEST = 5

INSTRUCTION_TRANSLATE_RESEARCH = """
Bạn là chuyên gia dịch thuật học thuật. Tôi cần bạn dịch nội dung của bài research sau với các các đoạn văn tiếng Anh sang tiếng Việt theo yêu cầu:
- Dịch chính xác, rõ ràng theo ngữ nghĩa khoa học
- Giữ các thuật ngữ chuyên ngành bằng tiếng Anh (hoặc kèm tiếng Anh nếu cần)
- Giữ nguyên cấu trúc (đánh số, đoạn, format)
- Không giải thích thêm, không lạc đề, không thêm nội dung, chỉ trả về nội dung đã dịch.
"""

