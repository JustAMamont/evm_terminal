import pytest
import asyncio
from unittest.mock import patch, AsyncMock, MagicMock

from bot.bot import main_loop

@pytest.mark.asyncio
async def test_main_loop_exits_when_no_networks_found():
    """
    Проверяет, что главный цикл завершается, если не найдено ни одной сети.
    """
    # Мокаем (подменяем) все внешние зависимости функции main_loop
    with patch("bot.bot.enumerate_adapters", return_value=[]) as mock_enumerate_adapters, \
         patch("bot.bot.run_bot_instance", new_callable=AsyncMock) as mock_run_bot, \
         patch("bot.bot.DatabaseManager") as mock_db, \
         patch("bot.bot.load_last_network", new_callable=AsyncMock) as mock_load_last, \
         patch("bot.bot.load_resource_bundle") as mock_load_bundle:

        # Запускаем тестируемую функцию
        await main_loop()

        # --- Проверки (Assertions) ---
        # 1. Убеждаемся, что мы действительно пытались найти сети
        mock_enumerate_adapters.assert_called_once()

        # 2. Главная проверка: убеждаемся, что запуск экземпляра бота НЕ БЫЛ вызван,
        #    потому что список сетей пуст.
        mock_run_bot.assert_not_called()

        # 3. Убеждаемся, что до логики загрузки сетей дело даже не дошло
        mock_load_last.assert_not_called()
        mock_db.assert_not_called()
        mock_load_bundle.assert_not_called()


@pytest.mark.asyncio
async def test_main_loop_runs_instance_when_networks_exist():
    """
    Проверяет, что главный цикл ПЫТАЕТСЯ запустить экземпляр бота,
    если сети были успешно найдены.
    """
    # Готовим моки для "успешного" сценария
    mock_db_instance = MagicMock()
    mock_db_instance.connect = AsyncMock()
    mock_db_instance.close = AsyncMock()

    # Мокаем зависимости
    with patch("bot.bot.enumerate_adapters", return_value=["bsc", "eth"]) as mock_enumerate_adapters, \
         patch("bot.bot.run_bot_instance", new_callable=AsyncMock) as mock_run_bot, \
         patch("bot.bot.load_resource_bundle", return_value={"db_path": "dummy.db"}) as mock_load_bundle, \
         patch("bot.bot.DatabaseManager", return_value=mock_db_instance) as mock_db_class, \
         patch("bot.bot.load_last_network", new_callable=AsyncMock, return_value="bsc") as mock_load_last:

        # Чтобы цикл while в main_loop не стал бесконечным в тесте,
        # мы делаем так, чтобы run_bot_instance вернул None (или любое False значение)
        mock_run_bot.return_value = None

        # Запускаем тестируемую функцию
        await main_loop()

        # --- Проверки (Assertions) ---
        # 1. Убеждаемся, что сети были найдены
        mock_enumerate_adapters.assert_called_once()

        # 2. Убеждаемся, что была попытка загрузить последнюю использованную сеть
        mock_load_last.assert_called_once()

        # 3. Главная проверка: убеждаемся, что функция запуска экземпляра бота БЫЛА вызвана.
        mock_run_bot.assert_called_once()
        # 4. Можно даже проверить, с какими аргументами она была вызвана
        mock_run_bot.assert_called_once_with("bsc", ["bsc", "eth"])