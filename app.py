import json
import os
import re
from pathlib import Path

import bleach
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request
import google.generativeai as genai

load_dotenv()

app = Flask(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

SYSTEM_INSTRUCTION = """너는 성경 해설가이다. 간결하지만 정확하게 쓴다.

[필수] 아래 4개 제목을 이모지와 함께 반드시 모두 작성한다. 하나라도 빠지면 안 된다.

📝 문단별 핵심
🌍 역사&문화적 배경
💡 중요한 원어
📍 지역명&인물·사람의 뜻

[항목별 형식 — HTML만]
📝 — <table> 1개, tbody 3행
🌍 — <ul> 3개 <li>, 각 1~2문장
💡 — <ul> 2~3개 <li>, 각 항목 <strong>한글음(히브리/헬라 원어)</strong> + 1~2문장
📍 — <ul> 2~3개 <li>, 지명·인물(사람) 각 1~2문장

문장은 마침표(.)로 끝내라. 없는 사실을 지어내지 마라. 한국어."""

GENERATION_CONFIG = {
    "temperature": 0.35,
    "max_output_tokens": 3072,
}

CACHE_VERSION = "v4"
CACHE_DIR = Path(__file__).resolve().parent / "cache" / "summaries"
REQUIRED_SECTION_IDS = frozenset({"core", "history", "hebrew", "places"})

ALLOWED_TAGS = [
    "table", "thead", "tbody", "tr", "th", "td",
    "ul", "ol", "li", "p", "strong", "em", "br", "div",
]
ALLOWED_ATTRS = {"table": ["class"], "th": ["class"], "td": ["class"], "div": ["class"]}

EMOJI_SECTIONS = [
    {"id": "core", "emoji": "📝", "title": "문단별 핵심",
     "header_strip": r"📝\s*문단별\s*핵심\s*[:：]?\s*"},
    {"id": "history", "emoji": "🌍", "title": "역사&문화적 배경",
     "header_strip": r"🌍\s*역사\s*[&＆]?\s*문화(?:적)?\s*배경\s*[:：]?\s*"},
    {"id": "hebrew", "emoji": "💡", "title": "중요한 원어",
     "header_strip": r"💡\s*중요한\s*(?:히브리어|헬라어|원어)\s*[:：]?\s*"},
    {"id": "places", "emoji": "📍", "title": "지역명&인물·사람의 뜻",
     "header_strip": r"📍\s*지역명\s*[&＆]?\s*(?:인물|사람)(?:·(?:인물|사람))?(?:의)?\s*뜻\s*[:：]?\s*"},
]

SECTION_DEFS = [
    {
        **s,
        "patterns": [
            rf"(?:^|\n)\s*{s['header_strip']}",
            rf"(?:^|\n)\s*{re.escape(s['emoji'])}\s*",
        ],
    }
    for s in EMOJI_SECTIONS
]

_model = None


def get_model():
    global _model
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
    if _model is None:
        genai.configure(api_key=GEMINI_API_KEY)
        _model = genai.GenerativeModel(
            GEMINI_MODEL,
            system_instruction=SYSTEM_INSTRUCTION,
            generation_config=GENERATION_CONFIG,
        )
    return _model


def extract_response_text(response) -> str:
    try:
        text = (response.text or "").strip()
        if text:
            return text
    except (ValueError, AttributeError):
        pass
    chunks = []
    for candidate in getattr(response, "candidates", None) or []:
        content = getattr(candidate, "content", None)
        for part in getattr(content, "parts", None) or []:
            part_text = getattr(part, "text", None)
            if part_text:
                chunks.append(part_text.strip())
    return "\n".join(chunks).strip()


def is_response_truncated(response) -> bool:
    candidates = getattr(response, "candidates", None) or []
    if not candidates:
        return False
    reason = str(getattr(candidates[0], "finish_reason", "") or "").upper()
    return "MAX" in reason or "LENGTH" in reason


def markdown_bullets_to_html(text: str) -> str:
    items = []
    for line in text.strip().splitlines():
        m = re.match(r"^[\-\*•]\s+(.+)$", line.strip())
        if m:
            items.append(m.group(1).strip())
    if not items:
        return text
    lis = "".join(f"<li>{bleach.clean(item, tags=[], strip=True)}</li>" for item in items)
    return f"<ul>{lis}</ul>"


def sanitize_section_html(body: str) -> str:
    body = body.strip()
    body = re.sub(r"^```(?:html)?\s*", "", body, flags=re.I)
    body = re.sub(r"\s*```$", "", body)
    if "<" not in body and re.search(r"^[\-\*•]\s", body, re.M):
        body = markdown_bullets_to_html(body)
    cleaned = bleach.clean(body, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    if "<table" in cleaned and "table-wrap" not in cleaned:
        cleaned = f'<div class="table-wrap">{cleaned}</div>'
    return cleaned.strip()


def find_section_starts(text: str) -> list[tuple[int, int, dict]]:
    matches = []
    for section in SECTION_DEFS:
        best = None
        for pattern in section["patterns"]:
            m = re.search(pattern, text, re.I)
            if m and (best is None or m.start() < best.start()):
                best = m
        if best:
            matches.append((best.start(), best.end(), section))
    matches.sort(key=lambda x: x[0])
    return matches


def _strip_section_header(body: str, section: dict) -> str:
    body = body.strip()
    body = re.sub(rf"^(?:{section['header_strip']})", "", body, flags=re.I)
    body = re.sub(rf"^{re.escape(section['emoji'])}\s*[^\n<]*\n?", "", body, count=1)
    return body.strip()


def parse_sections_by_emoji(text: str) -> list[dict]:
    hits: list[tuple[int, dict]] = []
    for section in EMOJI_SECTIONS:
        emoji = section["emoji"]
        pos = 0
        found_at = -1
        while True:
            idx = text.find(emoji, pos)
            if idx == -1:
                break
            at_line_start = idx == 0 or text[idx - 1] in "\n\r"
            if at_line_start:
                found_at = idx
                break
            pos = idx + 1
        if found_at == -1:
            idx = text.find(emoji)
            if idx != -1:
                found_at = idx
        if found_at != -1:
            hits.append((found_at, section))

    if len(hits) < 2:
        return []

    hits.sort(key=lambda x: x[0])
    sections = []
    for i, (start, section) in enumerate(hits):
        end = hits[i + 1][0] if i + 1 < len(hits) else len(text)
        body = _strip_section_header(text[start:end], section)
        if body:
            sections.append({
                "id": section["id"],
                "emoji": section["emoji"],
                "title": section["title"],
                "html": sanitize_section_html(body),
            })
    return sections


def parse_sections(text: str) -> list[dict]:
    sections = parse_sections_by_emoji(text)
    if len(sections) >= 3:
        return sections

    starts = find_section_starts(text)
    if not starts:
        return sections

    regex_sections = []
    for i, (_start, end, section) in enumerate(starts):
        body_end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        body = _strip_section_header(text[end:body_end], section)
        if body:
            regex_sections.append({
                "id": section["id"],
                "emoji": section["emoji"],
                "title": section["title"],
                "html": sanitize_section_html(body),
            })
    return regex_sections if len(regex_sections) > len(sections) else sections


def sections_complete(sections: list[dict]) -> bool:
    return REQUIRED_SECTION_IDS <= {s["id"] for s in sections}


def _cache_file(book: str, chapter_num: int) -> Path:
    safe = re.sub(r"[^\w가-힣]", "_", book)
    return CACHE_DIR / f"{CACHE_VERSION}_{safe}_{chapter_num}.json"


def load_server_cache(book: str, chapter_num: int) -> dict | None:
    path = _cache_file(book, chapter_num)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def save_server_cache(book: str, chapter_num: int, payload: dict) -> None:
    path = _cache_file(book, chapter_num)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def build_summary_payload(book: str, chapter_num: int) -> dict:
    cached = load_server_cache(book, chapter_num)
    if cached:
        cached["cached"] = True
        return cached

    prompt = (
        f"『{book}』 {chapter_num}장.\n"
        f"반드시 4개 섹션을 모두 작성: 📝 문단별 핵심, 🌍 역사&문화적 배경, "
        f"💡 중요한 원어, 📍 지역명&인물·사람의 뜻.\n"
        f"HTML 형식. 표 3행, 리스트 2~3항목, 항목당 1~2문장."
    )
    model = get_model()
    response = model.generate_content(prompt)
    text = extract_response_text(response)

    if not text:
        raise RuntimeError("요약을 생성하지 못했습니다.")

    sections = parse_sections(text)

    if is_response_truncated(response) or not sections_complete(sections):
        missing = REQUIRED_SECTION_IDS - {s["id"] for s in sections}
        fix = (
            prompt
            + f"\n[수정] 빠진 섹션이 있다: {', '.join(sorted(missing))}. "
            "4개 섹션(📝🌍💡📍)을 처음부터 순서대로 모두 다시 작성하라. "
            "특히 💡 중요한 원어 와 📍 지역명&인물·사람의 뜻 을 반드시 포함하라."
        )
        response = model.generate_content(fix)
        text = extract_response_text(response)
        if not text:
            raise RuntimeError("요약을 생성하지 못했습니다.")
        sections = parse_sections(text)
    if not sections:
        sections = [{
            "id": "core",
            "emoji": "📝",
            "title": "요약",
            "html": sanitize_section_html(text),
        }]
    payload = {
        "summary": text,
        "sections": sections,
        "book": book,
        "chapter": chapter_num,
        "cached": False,
    }
    save_server_cache(book, chapter_num, payload)
    return payload


@app.after_request
def cache_static(response):
    if request.path.startswith("/static/"):
        response.cache_control.max_age = 604800
        response.cache_control.public = True
    return response


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/summarize", methods=["POST"])
@app.route("/get_summary", methods=["POST"])
def summarize():
    data = request.get_json(silent=True) or {}
    book = (data.get("book") or "").strip()
    chapter = data.get("chapter")

    if not book:
        return jsonify({"error": "성경 권명이 필요합니다."}), 400

    try:
        chapter_num = int(chapter)
    except (TypeError, ValueError):
        return jsonify({"error": "유효한 장 번호가 필요합니다."}), 400

    if chapter_num < 1:
        return jsonify({"error": "유효한 장 번호가 필요합니다."}), 400

    try:
        payload = build_summary_payload(book, chapter_num)
        return jsonify(payload)
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        app.logger.exception("summarize failed")
        return jsonify({"error": f"Gemini API 오류: {e}"}), 502


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
