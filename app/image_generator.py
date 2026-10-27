import base64
import logging
from datetime import datetime
from pathlib import Path

import requests

from .config import (
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    CLOUDFLARE_IMAGE_MODEL,
    ENABLE_IMAGE,
    IMAGE_OUTPUT_DIR,
)

log = logging.getLogger("tasty_world.image")


def generate_dish_image(title: str, body: str, run_date: str | None = None) -> Path | None:
    """Generate one recipe image with Cloudflare Workers AI. Never retries or falls back."""
    if not ENABLE_IMAGE:
        log.info("Генерация изображения выключена (ENABLE_IMAGE=false).")
        return None
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
        log.error("Изображение не создано: заполните CLOUDFLARE_ACCOUNT_ID и CLOUDFLARE_API_TOKEN в .env.")
        return None

    excerpt = " ".join(body.split())[:1400]
    prompt = (
        "Create a realistic editorial food photograph for a cooking article. "
        "Show only the finished dish described by the recipe, with plausible ingredients and preparation. "
        "Appetizing natural window light, detailed real food texture, tasteful simple table setting, "
        "45-degree camera angle, professional food photography, no people, no lettering, no text, "
        "no logo, no watermark. The image must look like a real photograph, not an illustration.\n"
        f"Article title: {title[:180]}\nRecipe context: {excerpt}"
    )[:2048]

    endpoint = (
        "https://api.cloudflare.com/client/v4/accounts/"
        f"{CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_IMAGE_MODEL}"
    )
    try:
        response = requests.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
                "Content-Type": "application/json",
            },
            json={"prompt": prompt, "steps": 4},
            timeout=(15, 150),
        )
        response.raise_for_status()
        payload = response.json()
        if not payload.get("success"):
            errors = payload.get("errors") or []
            raise RuntimeError(f"Cloudflare AI вернул success=false: {errors[:2]}")
        encoded = (payload.get("result") or {}).get("image")
        if not encoded:
            raise RuntimeError("Cloudflare AI не вернул result.image")
        image_bytes = base64.b64decode(encoded, validate=True)
        if not image_bytes:
            raise RuntimeError("Cloudflare AI вернул пустое изображение")

        IMAGE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        date_part = run_date or datetime.now().date().isoformat()
        path = IMAGE_OUTPUT_DIR / f"{date_part}.png"
        path.write_bytes(image_bytes)
        log.info("Изображение блюда сохранено: %s (%s байт)", path, len(image_bytes))
        return path
    except Exception as exc:
        # No retry and no stock-photo fallback by design.
        log.error("Не удалось сгенерировать изображение; публикация продолжится без него: %s", exc)
        return None
