import json
from google import genai
from google.genai import types
from .config import GEMINI_API_KEY, GEMINI_MODEL, PROMPT_PATH
from .topic_selector import candidates_for_date

def _client():
    if not GEMINI_API_KEY:
        raise RuntimeError("Не задан GEMINI_API_KEY в файле .env")
    return genai.Client(api_key=GEMINI_API_KEY)

def _read_prompt():
    return PROMPT_PATH.read_text(encoding="utf-8")

def generate_post(day, previous_topics):
    season, candidates = candidates_for_date(day)
    prompt = f"""
{_read_prompt()}

Дата: {day.isoformat()}
Сезон для этой даты: {season}
Темы-кандидаты: {json.dumps(candidates, ensure_ascii=False)}
Недавно использованные темы, не повторяй их: {json.dumps(previous_topics[-80:], ensure_ascii=False)}

Выбери одну подходящую тему самостоятельно. Верни только корректный JSON с ключами:
topic, title, body.
В body включи весь готовый к публикации текст, кроме отдельного технического поля topic.
Исторические утверждения не выдумывай. Художественную историю явно обозначай как вымысел.
Заголовок должен быть первым предложением публикации и быть короче 140 символов.
"""
    response = _client().models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.8,
            response_mime_type="application/json",
            response_schema={
                "type": "OBJECT",
                "properties": {
                    "topic": {"type": "STRING"},
                    "title": {"type": "STRING"},
                    "body": {"type": "STRING"}
                },
                "required": ["topic", "title", "body"]
            }
        )
    )
    raw = response.text or ""
    data = json.loads(raw)
    for key in ("topic", "title", "body"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"ИИ вернул пустое или некорректное поле: {key}")
    data["title"] = data["title"].strip()
    data["body"] = data["body"].strip()
    return data

def validate_post(post):
    title, body = post["title"], post["body"]
    issues = []
    if len(title) > 140:
        issues.append("Заголовок длиннее 140 символов")
    required_terms = ["сезон", "ингредиент", "приготов", "совет"]
    combined = (title + "\n" + body).lower()
    for term in required_terms:
        if term not in combined:
            issues.append(f"Не обнаружен обязательный раздел/термин: {term}")
    if len(body) < 700:
        issues.append("Пост подозрительно короткий")
    if len(body) > 10000:
        issues.append("Пост слишком длинный для MVP; проверьте форматирование")
    return issues
