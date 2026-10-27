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
    """Open the image popup using Dzen's side-toolbar button, then upload its file input."""
    body_box = page.locator(TEXTBOX_SELECTOR).nth(1)
    try:
        await body_box.click(timeout=10_000)
        await page.wait_for_timeout(300)

        # Dzen renders this toolbar button beside the active empty paragraph.
        toolbar_button = page.locator(
            'button[data-tip="Вставить изображение"]'
        ).last
        if not await toolbar_button.count() or not await toolbar_button.is_visible():
            # Fallback to the icon's SVG use reference from the supplied DOM.
            toolbar_button = page.locator(
                'button:has(svg use[href="#add_gallery_e477--react"]), '
                'button:has(svg use[xlink\\:href="#add_gallery_e477--react"])'
            ).last

        if not await toolbar_button.count() or not await toolbar_button.is_visible():
            log.error("Не найдена кнопка Дзена button[data-tip='Вставить изображение'] рядом с пустым блоком.")
            return False

        await toolbar_button.click(timeout=10_000)

        # The modal markup supplied by the user exposes a dedicated file input.
        file_input_selector = (
            'input.article-editor-desktop--image-popup__fileInput-35, '
            'input[type="file"][accept*="image/png"]'
        )
        file_input = page.locator(file_input_selector).last
        await file_input.wait_for(state="attached", timeout=10_000)
        await file_input.set_input_files(str(image_path), timeout=10_000)
        await page.wait_for_timeout(3000)

        # Verify that the modal closed or an image node appeared before reporting success.
        modal = page.locator('[class*="image-popup__imagePopup"]')
        image_nodes = page.locator('[contenteditable="true"] img, [role="textbox"] img')
        if await modal.count() and await modal.last.is_visible():
            log.warning("Поле файла приняло изображение, но окно загрузки Дзена ещё открыто.")
        log.info(
            "Файл передан в окно изображения Дзена: %s (видимых изображений в редакторе: %s)",
            image_path.name, await image_nodes.count()
        )
        return True
    except Exception as exc:
        log.error("Не удалось загрузить изображение через панель Дзена: %s", exc)
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
