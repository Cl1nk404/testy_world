import asyncio
import logging
import re

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from .config import DRY_RUN, DZEN_CDP_URL, DZEN_EDITOR_URL, LOG_DIR

log = logging.getLogger("tasty_world.dzen")
TEXTBOX_SELECTOR = '[role="textbox"]'
ADD_BUTTON_SELECTOR = '[data-testid="add-publication-button"]'


def _plain_article_text(body: str) -> str:
    """Convert basic Markdown conventions to readable plain text for the Dzen editor."""
    text = body.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return text.strip()


async def _create_draft(title: str, body: str) -> dict:
    if DRY_RUN:
        log.info("DRY_RUN=true: черновик Дзена не создаётся.")
        return {"status": "dry_run", "message_id": None}

    if not DZEN_EDITOR_URL:
        raise RuntimeError("Не задан DZEN_EDITOR_URL в .env")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.connect_over_cdp(DZEN_CDP_URL)
        if not browser.contexts:
            raise RuntimeError(
                "Не найден контекст Chrome. Запустите scripts\\start_chrome.bat и войдите в Дзен."
            )

        context = browser.contexts[0]
        page = await context.new_page()
        try:
            log.info("Открываю редактор Дзена: %s", DZEN_EDITOR_URL)
            await page.goto(
                DZEN_EDITOR_URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            await page.wait_for_timeout(2500)

            current_url = page.url.lower()
            if any(part in current_url for part in (
                "passport.yandex", "oauth.yandex", "dzen.ru/login", "sso.dzen.ru"
            )) or await page.locator('input[type="password"]').count():
                raise RuntimeError(
                    "Chrome не авторизован в Дзене. Откройте окно Chrome, войдите вручную и повторите запуск."
                )

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
                    await page.locator(TEXTBOX_SELECTOR).nth(1).wait_for(
                        state="visible", timeout=25_000
                    )
                except PlaywrightTimeoutError as exc:
                    raise RuntimeError(
                        "Не удалось открыть редактор статьи. Проверьте DZEN_EDITOR_URL и интерфейс канала."
                    ) from exc

            textboxes = page.locator(TEXTBOX_SELECTOR)
            count = await textboxes.count()
            if count < 2:
                raise RuntimeError(
                    f"В редакторе найдено полей ввода: {count}, ожидалось минимум 2."
                )

            # В этой первой версии создаём черновик, но намеренно не нажимаем «Опубликовать».
            await textboxes.nth(0).fill(title, timeout=15_000)
            await textboxes.nth(1).fill(_plain_article_text(body), timeout=15_000)
            await page.wait_for_timeout(5000)

            # Дзен сохраняет черновик автоматически; ждём завершения индикатора сохранения.
            for _ in range(12):
                page_text = await page.locator("body").inner_text()
                if "Идёт сохранение" not in page_text and "Сохранение..." not in page_text:
                    break
                await page.wait_for_timeout(1000)

            draft_url = page.url
            log.info("Черновик Дзена заполнен; URL редактора: %s", draft_url)
            return {
                "status": "draft_created",
                "message_id": None,
                "url": draft_url,
            }
        except Exception:
            try:
                LOG_DIR.mkdir(parents=True, exist_ok=True)
                await page.screenshot(
                    path=str(LOG_DIR / "dzen_editor_error.png"),
                    full_page=True,
                )
                log.exception("Ошибка работы с редактором Дзена; скриншот сохранён в logs/dzen_editor_error.png")
            except Exception:
                log.exception("Ошибка работы с редактором Дзена")
            raise
        finally:
            await page.close()
            # Не закрываем browser: это Chrome пользователя, подключённый через CDP.


def publish_dzen(title: str, body: str) -> dict:
    """Create a Dzen draft using the already-authenticated Chrome session."""
    return asyncio.run(_create_draft(title, body))


if __name__ == "__main__":
    import argparse

    from .storage import connect

    parser = argparse.ArgumentParser(
        description="Create a Dzen draft from the latest locally saved article."
    )
    parser.add_argument(
        "--last-post",
        action="store_true",
        help="Use the latest article saved in SQLite; does not call GigaChat.",
    )
    args = parser.parse_args()
    if not args.last_post:
        parser.error("Укажите --last-post для безопасного теста без генерации новой статьи.")

    with connect() as conn:
        row = conn.execute(
            "SELECT title, body FROM posts "
            "WHERE body != '' AND title != 'Ошибка генерации' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()

    if row is None:
        parser.error("В SQLite нет сохранённой статьи. Сначала запустите генерацию один раз.")

    result = publish_dzen(row["title"], row["body"])
    print(result)
