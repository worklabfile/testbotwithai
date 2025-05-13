import logging
import json
import os
import requests
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
import pandas as pd
import random
import string

# Конфигурация
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

os.makedirs('tests', exist_ok=True)
os.makedirs('progress', exist_ok=True)
os.makedirs('stats', exist_ok=True)

try:
    from config import TELEGRAM_BOT_TOKEN, GENAPI_KEY
except ImportError:
    TELEGRAM_BOT_TOKEN = 'YOUR_TELEGRAM_BOT_TOKEN'
    GENAPI_KEY = 'YOUR_GENAPI_KEY'

GENAPI_URL = 'https://api.gen-api.ru/api/v1/networks/gpt-4o-mini'
ADMIN_ID = 911971063  # Замените на ваш Telegram ID

# Генерация простого ID
def generate_test_id(length=6):
    characters = string.ascii_letters + string.digits
    while True:
        test_id = ''.join(random.choice(characters) for _ in range(length))
        if not os.path.exists(f"tests/test_{test_id}.json"):
            return test_id

# Модели данных
class TestConfig:
    def __init__(self, mcq_count: int = 10):
        self.mcq_count = mcq_count

def save_test(test_data: dict, creator_id: int, creator_username: str) -> str:
    test_id = generate_test_id()
    test_data['metadata'] = {
        'id': test_id,
        'created_at': datetime.now().isoformat(),
        'creator_id': creator_id,
        'creator_username': creator_username,
        'total_points': calculate_total_points(test_data)
    }
    
    filename = f"tests/test_{test_id}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(test_data, f, ensure_ascii=False, indent=2)
    return test_id

def calculate_total_points(test_data: dict) -> int:
    return len(test_data.get('question_options', [])) * test_data.get('points_per_mcq', 1)

def load_test(test_id: str) -> dict:
    filename = f"tests/test_{test_id}.json"
    with open(filename, 'r', encoding='utf-8') as f:
        return json.load(f)

def update_user_progress(user_id: int, username: str, test_id: str, test_title: str, score: int):
    progress_file = f"progress/user_{user_id}.json"
    try:
        with open(progress_file, 'r', encoding='utf-8') as f:
            progress = json.load(f)
    except FileNotFoundError:
        progress = {'user_id': user_id, 'username': username, 'completed_tests': {}}
    
    # Всегда сохраняем как словарь с title и score
    progress['completed_tests'][test_id] = {'title': test_title, 'score': score}
    with open(progress_file, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)

def generate_stats_excel(creator_id: int):
    progress_files = [f for f in os.listdir('progress') if f.startswith('user_')]
    data = []
    for file in progress_files:
        with open(f'progress/{file}', 'r', encoding='utf-8') as f:
            user_data = json.load(f)
            for test_id, test_info in user_data['completed_tests'].items():
                test_data = load_test(test_id)
                # Добавляем только тесты, созданные вами
                if test_data['metadata']['creator_id'] == creator_id:
                    data.append({
                        'User ID': user_data['user_id'],
                        'Username': user_data['username'],
                        'Test ID': test_id,
                        'Test Title': test_info['title'],
                        'Score': test_info['score']
                    })
    
    if data:
        df = pd.DataFrame(data)
        filename = f"stats/stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        df.to_excel(filename, index=False)
        return filename
    return None

async def generate_test(topic: str, config: TestConfig) -> dict:
    prompt = f"""
    Сгенерируй тест по теме "{topic}" в следующем JSON формате:
    {{
      "title": "Название теста",
      "category": "Категория",
      "points_per_mcq": 1,
      "question_options": [
        {{
          "topic": "Подтема",
          "question_text": "Текст вопроса с вариантами ответов",
          "options": ["вариант1", "вариант2", "вариант3", "вариант4"],
          "answers": [0]
        }}
      ]
    }}
    Сгенерируй ровно 10 вопросов с вариантами ответов (question_options).
    Вопросы должны быть разными и охватывать разные аспекты темы.
    """

    payload = {
        "is_sync": True,
        "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
        "stream": False,
        "n": 1,
        "max_tokens": 4000,
        "temperature": 0.7,
        "response_format": {"type": "json_object"}
    }

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Authorization': f'Bearer {GENAPI_KEY}'
    }

    response = requests.post(GENAPI_URL, json=payload, headers=headers)
    data = response.json()
    
    if 'response' in data:
        content = data['response'][0]['message']['content']
        return json.loads(content)
    raise ValueError(f"Ошибка API: {data.get('error', 'Неизвестная ошибка')}")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Привет! Я бот для создания и прохождения тестов.\n\n"
        "Команды:\n"
        "/newtest - создать тест\n"
        "/mytests - мои тесты\n"
        "/taketest - пройти тест\n"
        "/progress - мой прогресс\n"
        "/stats - статистика (админ)"
    )

async def new_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Введите тему теста (генерируется 10 вопросов с вариантами):")

async def handle_new_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    topic = update.message.text.strip()
    config = TestConfig()
    await update.message.reply_text(f"⌛ Генерирую тест по теме: {topic}...")
    try:
        user = update.effective_user
        test_data = await generate_test(topic, config)
        context.user_data['preview_test'] = test_data
        context.user_data['preview_index'] = 0
        await show_preview_question(update, context)
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {str(e)}")

async def show_preview_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    test_data = context.user_data['preview_test']
    index = context.user_data['preview_index']
    questions = test_data['question_options']
    
    question = questions[index]
    text = (f"Вопрос {index + 1}/10\n\n{question['question_text']}\n\n"
            f"Варианты:\n" + "\n".join(f"{i+1}. {opt}" for i, opt in enumerate(question['options'])) +
            f"\n\nПравильный: {question['options'][question['answers'][0]]}")
    
    keyboard = []
    if index > 0:
        keyboard.append([InlineKeyboardButton("← Назад", callback_data=f"preview_prev")])
    if index < 9:
        keyboard.append([InlineKeyboardButton("Вперед →", callback_data=f"preview_next")])
    keyboard.append([InlineKeyboardButton("Опубликовать", callback_data="publish_test"),
                     InlineKeyboardButton("Отменить", callback_data="cancel_test")])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    if 'preview_message_id' in context.user_data:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['preview_message_id'],
            text=text,
            reply_markup=reply_markup
        )
    else:
        message = await update.message.reply_text(text, reply_markup=reply_markup)
        context.user_data['preview_message_id'] = message.message_id

async def handle_preview_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    
    if action == "preview_prev":
        context.user_data['preview_index'] = max(0, context.user_data['preview_index'] - 1)
    elif action == "preview_next":
        context.user_data['preview_index'] = min(9, context.user_data['preview_index'] + 1)
    await show_preview_question(update, context)

async def handle_publish_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    test_data = context.user_data.pop('preview_test')
    user = update.effective_user
    test_id = save_test(test_data, user.id, user.username)
    
    keyboard = [[InlineKeyboardButton("Пройти тест", callback_data=f"take_test_{test_id}")]]
    await query.edit_message_text(f"✅ Тест опубликован! ID: {test_id}", reply_markup=InlineKeyboardMarkup(keyboard))
    context.user_data.pop('preview_index', None)
    context.user_data.pop('preview_message_id', None)

async def handle_cancel_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop('preview_test', None)
    context.user_data.pop('preview_index', None)
    context.user_data.pop('preview_message_id', None)
    await query.edit_message_text("❌ Создание теста отменено.")

async def my_tests(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    test_files = [f for f in os.listdir('tests') if f.startswith('test_')]
    tests = [load_test(f.split('_')[1].split('.')[0]) for f in test_files 
             if load_test(f.split('_')[1].split('.')[0])['metadata']['creator_id'] == user.id]
    
    if not tests:
        await update.message.reply_text("Вы еще не создали тесты.")
        return
    
    keyboard = [[InlineKeyboardButton(test['title'], callback_data=f"take_test_{test['metadata']['id']}")] 
                for test in tests]
    await update.message.reply_text("Ваши тесты:", reply_markup=InlineKeyboardMarkup(keyboard))

async def take_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    test_files = [f for f in os.listdir('tests') if f.startswith('test_')]
    if not test_files:
        await update.message.reply_text("Нет доступных тестов.")
        return
    
    keyboard = [[InlineKeyboardButton(load_test(f.split('_')[1].split('.')[0])['title'], 
                                      callback_data=f"take_test_{f.split('_')[1].split('.')[0]}")] 
                for f in test_files[:10]]
    await update.message.reply_text("Выберите тест:", reply_markup=InlineKeyboardMarkup(keyboard))

async def start_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    test_id = query.data.split('_')[-1]
    context.user_data.update({
        'current_test': test_id,
        'current_question': 0,
        'score': 0,
        'answers': []
    })
    await show_test_question(update, context)

async def show_test_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    test_data = load_test(context.user_data['current_test'])
    index = context.user_data['current_question']
    question = test_data['question_options'][index]
    
    text = f"Вопрос {index + 1}/10\n\n{question['question_text']}"
    keyboard = [[InlineKeyboardButton(opt, callback_data=f"answer_{index}_{i}")] 
                for i, opt in enumerate(question['options'])]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    if 'test_message_id' in context.user_data:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=context.user_data['test_message_id'],
            text=text,
            reply_markup=reply_markup
        )
    else:
        message = await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=reply_markup
        )
        context.user_data['test_message_id'] = message.message_id

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    test_data = load_test(context.user_data['current_test'])
    index, answer_idx = map(int, query.data.split('_')[1:])
    question = test_data['question_options'][index]
    is_correct = int(answer_idx) in question['answers']
    points = test_data['points_per_mcq'] if is_correct else 0
    
    context.user_data['score'] += points
    context.user_data['answers'].append({
        'question': question['question_text'],
        'user_answer': question['options'][answer_idx],
        'correct_answer': question['options'][question['answers'][0]],
        'points': points
    })
    
    context.user_data['current_question'] += 1
    if context.user_data['current_question'] < 10:
        await show_test_question(update, context)
    else:
        await finish_test(update, context)

async def finish_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    test_data = load_test(context.user_data['current_test'])
    user = update.effective_user
    score = context.user_data['score']
    total = test_data['metadata']['total_points']
    update_user_progress(user.id, user.username, context.user_data['current_test'], test_data['title'], score)
    
    text = f"🏁 Тест завершен: {test_data['title']}\n\nВаш результат: {score}/{total} ({score/total*100:.1f}%)"
    await context.bot.edit_message_text(
        chat_id=update.effective_chat.id,
        message_id=context.user_data['test_message_id'],
        text=text
    )
    context.user_data.clear()

async def user_progress(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    progress_file = f"progress/user_{user.id}.json"
    try:
        with open(progress_file, 'r', encoding='utf-8') as f:
            progress = json.load(f)
        if not progress['completed_tests']:
            raise FileNotFoundError
        
        # Исправляем обработку прогресса для поддержки старого формата
        text = "Ваш прогресс:\n\n"
        for test_id, info in progress['completed_tests'].items():
            test_data = load_test(test_id)
            if isinstance(info, int):  # Старый формат, только score
                score = info
                title = test_data['title']
            else:  # Новый формат, словарь
                score = info['score']
                title = info['title']
            total_points = test_data['metadata']['total_points']
            text += f"{title}: {score}/{total_points}\n"
        await update.message.reply_text(text)
    except FileNotFoundError:
        await update.message.reply_text("Вы еще не прошли тесты.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if user.id != ADMIN_ID:
        await update.message.reply_text("Только для администратора.")
        return
    
    filename = generate_stats_excel(ADMIN_ID)
    if filename:
        await update.message.reply_document(document=open(filename, 'rb'), caption="Статистика по моим тестам")
    else:
        await update.message.reply_text("Нет данных по вашим тестам.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("newtest", new_test))
    app.add_handler(CommandHandler("mytests", my_tests))
    app.add_handler(CommandHandler("taketest", take_test))
    app.add_handler(CommandHandler("progress", user_progress))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_new_test))
    app.add_handler(CallbackQueryHandler(handle_preview_navigation, pattern="^preview_"))
    app.add_handler(CallbackQueryHandler(handle_publish_test, pattern="^publish_test$"))
    app.add_handler(CallbackQueryHandler(handle_cancel_test, pattern="^cancel_test$"))
    app.add_handler(CallbackQueryHandler(start_test, pattern="^take_test_"))
    app.add_handler(CallbackQueryHandler(handle_answer, pattern="^answer_"))
    
    print("🤖 Бот запущен...")
    app.run_polling()

if __name__ == '__main__':
    main()