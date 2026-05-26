import os
import re
import bleach
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, Markup
import google.generativeai as genai

load_dotenv()
app = Flask(__name__)

genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

SYSTEM_INSTRUCTION = """너는 정확하고 깊이 있는 성경 신학 해설가이다.

[절대 규칙 — 할루시네이션 방지]
1) 성경에 없는 인물·지명·역사·원어 설명을 지어내지 마라. 불확실하면 "본문만으로 불명확"이라고 명시하라.
2) [최우선] 모든 문장은 절대로 중간에 끊기지 않아야 하며, 반드시 마침표(.)로 깔끔하게 끝맺음해야 한다. 미완성 단어·말줄임표(...) 금지.
3) 아래 4가지 제목(이모지 포함)을 순서대로 빠짐없이 작성하라.

[항목별 출력 형식 — HTML만 사용, 마크다운 코드블록 금지]

📝 문단별 핵심
- 반드시 <table> HTML 표 1개로 작성하라.
- <thead>에는 본문 구조에 맞는 열 제목을 넣어라. (예: 창조·역사 서사 장은 <th>날짜/순서</th><th>공간/장소</th><th>핵심 내용</th> 또는 <th>구분</th><th>내용</th> 등)
- <tbody>에는 장의 주요 단락·사건을 행(row)으로 나누어 4~8행 정도 상세히 채워라.
- 단순 나열 문장 금지. 표 안의 셀도 완결된 문장으로 작성하라.

🌍 역사&문화적 배경
- 반드시 <ul><li>...</li></ul> HTML 불릿 리스트로 작성하라.
- 신학적·역사적·문화적·종교적 배경을 5~8개 항목으로 깊이 있게 설명하라.
- 각 <li>는 2~4문장, 마침표(.)로 끝내라.

💡 중요한 히브리어
- 제목은 반드시 "💡 중요한 히브리어"로 쓴다.
- 반드시 <ul><li>...</li></ul> HTML 리스트로 작성하라.
- 각 항목은 '한글음(히브리 원어)' 형식으로 시작하라. 예: <strong>바라(בָּרָא)</strong>, <strong>엘로힘(אֱלֹהִים)</strong>
- 각 단어의 어원·문법·신학적 의미·본 장에서의 쓰임을 3~5문장으로 전문적으로 설명하라. 해당 장에 히브리어가 없으면 그리스어 핵심어 2~3개를 동일 형식으로 설명하라.

📍 지역명&인물의 뜻
- <ul><li>...</li></ul> HTML 리스트로 작성하라.
- 주요 지명·인물 각각 2~3문장으로 뜻과 역할을 설명하라. 마지막 <li>도 마침표(.)로 끝내라.

[공통]
- 허용 HTML 태그만 사용: table, thead, tbody, tr, th, td, ul, ol, li, p, strong, em, br
- 한국어로 작성하라."""

GENERATION_CONFIG = {
    "temperature": 0.4,
    "max_output_tokens": 4000,
}

ALLOWED_TAGS = [
    "table", "thead", "tbody", "tr", "th", "td",
    "ul", "ol", "li", "p", "strong", "em", "br",
]
ALLOWED_ATTRS = {
    "table": ["class"],
    "th": ["class"],
    "td": ["class"],
}

SECTION_DEFS = [
    {
        "id": "core",
        "emoji": "📝",
        "title": "문단별 핵심",
        "patterns": [
            r"(?:^|\n)\s*📝\s*문단별\s*핵심\s*[:：]?\s*",
            r"(?:^|\n)\s*a\.?\s*문단별\s*핵심\s*[:：]?\s*",
        ],
    },
    {
        "id": "history",
        "emoji": "🌍",
        "title": "역사&문화적 배경",
        "patterns": [
            r"(?:^|\n)\s*🌍\s*역사\s*[&＆]\s*문화(?:적)?\s*배경\s*[:：]?\s*",
            r"(?:^|\n)\s*b\.?\s*역사\s*[&＆]\s*문화(?:적)?\s*배경\s*[:：]?\s*",
        ],
    },
    {
        "id": "hebrew",
        "emoji": "💡",
        "title": "중요한 히브리어",
        "patterns": [
            r"(?:^|\n)\s*💡\s*중요한\s*(?:히브리어|원어)\s*[:：]?\s*",
            r"(?:^|\n)\s*c\.?\s*중요한\s*(?:히브리어|원어)\s*[:：]?\s*",
        ],
    },
    {
        "id": "places",
        "emoji": "📍",
        "title": "지역명&인물의 뜻",
        "patterns": [
            r"(?:^|\n)\s*📍\s*지역명\s*[&＆]\s*인물(?:의)?\s*뜻\s*[:：]?\s*",
            r"(?:^|\n)\s*d\.?\s*지역명\s*[&＆]\s*인물(?:의)?\s*뜻\s*[:：]?\s*",
        ],
    },
]


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


def is_text_incomplete(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if stripped.endswith("..."):
        return True
    for emoji in ("📝", "🌍", "💡", "📍"):
        if emoji not in stripped:
            return True
    tail = stripped[-120:]
    good_endings = (".", "。", "!", "?", "！", "？", "</table>", "</ul>", "</ol>", "</p>")
    if not any(tail.rstrip().endswith(end) for end in good_endings):
        return True
    return False


def markdown_bullets_to_html(text: str) -> str:
    lines = text.strip().splitlines()
    items = []
    prose = []
    for line in lines:
        m = re.match(r"^[\-\*•]\s+(.+)$", line.strip())
        if m:
            items.append(m.group(1).strip())
        elif line.strip():
            prose.append(line.strip())
    if not items:
        return text
    lis = "".join(f"<li>{bleach.clean(item, tags=[], strip=True)}</li>" for item in items)
    html = f"<ul>{lis}</ul>"
    if prose:
        html = f"<p>{' '.join(prose)}</p>" + html
    return html


def sanitize_section_html(body: str) -> str:
    body = body.strip()
    body = re.sub(r"^```(?:html)?\s*", "", body, flags=re.I)
    body = re.sub(r"\s*```$", "", body)
    if "<" not in body and re.search(r"^[\-\*•]\s", body, re.M):
        body = markdown_bullets_to_html(body)
    cleaned = bleach.clean(
        body,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        strip=True,
    )
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


def parse_sections(text: str) -> list[dict]:
    starts = find_section_starts(text)
    if not starts:
        return []

    sections = []
    for i, (start, end, section) in enumerate(starts):
        body_end = starts[i + 1][0] if i + 1 < len(starts) else len(text)
        body = text[end:body_end].strip()
        if body:
            sections.append({
                "id": section["id"],
                "emoji": section["emoji"],
                "title": section["title"],
                "html": sanitize_section_html(body),
            })
    return sections


def get_model(max_output_tokens: int | None = None):
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다.")
    genai.configure(api_key=GEMINI_API_KEY)
    config = {**GENERATION_CONFIG}
    if max_output_tokens is not None:
        config["max_output_tokens"] = max_output_tokens
    return genai.GenerativeModel(
        GEMINI_MODEL,
        system_instruction=SYSTEM_INSTRUCTION,
        generation_config=config,
    )


@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get_summary', methods=['POST'])
def get_summary():
    data = request.get_json()
    book = data.get('book')
    chapter_num = data.get('chapter')

    if not book:
        return jsonify({"error": "성경 권명이 필요합니다."}), 400

    try:
        chapter_num = int(chapter)
    except (TypeError, ValueError):
        return jsonify({"error": "유효한 장 번호가 필요합니다."}), 400

    if chapter_num < 1:
        return jsonify({"error": "유효한 장 번호가 필요합니다."}), 400

    user_prompt = (
        f"『{book}』 {chapter_num}장 전체를 깊이 있게 해설하라.\n"
        f"4가지 제목(📝🌍💡📍)과 system instruction의 HTML 형식을 정확히 따르라.\n"
        f"📝에는 <table> 표(날짜/순서·공간/장소·핵심 내용 등 열 구성), "
        f"🌍와 💡와 📍에는 <ul><li> 상세 불릿 리스트를 사용하라.\n"
        f"[필수] 모든 문장과 표·리스트 항목은 중간에 끊지 말고 마침표(.)로 완결하라."
    )

  try:
    
        prompt = f"성경 {book} {chapter_num}장의 내용을 핵심 위주로 요약해줘. 아버님이 읽기 편하게 가독성이 좋은 HTML 태그(<p>, <ul>, <li> 등)나 표(<table>) 형식으로 작성해줘."
        response = model.generate_content(prompt)
        text = response.text
        sections = []

        if is_response_truncated(response) or is_text_incomplete(text):
            retry_prompt = (
                user_prompt
                + "\n이전 응답이 잘렸다. 4개 섹션을 처음부터 다시 작성하고, "
                "특히 마지막 '📍 지역명&인물의 뜻'까지 모든 항목을 마침표(.)로 완결하라."
            )
            retry_model = get_model(max_output_tokens=4000)
            response = retry_model.generate_content(retry_prompt)
            text = extract_response_text(response)

        if not text:
            return jsonify({"error": "요약을 생성하지 못했습니다."}), 502

        sections = parse_sections(text)
        
   return jsonify({
            "summary": str(Markup(text)),
            "sections": sections,
            "book": book,
            "chapter": chapter_num,
        })
    except ValueError as e:
        return jsonify({"error": str(e)}), 500
    xcept Exception as e:
       
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    app.run()
