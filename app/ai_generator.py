import json
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole
from .config import (
    GIGACHAT_CREDENTIALS,
    GIGACHAT_MODEL,
    GIGACHAT_SCOPE,
    GIGACHAT_BASE_URL,
    GIGACHAT_VERIFY_SSL_CERTS,
    PROMPT_PATH,
)
from .topic_selector import candidates_for_date

def _read_prompt():
    return PROMPT_PATH.read_text(encoding="utf-8")

def _generate_text(prompt: str) -> str:
    if not GIGACHAT_CREDENTIALS:
        raise RuntimeError("Не задан GIGACHAT_CREDENTIALS в файле .env")
    # Не отключаем проверку TLS по умолчанию: при необходимости настройте корневой сертификат Минцифры.
    with GigaChat(
        credentials=GIGACHAT_CREDENTIALS,
        scope=GIGACHAT_SCOPE,
        base_url=GIGACHAT_BASE_URL,
        verify_ssl_certs=GIGACHAT_VERIFY_SSL_CERTS,
        timeout=90,
        max_retries=2,
    ) as client:
        request = Chat(
            model=GIGACHAT_MODEL,
            messages=[Messages(role=MessagesRole.USER, content=prompt)],
            temperature=0.8,
        )
        response = client.chat(request)
    try:
        return response.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError("GigaChat вернул ответ в неожиданном формате") from exc

def generate_post(day, previous_topics):
    season, candidates = candidates_for_date(day)
    prompt = f"""
{_read_prompt()}

Дата: {day.isoformat()}
Сезон для этой даты: {season}
Темы-кандидаты: {json.dumps(candidates, ensure_ascii=False)}
Недавно использованные темы, не повторяй их: {json.dumps(previous_topics[-80:], ensure_ascii=False)}

Выбери одну подходящую тему самостоятельно. Верни только корректный JSON без Markdown-ограждений с ключами:
topic, title, body.
В body включи весь готовый к публикации текст, кроме отдельного технического поля topic.
Исторические утверждения не выдумывай. Художественную историю явно обозначай как вымысел.
Заголовок должен быть первым предложением публикации и быть короче 140 символов.
"""
    raw = _generate_text(prompt).strip()
    if raw.startswith("```json"):
        raw = raw[7:]
    elif raw.startswith("```"):
        raw = raw[3:]
    if raw.endswith("```"):
        raw = raw[:-3]
    data = json.loads(raw.strip())
    for key in ("topic", "title", "body"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise ValueError(f"ИИ вернул пустое или некорректное поле: {key}")
    data["topic"] = data["topic"].strip()
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
