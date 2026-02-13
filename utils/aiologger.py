import aiofiles
import asyncio
import platform
from datetime import datetime, timedelta
from pathlib import Path
import traceback
from enum import IntEnum
from typing import Optional, Any, cast, Callable, Awaitable
import re
import os

class LogLevel(IntEnum):
    DEBUG = 10
    INFO = 20
    SUCCESS = 25
    WARNING = 30
    ERROR = 40
    CRITICAL = 50

LogHandlerCallable = Callable[[str, LogLevel, str, datetime], Awaitable[None]]


class AsyncLogger:
    _instances: dict[str, 'AsyncLogger'] = {}
    _lock = asyncio.Lock()


    @staticmethod
    async def get_logger(
        log_file_path: str = "logs/app.log", 
        level: LogLevel = LogLevel.DEBUG,
        custom_handler: Optional[LogHandlerCallable] = None 
    ) -> 'AsyncLogger':
        async with AsyncLogger._lock:
            if log_file_path not in AsyncLogger._instances:
                instance = AsyncLogger(log_file_path, level, custom_handler)
                await instance._initialize()
                AsyncLogger._instances[log_file_path] = instance
            return AsyncLogger._instances[log_file_path]


    def __init__(self, path_template: str, level: LogLevel, custom_handler: Optional[LogHandlerCallable]):
        self.path_template = path_template
        self.level = level
        self.custom_handler = custom_handler
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task[None]] = None
        self._current_log_path: Optional[Path] = None
        
        if platform.system() == 'Windows':
            self._init_windows_colors()


    async def _initialize(self):
        # Сначала запускаем очистку старых логов
        await self._cleanup_old_logs()
        
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._log_writer())


    async def _cleanup_old_logs(self):
        """Удаляет лог-файлы старше 7 дней в фоновом режиме."""
        try:
            # Определяем папку с логами из шаблона
            # Если шаблон 'logs/{date}.log', то папка 'logs'
            template_path = Path(self.path_template)
            log_dir = template_path.parent
            
            # Если папки еще нет, чистить нечего
            if not log_dir.exists():
                return

            retention_days = 7
            cutoff_time = datetime.now() - timedelta(days=retention_days)
            cutoff_timestamp = cutoff_time.timestamp()

            def sync_cleanup():
                # Ищем все файлы в директории (предполагаем, что там только логи или .log файлы)
                # Если шаблон имеет расширение, фильтруем по нему
                extension = template_path.suffix or ".log"
                
                for file_path in log_dir.glob(f"*{extension}"):
                    try:
                        if file_path.is_file():
                            # Проверяем время последней модификации
                            if file_path.stat().st_mtime < cutoff_timestamp:
                                file_path.unlink() # Удаляем файл
                                # print(f"Deleted old log: {file_path}") # Можно раскомментировать для отладки
                    except Exception:
                        pass # Игнорируем ошибки доступа к конкретным файлам

            # Запускаем в отдельном потоке, чтобы не блокировать event loop при большом кол-ве файлов
            await asyncio.to_thread(sync_cleanup)
            
        except Exception as e:
            print(f"[WARN] Failed to cleanup old logs: {e}")


    def _init_windows_colors(self):
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32 # type: ignore
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7) 
        except Exception:
            pass


    def _get_color_code(self, level_name: str, custom_color: Optional[str] = None):
        colors = {
            'black': '\033[30m', 'red': '\033[31m', 'green': '\033[32m',
            'yellow': '\033[33m', 'blue': '\033[34m', 'magenta': '\033[35m',
            'cyan': '\033[36m', 'white': '\033[37m', 'reset': '\033[0m'
        }
        level_colors = {
            'DEBUG': colors['cyan'], 'INFO': colors['blue'], 'WARNING': colors['yellow'],
            'ERROR': colors['red'], 'CRITICAL': '\033[41m', 'SUCCESS': colors['green'],
        }
        if custom_color:
            return colors.get(custom_color.lower(), '')
        return level_colors.get(level_name, colors['reset'])


    def _get_log_path(self, dt: datetime) -> Path:
        date_str = dt.strftime('%Y-%m-%d')
        path_str = self.path_template.format(date=date_str) 
        return Path(path_str)


    def _colorize_message(self, message: str) -> str:
        def replace_tag(match: re.Match) -> str:
            color_name = match.group(1)
            text = match.group(2)
            color_code = self._get_color_code('', custom_color=color_name)
            reset_code = self._get_color_code('', custom_color='reset')
            return f"{color_code}{text}{reset_code}" if color_code else text

        pattern = re.compile(r"<(\w+)>(.*?)</\1>")
        return pattern.sub(replace_tag, message)
    

    async def _log_writer(self):
        while True:
            try:
                log_record = await self._queue.get()
                if log_record is None:
                    self._queue.task_done()
                    break

                dt, level, message_str, to_console, to_file = log_record

                dt_str = dt.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3] 
                level_name = level.name

                if self.custom_handler:
                    try:
                        await self.custom_handler(dt_str, level, message_str, dt)
                    except Exception as handler_e:
                        print(f"CRITICAL - Error in custom log handler: {handler_e}", flush=True)

                if to_console:
                    level_color = self._get_color_code(level_name)
                    reset = self._get_color_code('', custom_color='reset')
                    colored_message = self._colorize_message(message_str)
                    print(f"{dt_str} - {level_color}[{level_name}]{reset} - {colored_message}")

                if to_file:
                    log_path = self._get_log_path(dt)
                    
                    if self._current_log_path != log_path:
                        log_path.parent.mkdir(parents=True, exist_ok=True)
                        self._current_log_path = log_path

                    clean_message = re.sub(r"<(\w+)>(.*?)</\1>", r"\2", message_str)

                    async with aiofiles.open(log_path, mode='a', encoding='utf-8') as f:
                        await f.write(f"{dt_str} - {level_name} - {clean_message}\n")
                
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"CRITICAL - Error in logger worker: {e} - Original record: {log_record}", flush=True) # type: ignore


    async def _write(self, level: LogLevel, message: Any, to_console: bool, to_file: bool, exc_info: bool):
        if level < self.level:
            return

        dt = datetime.now()
        message_str = str(message)
        if exc_info:
            message_str += "\n" + traceback.format_exc()

        log_record = (dt, level, message_str, to_console, to_file)
        await self._queue.put(log_record)

    async def debug(self, message: Any, to_console: bool = True, to_file: bool = True, exc_info: bool = False) -> None:
        await self._write(LogLevel.DEBUG, message, to_console, to_file, exc_info)

    async def info(self, message: Any, to_console: bool = True, to_file: bool = True, exc_info: bool = False) -> None:
        await self._write(LogLevel.INFO, message, to_console, to_file, exc_info)

    async def success(self, message: Any, to_console: bool = True, to_file: bool = True, exc_info: bool = False) -> None:
        await self._write(LogLevel.SUCCESS, message, to_console, to_file, exc_info)
        
    async def warning(self, message: Any, to_console: bool = True, to_file: bool = True, exc_info: bool = False) -> None:
        await self._write(LogLevel.WARNING, message, to_console, to_file, exc_info)

    async def error(self, message: Any, to_console: bool = True, to_file: bool = True, exc_info: bool = False) -> None:
        await self._write(LogLevel.ERROR, message, to_console, to_file, exc_info)

    async def critical(self, message: Any, to_console: bool = True, to_file: bool = True, exc_info: bool = False) -> None:
        await self._write(LogLevel.CRITICAL, message, to_console, to_file, exc_info)

    async def shutdown(self) -> None:
        await self._queue.put(None) 
        await self._queue.join() 

        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        
        AsyncLogger._instances.clear()


class LoggerProxy:
    def __init__(self, path_template: str, level: LogLevel, custom_handler: Optional[LogHandlerCallable] = None):
        self._real_logger: Optional[AsyncLogger] = None
        self._init_lock = asyncio.Lock()
        self._path_template = path_template
        self._level = level
        self._custom_handler = custom_handler

    async def _ensure_initialized(self):
        if self._real_logger is None:
            async with self._init_lock:
                if self._real_logger is None:
                    self._real_logger = await AsyncLogger.get_logger(
                        self._path_template, self._level, self._custom_handler
                    )
    
    async def set_custom_handler(self, handler: LogHandlerCallable) -> None:
        await self._ensure_initialized()
        cast(AsyncLogger, self._real_logger).custom_handler = handler

    async def debug(self, message: Any, to_console: bool = True, to_file: bool = False, exc_info: bool = False) -> None:
        await self._ensure_initialized()
        await cast(AsyncLogger, self._real_logger).debug(message, to_console, to_file, exc_info)

    async def info(self, message: Any, to_console: bool = True, to_file: bool = True, exc_info: bool = False) -> None:
        await self._ensure_initialized()
        await cast(AsyncLogger, self._real_logger).info(message, to_console, to_file, exc_info)

    async def success(self, message: Any, to_console: bool = True, to_file: bool = True, exc_info: bool = False) -> None:
        await self._ensure_initialized()
        await cast(AsyncLogger, self._real_logger).success(message, to_console, to_file, exc_info)
        
    async def warning(self, message: Any, to_console: bool = True, to_file: bool = True, exc_info: bool = False) -> None:
        await self._ensure_initialized()
        await cast(AsyncLogger, self._real_logger).warning(message, to_console, to_file, exc_info)

    async def error(self, message: Any, to_console: bool = True, to_file: bool = True, exc_info: bool = False) -> None:
        await self._ensure_initialized()
        await cast(AsyncLogger, self._real_logger).error(message, to_console, to_file, exc_info)

    async def critical(self, message: Any, to_console: bool = True, to_file: bool = True, exc_info: bool = False) -> None:
        await self._ensure_initialized()
        await cast(AsyncLogger, self._real_logger).critical(message, to_console, to_file, exc_info)

    async def shutdown(self) -> None:
        if self._real_logger:
            await self._real_logger.shutdown()
        else:
            pass

log: LoggerProxy = LoggerProxy(path_template='logs/{date}.log', level=LogLevel.INFO)