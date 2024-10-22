import unittest
import json
import os
from dotenv import load_dotenv
from unittest.mock import AsyncMock, patch, MagicMock
from aiogram import Bot
from aiogram.types import Message
from aiogram.dispatcher import FSMContext, Dispatcher
from aiounittest import AsyncTestCase
from main import get_currency_rate, get_crypto_rate, get_stock_rate, conn, cursor, process_asset_type, process_asset_ticker, process_asset_amount, add_to_portfolio, process_asset_type, process_asset_ticker, process_asset_amount, Portfolio, asset_type_inline_keyboard
from aiogram.contrib.fsm_storage.memory import MemoryStorage

API_TOKEN = os.getenv('API_TOKEN')

class TestFinanceBot(unittest.TestCase):
    @patch('main.requests.get')
    def test_get_currency_rate(self, mock_get):
        # Пример ответа API ЦБ РФ
        mock_response = {
            "Valute": {
                "USD": {
                    "Value": 76.32,
                    "Name": "Доллар США",
                    "Nominal": 1
                },
                "EUR": {
                    "Value": 90.45,
                    "Name": "Евро",
                    "Nominal": 1
                }
            }
        }
        mock_get.return_value.json.return_value = mock_response
        rates = get_currency_rate("USD")
        self.assertIn("USD", rates)
        self.assertEqual(rates["USD"]["Value"], 76.32)
        self.assertEqual(rates["USD"]["Name"], "Доллар США")

    @patch('main.client.get_symbol_ticker')
    def test_get_crypto_rate(self, mock_get_symbol_ticker):
        # Пример ответа Binance API
        mock_get_symbol_ticker.return_value = {
            "symbol": "BTCUSDT",
            "price": "58000.50"
        }  
        rate = get_crypto_rate("BTC")
        self.assertEqual(rate, 58000.50)

    @patch('main.requests.get')
    def test_get_stock_rate(self, mock_get):
        # Пример ответа Alpha Vantage API
        mock_response = {
            "Time Series (Daily)": {
                "2024-10-16": {
                    "4. close": "150.50"
                }
            }
        }
        mock_get.return_value.json.return_value = mock_response
        rate = get_stock_rate("IBM")
        self.assertEqual(rate, "150.50")

    def test_database_insert_user(self):
        # Вставка данных пользователя в базу данных
        cursor.execute('INSERT INTO users (user_id, username) VALUES (?, ?)', (12345, "test_user"))
        conn.commit()
        # Проверка, что пользователь был добавлен
        cursor.execute('SELECT username FROM users WHERE user_id = ?', (12345,))
        result = cursor.fetchone()
        self.assertEqual(result[0], "test_user")
    def test_database_insert_portfolio(self):
        # Добавляем запись в таблицу portfolio
        cursor.execute('''
            INSERT INTO portfolio (user_id, asset_name, amount, asset_type)
            VALUES (?, ?, ?, ?)
        ''', (12345, 'BTC', 1.5, 'crypto'))
        conn.commit()
        # Проверка, что актив был добавлен
        cursor.execute('SELECT amount FROM portfolio WHERE user_id = ? AND asset_name = ?', (12345, 'BTC'))
        result = cursor.fetchone()
        self.assertEqual(result[0], 1.5)
    def tearDown(self):
        # Очистка базы данных после каждого теста
        cursor.execute('DELETE FROM users WHERE user_id = ?', (12345,))
        cursor.execute('DELETE FROM portfolio WHERE user_id = ?', (12345,))
        conn.commit()

class TestPortfolioHandlers(AsyncTestCase):
    def setUp(self):
        # Создаем моки для бота и диспетчера
        self.bot = Bot(token=API_TOKEN)
        self.storage = MemoryStorage() 
        self.dispatcher = Dispatcher(self.bot, storage=self.storage)
        self.state = AsyncMock(FSMContext)
        self.state.set_state = AsyncMock()
        self.state.update_data = AsyncMock()
        self.state.finish = AsyncMock()

    async def test_process_asset_type(self):
        message = MagicMock(Message)
        message.text = "Крипто"
        message.reply = AsyncMock()
        message.from_user.id = 123456789 
        message.chat.id = 67890       

        # Мокаем методы FSMContext
        state = AsyncMock()
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()

        # Мокаем Dispatcher.get_current() внутри теста
        with patch('aiogram.dispatcher.Dispatcher.get_current', return_value=self.dispatcher):
            await process_asset_type(message, state)
           
        state.update_data.assert_called_once_with(asset_type="крипто")
        message.reply.assert_called_once_with("Вы выбрали крипто. Пожалуйста, введите тикер актива:")
        state.set_state.assert_called_once_with(Portfolio.waiting_for_asset_ticker)
    
    async def test_process_asset_ticker(self):
        message = MagicMock(Message)
        message.text = "BTC"
        message.reply = AsyncMock()

    @patch('main.get_crypto_rate', return_value=50000.0)
    async def test_process_asset_amount_crypto(self, mock_get_crypto_rate):
        message = MagicMock(Message)
        message.text = "1.5"
        message.from_user.id = 12345
        message.reply = AsyncMock()
        
        # Мокаем состояние с сохраненными данными
        state = AsyncMock(FSMContext)
        state.get_data = AsyncMock(return_value={'asset_type': 'crypto', 'asset_ticker': 'BTC'})
        
        # Создаем мок для взаимодействия с базой данных
        cursor = MagicMock()
        cursor.fetchone = MagicMock(return_value=None)
        
        await process_asset_amount(message, state)
        
        mock_get_crypto_rate.assert_called_once_with("BTC")
        message.reply.assert_called_once_with("BTC в количестве 1.5 добавлен в ваше портфолио.")
        state.finish.assert_called_once()

if __name__ == '__main__':
    unittest.main()
