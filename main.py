import sqlite3
import requests
import os
from dotenv import load_dotenv
from datetime import datetime
from binance.client import Client
from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import ParseMode, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters import Command, Text
from aiogram.dispatcher.filters.state import State, StatesGroup

load_dotenv()
api_token = os.getenv('API_TOKEN')
bot = Bot(token=api_token)

storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

AV_API = os.getenv('AV_API_KEY')
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_API_SECRET = os.getenv('BINANCE_API_SECRET')

# Инициализация Binance API клиента
client = Client(BINANCE_API_KEY, BINANCE_API_SECRET)

# Подключаемся к базе данных SQLite
conn = sqlite3.connect('./app_data/database.db')
cursor = conn.cursor()

# Создаем таблицы, если они не существуют
cursor.execute('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS portfolio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    asset_name TEXT,
    amount REAL,
    asset_type TEXT, -- 'currency', 'crypto', 'stock'
    FOREIGN KEY (user_id) REFERENCES users (user_id)
)
''')
conn.commit()

# Создаем клавиатуру с кнопками
def main_menu_keyboard():
    keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
    # Первая линия кнопок
    keyboard.add(KeyboardButton('Портфель'), KeyboardButton('Добавить актив'))
    # Вторая линия кнопок
    keyboard.row(
        KeyboardButton('💵Валюта'),
        KeyboardButton('💸Крипто'),
        KeyboardButton('📈Акции')
    )
    return keyboard

# Inline-клавиатура для выбора типа актива кнопки в одну строку метод row() вместо add()
def asset_type_inline_keyboard():
    inline_kb = InlineKeyboardMarkup()
    # Добавляем кнопки в одну строку 
    inline_kb.row(
        InlineKeyboardButton("💸Крипто", callback_data='crypto'),
        InlineKeyboardButton("💵Валюта", callback_data='currency'),
        InlineKeyboardButton("📈Акции", callback_data='stock')
    )
    return inline_kb

# Определение состояний
class CurrencyState(StatesGroup):
    waiting_for_asset = State()
    response = State()
class PriceState(StatesGroup):
    waiting_for_asset = State()
class StockState(StatesGroup):
    waiting_for_asset = State()
class Portfolio(StatesGroup):
    waiting_for_asset_type = State()  # Состояние ожидания типа актива
    waiting_for_asset_ticker = State()  # Состояние ожидания тикера
    waiting_for_amount = State()  # Состояние ожидания количества

# Обработка нажатий на Inline-кнопки для выбора актива
@dp.callback_query_handler(lambda c: c.data in ['crypto', 'currency', 'stock'], state=Portfolio.waiting_for_asset_type)
async def process_asset_choice(callback_query: types.CallbackQuery, state: FSMContext):
    asset_type = callback_query.data
    await state.update_data(asset_type=asset_type)
    await callback_query.message.answer(f"Вы выбрали: {asset_type.capitalize()}. Введите тикер актива например: BTC, USD, IBM")
    await callback_query.answer()
    await Portfolio.waiting_for_asset_ticker.set()

# Функция для получения курса валюты
def get_currency_rate(currency: str):
    response = requests.get('https://www.cbr-xml-daily.ru/daily_json.js')
    return response.json()['Valute']

# Функция для получения курса криптовалюты
def get_crypto_rate(crypto: str):
    crypto = crypto+'USDT'
    try:
        response = client.get_symbol_ticker(symbol=crypto)
        # Извлекаем цену из ответа
        price = response.get('price')
        if price:
            return float(price)  # Преобразуем строку в число с плавающей запятой
        else:
            return "Криптовалюта не найдена."
    except Exception as e:
        return str(e)
    
# Функция для получения курса акций
def get_stock_rate(stock: str):
    try:
        # Используем API, например, Alpha Vantage
        response = requests.get(f'https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={stock}&apikey=P{AV_API}')
        data = response.json()
        # Проверяем, что в ответе есть нужные данные
        if "Time Series (Daily)" in data:
            time_series = data['Time Series (Daily)']
            # Получаем последнюю временную метку (это будет самая актуальная цена)
            latest_time = sorted(time_series.keys(), reverse=True)[0]
            # Извлекаем цену открытия для этой метки
            return time_series[latest_time]['4. close']
        else:
            return "Ошибка: данные не содержат 'Time Series (Daily)'"
    except Exception as e:
        return str(e)

# Команда для старта
@dp.message_handler(commands=['start'])
async def start(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)', (user_id, username))
    conn.commit()
    await message.reply(
        "Добро пожаловать! Я помогу вам отслеживать курсы валют, криптовалют и акций.",
        reply_markup=main_menu_keyboard()  # Отправляем клавиатуру при старте
    )

# Команда /help для справки
@dp.message_handler(commands=['help'])
async def help_command(message: types.Message):
    help_text = ('Добро пожаловать! Я помогу вам отслеживать курсы валют, криптовалют и акций.')
    await message.reply(help_text, reply_markup=main_menu_keyboard())  # Отправляем клавиатуру с командой /help

# Команда для получения курса валюты
@dp.message_handler(Text(equals="💵Валюта", ignore_case=True))
async def currency_command(message: types.Message):
    await message.reply("Введите тикер валюты (например, USD, EUR, CNY):")
    await CurrencyState.waiting_for_asset.set()  # Устанавливаем состояние ожидания ввода тикера

@dp.message_handler(state=CurrencyState.waiting_for_asset)
async def crypto_command(message: types.Message, state: FSMContext):
    ticker = message.text.strip().upper()
    rates = get_currency_rate(ticker)
    if ticker in rates:
        value = rates[ticker]['Value']
        name = rates[ticker]['Name']
        nominal = rates[ticker]['Nominal']
        await message.reply(f"Курс {ticker}: {value} Рублей за {nominal} {name}")
    else:
        await message.reply("Ошибка: неверный тикер. Попробуйте снова.")
    
    await state.finish()  # Завершение состояния

# Команда для получения курса криптовалюты
@dp.message_handler(Text(equals="💸Крипто", ignore_case=True))
async def start_crypto_process(message: types.Message, state: FSMContext):
    await message.reply("Пожалуйста, введите тикер актива, например: btcusdt")
    await PriceState.waiting_for_asset.set()  # Устанавливаем состояние ожидания ввода тикера

# Обрабатываем ввод тикера от пользователя
@dp.message_handler(state=PriceState.waiting_for_asset)
async def crypto_command(message: types.Message, state: FSMContext):
    # Получаем тикер из текста сообщения
    crypto = message.text.strip().upper()
    rate = get_crypto_rate(crypto)  # Предполагается, что эта функция возвращает курс
    if isinstance(rate, float):
        await message.reply(f"Курс {crypto.upper()}: {rate}")
    else:
        await message.reply(f"Ошибка при получении курса криптовалюты: {rate}")
    await state.finish()  # Завершаем состояние после обработки тикера

# Команда для получения курса акций
@dp.message_handler(Text(equals="📈Акции", ignore_case=True))
async def start_price_process(message: types.Message, state: FSMContext):
    await message.reply("Пожалуйста, введите тикер актива, например: ibm")
    await StockState.waiting_for_asset.set()  # Устанавливаем состояние ожидания ввода тикера

@dp.message_handler(state=StockState.waiting_for_asset)
async def stock_command(message: types.Message, state: FSMContext):
    stock = message.text.strip().upper()
    rate = get_stock_rate(stock)
    if rate:
        await message.reply(f"Курс акции {stock}: {rate} USD")
    else:
        await message.reply(f"Ошибка при получении курса акций.")
    await state.finish()  # Завершаем состояние после обработки тикера

# Команда для добавления актива в портфолио
@dp.message_handler(Text(equals="Добавить актив", ignore_case=True))
async def add_to_portfolio(message: types.Message, state: FSMContext):
    await state.set_state(Portfolio.waiting_for_asset_type)
    await message.answer("Выберите тип актива для добавления:", reply_markup=asset_type_inline_keyboard())
    # await Portfolio.waiting_for_asset_type.set()  # Устанавливаем состояние ожидания выбора типа актива

# Обрабатываем выбор типа актива
@dp.message_handler(Text(equals=["Крипто", "💵Валюта", "Акции"], ignore_case=True), state=Portfolio.waiting_for_asset_type)
async def process_asset_type(message: types.Message, state: FSMContext):
    asset_type = message.text.lower()
    await state.update_data(asset_type=asset_type)  # Сохраняем тип актива
    await message.reply(f"Вы выбрали {asset_type}. Пожалуйста, введите тикер актива:")
    await state.set_state(Portfolio.waiting_for_asset_ticker)  # Переходим к следующему состоянию для ввода тикера

# Обрабатываем ввод тикера
@dp.message_handler(state=Portfolio.waiting_for_asset_ticker)
async def process_asset_ticker(message: types.Message, state: FSMContext):
    asset_ticker = message.text.upper()
    await state.update_data(asset_ticker=asset_ticker)  # Сохраняем тикер актива
    await message.reply(f"Вы выбрали {asset_ticker}. Пожалуйста, введите количество, например: 10.5")
    await Portfolio.waiting_for_amount.set()  # Переходим к следующему состоянию для ввода количества

# Обрабатываем ввод количества
@dp.message_handler(state=Portfolio.waiting_for_amount)
async def process_asset_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        user_data = await state.get_data()
        asset_type = user_data['asset_type']
        asset_ticker = user_data['asset_ticker']
        user_id = message.from_user.id

        # Проверка наличия актива
        asset_exists = False
        current_price = None

        if asset_type == 'crypto':
            current_price = get_crypto_rate(asset_ticker)
            if isinstance(current_price, float):
                asset_exists = True
        elif asset_type == 'currency':
            rates = get_currency_rate(asset_ticker)
            if asset_ticker in rates:
                asset_info = rates[asset_ticker]
                nominal = asset_info['Nominal']
                current_price = asset_info['Value'] / nominal
                asset_exists = True
        elif asset_type == 'stock':
            current_price = get_stock_rate(asset_ticker)
            if isinstance(current_price, str) and current_price.startswith("Ошибка"):
                asset_exists = False
            else:
                asset_exists = True
        
        # Если актив не существует, сообщаем об этом пользователю
        if not asset_exists:
            await message.reply(f"Актив {asset_ticker} не найден. Пожалуйста, проверьте корректность тикера.")
            await state.finish()
            return

        # Проверка, существует ли уже запись с таким активом для пользователя
        cursor.execute('''
            SELECT amount FROM portfolio
            WHERE user_id = ? AND asset_name = ? AND asset_type = ?
        ''', (user_id, asset_ticker, asset_type))
        result = cursor.fetchone()

        if result:
            # Если актив уже существует, обновляем количество
            new_amount = result[0] + amount
            cursor.execute('''
                UPDATE portfolio
                SET amount = ?
                WHERE user_id = ? AND asset_name = ? AND asset_type = ?
            ''', (new_amount, user_id, asset_ticker, asset_type))
            conn.commit()
            await message.reply(f"Количество {asset_ticker} обновлено. Теперь у вас {new_amount}.")
        else:
            # Если актив не найден, добавляем его как новую запись
            cursor.execute('''
                INSERT INTO portfolio (user_id, asset_name, amount, asset_type)
                VALUES (?, ?, ?, ?)
            ''', (user_id, asset_ticker, amount, asset_type))
            conn.commit()
            await message.reply(f"{asset_ticker} в количестве {amount} добавлен в ваше портфолио.")
    except ValueError:
        await message.reply("Пожалуйста, введите корректное число для количества.")
    except Exception as e:
        await message.reply(f"Ошибка при добавлении в портфолио: {str(e)}")
    finally:
        await state.finish()  # Завершаем состояние после обработки

# Команда для отображения портфолио с текущими ценами активов
@dp.message_handler(Text(equals="Портфель", ignore_case=True))
async def portfolio_command(message: types.Message):
    user_id = message.from_user.id
    cursor.execute('SELECT asset_name, amount, asset_type FROM portfolio WHERE user_id = ?', (user_id,))
    assets = cursor.fetchall()

    if assets:
        portfolio_info = []
        for asset_name, amount, asset_type in assets:
            current_price = None
            # Получаем текущую цену для криптовалюты
            if asset_type == 'crypto':
                try:
                    current_price = get_crypto_rate(f"{asset_name}")
                except Exception as e:
                    current_price = f"Ошибка: {str(e)}"
            # Получаем текущую цену для валюты
            elif asset_type == 'currency':
                rates = get_currency_rate(asset_name)
                if asset_name in rates:
                    currency_info = rates[asset_name]
                    nominal = currency_info['Nominal']
                    value = currency_info['Value']
                    current_price = value / nominal  # Цена за единицу валюты
                else:
                    current_price = "Ошибка при получении курса"
            # Получаем текущую цену для акций
            elif asset_type == 'stock':
                current_price = get_stock_rate(asset_name)
                if not current_price:
                    current_price = "Ошибка при получении цены"
            # Формируем строку для каждого актива с его текущей ценой
            if isinstance(current_price, float):
                total_value = amount * current_price
                portfolio_info.append(
                    f"{asset_name} - Кол-во: {amount}, Цена: {current_price:.2f} USD, Итого: {total_value:.2f} USD"
                )
            else:
                portfolio_info.append(
                    f"{asset_name} - Кол-во: {amount}, Цена: {current_price}"
                )
        # Отправляем пользователю информацию о его портфолио
        await message.reply(f"Ваше портфолио:\n" + "\n".join(portfolio_info))
    else:
        await message.reply("Ваше портфолио пусто. Добавьте активы.")

# Запуск бота
if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True)
