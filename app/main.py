import argparse
import logging
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.blocking import BlockingScheduler
from .config import TIMEZONE, POST_HOUR, POST_MINUTE, LOG_DIR, OUTPUT_DIR, DRY_RUN
from .storage import init_db, topics_used, already_ran, save_post
from .ai_generator import generate_post, validate_post
from .publisher import publish

LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "service.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger("tasty_world")

def run_once(force=False):
    init_db()
    now = datetime.now(ZoneInfo(TIMEZONE))
    log.info("Начинаю запуск за %s. DRY_RUN=%s", now.date().isoformat(), DRY_RUN)
    run_date = now.date().isoformat()
    if already_ran(run_date) and not force:
        log.info("На %s запись уже существует; повторный запуск пропущен.", run_date)
        return
    try:
        log.info("Запрашиваю генерацию статьи у GigaChat...")
        post = generate_post(now.date(), topics_used())
        log.info("GigaChat вернул статью: %s", post.get("title", "без заголовка"))
        issues = validate_post(post)
        if issues:
            raise ValueError("Проверка качества не пройдена: " + "; ".join(issues))
        out = OUTPUT_DIR / f"{run_date}.md"
        out.write_text(post["body"].rstrip() + "\n", encoding="utf-8")
        result = publish(post["title"], post["body"])
        save_post(run_date, post["topic"], post["title"], post["body"], result["status"], result.get("message_id"))
        log.info("Готово. Тема=%r, статус=%s, файл=%s", post["topic"], result["status"], out)
    except Exception as exc:
        log.exception("Ежедневный запуск завершился ошибкой")
        save_post(run_date, "не определена", "Ошибка генерации", "", "error", error=str(exc))

def main():
    parser = argparse.ArgumentParser(description="Вкусные истории мира — MVP")
    parser.add_argument("--once", action="store_true", help="Выполнить один запуск сейчас")
    parser.add_argument("--force", action="store_true", help="Разрешить повторный запуск за сегодня")
    args = parser.parse_args()
    init_db()
    log.info("Сервис стартовал. Команда: once=%s, force=%s; timezone=%s", args.once, args.force, TIMEZONE)
    if args.once:
        run_once(force=args.force)
        return
    scheduler = BlockingScheduler(timezone=TIMEZONE)
    scheduler.add_job(run_once, "cron", hour=POST_HOUR, minute=POST_MINUTE, id="daily_recipe", max_instances=1, coalesce=True, misfire_grace_time=3600)
    log.info("Планировщик запущен: ежедневно в %02d:%02d (%s). DRY_RUN=%s", POST_HOUR, POST_MINUTE, TIMEZONE, DRY_RUN)
    scheduler.start()


if __name__ == "__main__":
    main()
