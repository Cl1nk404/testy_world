import asyncio
import logging
import re
from pathlib import Path

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from .config import DRY_RUN, DZEN_CDP_URL, DZEN_EDITOR_URL, LOG_DIR

log = logging.getLogger("tasty_world.dzen")
TEXTBOX_SELECTOR = '[role="textbox"]'
ADD_BUTTON_SELECTOR = '[data-testid="add-publication-button"]'
IMAGE_BUTTON_PATTERN = re.compile(r"изображ|фото|картин|image|photo", re.IGNORECASE)


def _plain_article_text(body: str) -> str:
    """Convert basic Markdown conventions to readable plain text for the Dzen editor."""
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


async def _insert_image_into_empty_body(page, image_path: Path) -> bool:
    """Insert the image while the article body is still empty, when Dzen exposes its image controls."""
    body_box = page.locator(TEXTBOX_SELECTOR).nth(1)
    try:
        # Dzen may expose the image control only for an active, empty paragraph.
        await body_box.click(timeout=10_000)
        await page.wait_for_timeout(500)

        buttons = page.get_by_role("button", name=IMAGE_BUTTON_PATTERN)
        visible_button = None
        for i in range(await buttons.count()):
            candidate = buttons.nth(i)
            try:
                if await candidate.is_visible():
                    visible_button = candidate
                    break
            except Exception:
                continue

        if visible_button is None:
            for label in ("Добавить изображение", "Загрузить изображение", "Изображение", "Фото"):
                candidate = page.get_by_text(label, exact=True)
                if await candidate.count() and await candidate.first.is_visible():
                    visible_button = candidate.first
                    break

        if visible_button is not None:
            async with page.expect_file_chooser(timeout=10_000) as chooser_info:
                await visible_button.click(timeout=10_000)
            chooser = await chooser_info.value
            await chooser.set_files(str(image_path))
            await page.wait_for_timeout(2500)
            log.info("Изображение добавлено через кнопку пустого блока: %s", image_path.name)
            return True

        # Some editor versions expose a file input without a consistently named button.
        file_inputs = page.locator('input[type="file"]')
        for i in range(await file_inputs.count()):
            file_input = file_inputs.nth(i)
            try:
                await file_input.set_input_files(str(image_path), timeout=5_000)
                await page.wait_for_timeout(2500)
                log.info("Изображение передано через input[type=file]: %s", image_path.name)
                return True
            except Exception:
                continue

        log.error("Не найдена кнопка загрузки изображения в пустом блоке; пробовал также input[type=file].")
        return False
    except Exception as exc:
        log.error("Не удалось вставить изображение в пустой блок статьи: %s", exc)
        return False


async def _create_draft(title: str, body: str, image_path: Path | None = None) -> dict:
    if DRY_RUN:
        log.info("DRY_RUN=true: черновик Дзена не создаётся.")
        return {"status": "dry_run", "message_id": None}
    if not DZEN_EDITOR_URL:
        raise RuntimeError("Не задан DZEN_EDITOR_URL в .env")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(DZEN_CDP_URL)
        if not browser.contexts:
            raise RuntimeError("Не найден контекст Chrome. Запустите scripts\\start_chrome.bat и войдите в Дзен.")
        context = browser.contexts[0]
        page = await context.new_page()
        try:
            log.info("Открываю редактор Дзена: %s", DZEN_EDITOR_URL)
            await page.goto(DZEN_EDITOR_URL, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(2500)
            current_url = page.url.lower()
            if any(part in current_url for part in (
                "passport.yandex", "oauth.yandex", "dzen.ru/login", "sso.dzen.ru"
            )) or await page.locator('input[type="password"]').count():
                raise RuntimeError("Chrome не авторизован в Дзене. Войдите вручную и повторите запуск.")

            textboxes = page.locator(TEXTBOX_SELECTOR)
            if await textboxes.count() < 2:
                add_button = page.locator(ADD_BUTTON_SELECTOR)
                if await add_button.count() and await add_button.first.is_visible():
                    await add_button.first.click()
                    await page.get_by_text("Написать статью", exact=True).click(timeout=10_000)
                else:
                    article_link = page.get_by_text("Написать статью", exact=True)
                    if await article_link.count() and await article_link.first.is_visible():
                        await article_link.first.click(timeout=10_000)
                try:
                    await page.locator(TEXTBOX_SELECTOR).nth(1).wait_for(state="visible", timeout=25_000)
                except PlaywrightTimeoutError as exc:
                    raise RuntimeError("Не удалось открыть редактор статьи. Проверьте DZEN_EDITOR_URL и интерфейс канала.") from exc

            textboxes = page.locator(TEXTBOX_SELECTOR)
            if await textboxes.count() < 2:
                raise RuntimeError(f"В редакторе найдено полей ввода: {await textboxes.count()}, ожидалось минимум 2.")

            await textboxes.nth(0).fill(title, timeout=15_000)
            article_text = _plain_article_text(body)
            image_inserted = False
            if image_path and image_path.exists():
                # Important: attempt image insertion before typing body text. In Dzen the image
                # control may only appear when the current paragraph is empty.
                image_inserted = await _insert_image_into_empty_body(page, image_path)
            elif image_path:
                log.error("Файл изображения не найден: %s; продолжаю без изображения.", image_path)

            body_box = page.locator(TEXTBOX_SELECTOR).nth(1)
            if image_inserted:
                # Do not call fill() after image insertion: it can replace the editor contents,
                # including the uploaded image. Type into the body after the inserted image.
                await body_box.click(timeout=10_000)
                await page.keyboard.press("Control+End")
                await page.keyboard.insert_text(article_text)
            else:
                await body_box.fill(article_text, timeout=15_000)

            await page.wait_for_timeout(5000)
            for _ in range(12):
                page_text = await page.locator("body").inner_text()
                if "Идёт сохранение" not in page_text and "Сохранение..." not in page_text:
                    break
                await page.wait_for_timeout(1000)
            draft_url = page.url
            log.info("Черновик Дзена заполнен; URL редактора: %s", draft_url)
            return {"status": "draft_created", "message_id": None, "url": draft_url}
        except Exception:
            try:
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(LOG_DIR / "dzen_editor_error.png"), full_page=True)
                log.exception("Ошибка редактора Дзена; скриншот сохранён в logs/dzen_editor_error.png")
            except Exception:
                log.exception("Ошибка работы с редактором Дзена")
            raise
        finally:
            await page.close()


def publish_dzen(title: str, body: str, image_path: Path | None = None) -> dict:
    """Create a Dzen draft using the already-authenticated Chrome session."""
    return asyncio.run(_create_draft(title, body, image_path))


if __name__ == "__main__":
    import argparse
    from .storage import connect

    parser = argparse.ArgumentParser(description="Create a Dzen draft from the latest locally saved article.")
    parser.add_argument("--last-post", action="store_true", help="Use latest saved article; does not call GigaChat.")
    parser.add_argument("--with-image", action="store_true", help="Generate one image via Cloudflare and insert it before the text.")
    args = parser.parse_args()
    if not args.last_post:
        parser.error("Укажите --last-post для безопасного теста без генерации новой статьи.")
    if args.with_image and DRY_RUN:
        parser.error("Для теста редактора с изображением установите DRY_RUN=false в .env; иначе браузер не откроется.")
    with connect() as conn:
        row = conn.execute(
            "SELECT title, body FROM posts WHERE body != '' AND title != 'Ошибка генерации' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        parser.error("В SQLite нет сохранённой статьи. Сначала запустите генерацию один раз.")
    image_path = None
    if args.with_image:
        from .image_generator import generate_dish_image
        from .config import TIMEZONE
        from datetime import datetime
        from zoneinfo import ZoneInfo
        run_date = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
        image_path = generate_dish_image(row["title"], row["body"], run_date)
    result = publish_dzen(row["title"], row["body"], image_path=image_path)
    print(result)
