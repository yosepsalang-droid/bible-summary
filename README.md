# 성경 요약 웹사이트

Flask + Google Gemini API 기반 모바일 최적화 성경 장별 요약 서비스입니다.

## 실행 방법

```bash
cd bible_web
python -m venv .venv

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
python app.py
```

브라우저에서 `http://localhost:5000` (또는 같은 Wi‑Fi의 `http://<PC IP>:5000`)으로 접속합니다. 카카오톡 링크 공유 시 PC IP 주소를 사용하세요.

## 환경 변수

`.env` 파일:

```
GEMINI_API_KEY=your_api_key
GEMINI_MODEL=gemini-2.5-flash
```

## 기능

- 구약 39권 / 신약 27권 격자 버튼
- 권 선택 → 장 목록 (페이지 새로고침 없이 전환)
- 장 선택 → Gemini API 요약 (4단 양식, 1,500~2,000자)
