import os
import logging
import json  # Импортируем json для работы с файлами JSON
from flask import Flask, jsonify
from slack_sdk import WebClient
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.errors import SlackApiError
from telegram import Bot
from dotenv import load_dotenv
import asyncio
import sys
import io
from collections import deque

# Загрузка переменных окружения
load_dotenv()

# Flask приложение
app = Flask(__name__)

class SlackTelegramBot:
    def __init__(self):
        # Настройки Slack и Telegram из переменных окружения
        self.slack_user_token = os.getenv('SLACK_USER_TOKEN')
        self.slack_app_token = os.getenv('SLACK_APP_TOKEN')
        self.telegram_bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID')

        # Инициализация клиентов для Slack и Telegram
        self.slack_client = WebClient(token=self.slack_user_token)
        self.socket_client = SocketModeClient(app_token=self.slack_app_token, web_client=self.slack_client)
        self.telegram_bot = Bot(token=self.telegram_bot_token)

        # Получение вашего Slack User ID
        self.user_id = self.get_user_id()

        # Очередь событий для обработки
        self.event_queue = deque()

        # Набор для хранения уже обработанных событий
        self.processed_events = set()

        # Подключение обработчиков Socket Mode
        self.socket_client.socket_mode_request_listeners.append(self.socket_mode_event_handler)

        # Загрузка эмодзи из JSON-файла
        self.channel_emojis = self.load_channel_emojis('channel_emojis.json')

    def load_channel_emojis(self, file_path):
        """Загрузка эмодзи из JSON-файла."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logging.error(f"Ошибка при загрузке эмодзи из файла: {e}")
            return {}

    def get_user_id(self):
        """Получение идентификатора пользователя Slack."""
        try:
            response = self.slack_client.auth_test()
            return response["user_id"]
        except SlackApiError as e:
            logging.error(f"Ошибка при получении User ID: {e.response['error']}")
            return None

    async def process_event_queue(self):
        """Асинхронная обработка очереди событий."""
        while True:
            if self.event_queue:
                event_data = self.event_queue.popleft()  # Получаем первое событие из очереди
                await self.process_message(event_data)
            await asyncio.sleep(1)  # Добавляем паузу, чтобы избежать излишней нагрузки на процессор

    async def process_message(self, event_data):
        """Обработка сообщений Slack и отправка уведомлений в Telegram."""
        logging.info("Обрабатываем событие: %s", event_data)
        event = event_data.get('event', {})

        if event.get('type') == 'message' and 'text' in event:
            text = event['text']
            user_id = event.get('user')
            channel_id = event.get('channel')

            if user_id:
                if f"<@{self.user_id}>" in text:
                    try:
                        # Получаем информацию о пользователе и канале
                        user_info = self.slack_client.users_info(user=user_id)
                        channel_info = self.slack_client.conversations_info(channel=channel_id)

                        user_name = user_info['user']['real_name']
                        channel_name = channel_info['channel']['name']

                        # Добавляем эмодзи к названию канала, если оно есть в словаре
                        channel_name_with_emoji = f"{channel_name} {self.channel_emojis.get(channel_name, '')}"

                        logging.info(f"Упоминание найдено в сообщении: {text}")

                        message = f"Канал: {channel_name_with_emoji}, Пользователь: {user_name}, Сообщение: {text}"
                        try:
                            await self.telegram_bot.send_message(chat_id=self.telegram_chat_id, text=message)
                            logging.info(f"Отправлено сообщение в Telegram: {message}")
                        except Exception as e:
                            logging.error(f"Ошибка при отправке сообщения в Telegram: {e}")
                    except SlackApiError as e:
                        logging.error(f"Ошибка при получении информации из Slack: {e.response['error']}")
            else:
                logging.info("Сообщение не содержит информации о пользователе.")

    def socket_mode_event_handler(self, client: SocketModeClient, req: SocketModeRequest):
        """Обработка событий через Socket Mode."""
        event = req.payload['event']
        event_id = event.get('client_msg_id')  # Уникальный идентификатор сообщения

        # Проверяем, было ли уже обработано это событие
        if event_id and event_id not in self.processed_events:
            self.event_queue.append(req.payload)  # Сохраняем событие в очередь
            self.processed_events.add(event_id)  # Добавляем событие в набор обработанных
        else:
            logging.info("Событие уже было обработано: %s", event_id)

        return SocketModeResponse(envelope_id=req.envelope_id)

    def start(self):
        """Запуск Socket Mode клиента и асинхронного обработчика."""
        logging.info("Запуск Socket Mode клиента...")
        self.socket_client.connect()

        # Запуск асинхронного цикла для обработки событий
        loop = asyncio.get_event_loop()
        loop.create_task(self.process_event_queue())
        loop.run_forever()

# Инициализация SlackTelegramBot
bot = SlackTelegramBot()

# Обработка Slack событий через Flask
@app.route("/slack/events", methods=["POST"])
def slack_events():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    # Настройка логирования для записи в файл
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        filename='app.log',  # Имя файла для логирования
        filemode='a',  # 'a' - добавление в конец файла, 'w' - перезапись файла
        encoding='utf-8'
    )

    # Запуск Slack Socket Mode клиента
    bot.start()

    # Запуск Flask сервера
    app.run(port=3000)
