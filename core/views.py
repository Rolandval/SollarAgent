# core/views.py
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
import openai
openai.api_key = settings.OPENAI_API_KEY
import requests
import json
import time
import re
import logging
import traceback
import uuid
from datetime import datetime
import urllib.parse
import html
from bs4 import BeautifulSoup

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('solar_agent.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ID асистента OpenAI
assistant_id = settings.OPENAI_ASSISTANT_ID  # Отримуємо ID асистента з налаштувань


def home(request):
    """
    Головна сторінка з чатом
    """
    # Генеруємо унікальний ID для запиту
    request_id = str(uuid.uuid4())
    
    # Створюємо сесію з аватаром HeyGen для початкового відображення
    initial_stream_url = initialize_heygen_avatar(request_id)
    print(initial_stream_url)
    print(settings.HEYGEN_API_URL)
    
    return render(request, 'home.html', {'initial_stream_url': initial_stream_url})

def get_client_ip(request):
    """Отримання IP-адреси клієнта"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip

@csrf_exempt
def chat(request):
    """
    Обробляє запити чату від користувача
    """
    start_time = time.time()
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Метод не підтримується'}, status=405)
    
    # Генеруємо унікальний ID для запиту
    request_id = str(uuid.uuid4())
    logger.info(f"[{request_id}] Отримано новий запит чату")
    
    try:
        # Отримуємо дані з запиту
        data = json.loads(request.body)
        user_message = data.get('message', '').strip()
        
        if not user_message:
            logger.warning(f"[{request_id}] Отримано порожнє повідомлення")
            return JsonResponse({'error': 'Повідомлення не може бути порожнім'}, status=400)
        
        logger.info(f"[{request_id}] Повідомлення користувача: {user_message[:50]}...")
        
        # Отримуємо відповідь від OpenAI
        ai_response = get_openai_response(user_message, request_id)
        
        if not ai_response:
            logger.error(f"[{request_id}] Не вдалося отримати відповідь від OpenAI")
            return JsonResponse({'error': 'Не вдалося отримати відповідь'}, status=500)
        
        logger.info(f"[{request_id}] Відповідь OpenAI: {ai_response[:50]}...")
        
        # Генеруємо відео з аватаром HeyGen, який говорить текст відповіді
        video_start_time = time.time()
        video_url = generate_heygen_avatar(ai_response, request_id)
        video_time = time.time() - video_start_time
        
        logger.info(f"[{request_id}] Отримано URL відео від HeyGen за {video_time:.2f} сек: {video_url[:50]}...")
        
        # Формуємо відповідь
        response = {
            'message': ai_response,
            'video_url': video_url
        }
        
        total_time = time.time() - start_time
        logger.info(f"[{request_id}] Запит оброблено успішно за {total_time:.2f} сек")
        
        return JsonResponse(response)
        
    except json.JSONDecodeError:
        logger.error(f"[{request_id}] Помилка декодування JSON")
        return JsonResponse({'error': 'Невірний формат JSON'}, status=400)
    except Exception as e:
        logger.error(f"[{request_id}] Неочікувана помилка: {str(e)}")
        logger.error(traceback.format_exc())
        return JsonResponse({'error': 'Внутрішня помилка сервера'}, status=500)

def extract_solar_keywords(response):
    """Витягує ключові слова про сонячні панелі з відповіді"""
    # Список можливих ключових слів для пошуку
    potential_keywords = [
        "монокристалічні панелі", "полікристалічні панелі", "тонкоплівкові панелі",
        "сонячні панелі", "сонячна енергія", "фотоелектричні модулі",
        "потужність панелей", "ефективність панелей", "сонячні електростанції",
        "зелений тариф", "окупність сонячних панелей"
    ]
    
    keywords = []
    for keyword in potential_keywords:
        if keyword.lower() in response.lower():
            keywords.append(keyword)
    
    # Додатково шукаємо згадки про конкретні моделі або типи
    model_pattern = r'([\w\s-]+)?\s?\d+\s?(?:Вт|W|кВт|kW)'
    models = re.findall(model_pattern, response)
    
    # Додаємо знайдені моделі до ключових слів
    for model in models:
        if model.strip() and len(model.strip()) > 2:  # Перевіряємо, що модель не порожня і не занадто коротка
            keywords.append(model.strip())
    
    # Якщо не знайдено жодного ключового слова, використовуємо загальний запит
    if not keywords:
        keywords = ["сучасні сонячні панелі характеристики"]
    
    return keywords[:3]  # Обмежуємо до 3 ключових слів для пошуку

def search_solar_info_in_google(keywords, request_id):
    """Пошук інформації про сонячні панелі в Google"""
    try:
        # Формуємо пошуковий запит з ключових слів
        search_query = " ".join(keywords) + " технічні характеристики ціна"
        encoded_query = urllib.parse.quote(search_query)
        
        search_url = f"https://www.google.com/search?q={encoded_query}"
        logger.info(f"[{request_id}] Пошук в Google: {search_url}")
        
        # Заголовки для імітації браузера
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
        
        # Виконуємо запит до Google
        response = requests.get(search_url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            # Парсимо результати пошуку
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Шукаємо блоки з результатами
            search_results = []
            
            # Шукаємо блоки з інформацією
            info_blocks = soup.select('div.g')
            
            for block in info_blocks[:2]:  # Беремо перші 2 результати
                title_elem = block.select_one('h3')
                snippet_elem = block.select_one('div.VwiC3b')
                
                if title_elem and snippet_elem:
                    title = title_elem.get_text()
                    snippet = snippet_elem.get_text()
                    
                    # Очищаємо текст від HTML-тегів
                    title = html.unescape(title)
                    snippet = html.unescape(snippet)
                    
                    search_results.append(f"{title}: {snippet}")
            
            # Якщо знайдено результати, повертаємо їх
            if search_results:
                result_text = " | ".join(search_results)
                logger.info(f"[{request_id}] Знайдено інформацію в Google: {result_text[:100]}...")
                return result_text[:300] + "..." if len(result_text) > 300 else result_text
        
        logger.warning(f"[{request_id}] Не вдалося знайти інформацію в Google")
        return ""
        
    except Exception as e:
        logger.error(f"[{request_id}] Помилка при пошуку в Google: {str(e)}")
        return ""

def get_openai_response(user_message, request_id):
    """Отримання відповіді від OpenAI Assistant API"""
    try:
        # Створюємо новий потік для розмови
        logger.debug(f"[{request_id}] Створення нового потоку OpenAI")
        thread = openai.beta.threads.create()
        
        # Додаємо повідомлення користувача
        logger.debug(f"[{request_id}] Додавання повідомлення користувача до потоку")
        openai.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=user_message
        )
        
        # Отримуємо ID асистента з налаштувань
        assistant_id = settings.OPENAI_ASSISTANT_ID
        
        # Запускаємо асистента з інструкціями щодо сонячних панелей
        logger.debug(f"[{request_id}] Запуск асистента з ID: {assistant_id}")
        run = openai.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant_id,
            instructions="""
            Ти - експерт з сонячних панелей. Твоя мета - допомогти користувачу вибрати 
            найкращі сонячні панелі для їхніх потреб. Надавай інформацію про:
            
            1. Типи сонячних панелей (монокристалічні, полікристалічні, тонкоплівкові)
            2. Ефективність та потужність різних моделей
            3. Оптимальне розміщення на даху чи ділянці
            4. Розрахунок необхідної кількості панелей
            5. Орієнтовну вартість та окупність
            
            Відповідай українською мовою, чітко та зрозуміло. Якщо користувач цікавиться 
            конкретною моделлю, вкажи її характеристики у своїй відповіді.
            """
        )
        
        # Чекаємо завершення виконання
        logger.debug(f"[{request_id}] Очікування завершення виконання, run ID: {run.id}")
        poll_count = 0
        start_time = datetime.now()
        
        while True:
            poll_count += 1
            run_status = openai.beta.threads.runs.retrieve(
                thread_id=thread.id, 
                run_id=run.id
            )
            
            current_status = run_status.status
            elapsed_time = (datetime.now() - start_time).total_seconds()
            
            logger.debug(f"[{request_id}] Статус виконання ({poll_count}): {current_status}, час: {elapsed_time:.2f} сек")
            
            if current_status == "completed":
                logger.debug(f"[{request_id}] Виконання завершено за {elapsed_time:.2f} сек після {poll_count} перевірок")
                break
            
            elif current_status in ["failed", "cancelled", "expired"]:
                logger.error(f"[{request_id}] Помилка виконання: {current_status}")
                return None
            
            # Затримка перед наступною перевіркою
            time.sleep(1)
            
            # Обмеження кількості спроб
            if poll_count > 30:
                logger.error(f"[{request_id}] Перевищено ліміт очікування (30 секунд)")
                return None
        
        # Отримуємо останнє повідомлення від асистента
        logger.debug(f"[{request_id}] Отримання останнього повідомлення від асистента")
        messages = openai.beta.threads.messages.list(
            thread_id=thread.id
        )
        
        # Перевіряємо, чи є повідомлення
        if not messages.data:
            logger.error(f"[{request_id}] Не отримано повідомлень від асистента")
            return None
        
        # Отримуємо останнє повідомлення від асистента
        assistant_message = messages.data[0]
        
        # Перевіряємо, чи це повідомлення від асистента
        if assistant_message.role != "assistant":
            logger.error(f"[{request_id}] Останнє повідомлення не від асистента: {assistant_message.role}")
            return None
        
        # Отримуємо текст відповіді
        response_text = assistant_message.content[0].text.value
        
        logger.debug(f"[{request_id}] Отримано відповідь від асистента: {response_text[:50]}...")
        
        return response_text
        
    except Exception as e:
        logger.error(f"[{request_id}] Помилка при отриманні відповіді від OpenAI: {str(e)}")
        logger.error(traceback.format_exc())
        return None

def generate_heygen_avatar(text, request_id):
    """
    Генерує відео з аватаром HeyGen, який говорить текст
    """
    logger.info(f"[{request_id}] Запит до HeyGen API для створення відео з аватаром")
    
    # Обмежуємо довжину тексту
    if len(text) > 1000:
        logger.warning(f"[{request_id}] Текст для HeyGen API занадто довгий ({len(text)} символів), обмежуємо до 1000")
        text = text[:1000]
    
    # URL для статичного зображення аватара (використовується як запасний варіант)
    avatar_url = "https://create-images-results.d-id.com/DefaultPresenters/hussan/image.jpeg"
    
    try:
        # 1. Створюємо сесію з аватаром
        session_data = create_heygen_session(request_id)
        
        if not session_data or "session_id" not in session_data:
            logger.error(f"[{request_id}] Не вдалося створити сесію HeyGen")
            return avatar_url
        
        session_id = session_data["session_id"]
        stream_url = session_data.get("stream_url", "")
        
        logger.info(f"[{request_id}] Створено сесію HeyGen: {session_id}")
        logger.info(f"[{request_id}] Stream URL: {stream_url}")
        
        # 2. Відправляємо текст для озвучування
        if send_text_to_avatar(session_id, text, request_id):
            logger.info(f"[{request_id}] Успішно відправлено текст для озвучування")
            return stream_url
        else:
            logger.error(f"[{request_id}] Не вдалося відправити текст для озвучування")
            return avatar_url
    
    except Exception as e:
        logger.error(f"[{request_id}] Помилка при генерації відео HeyGen: {str(e)}")
        logger.error(f"[{request_id}] Трасування: {traceback.format_exc()}")
        return avatar_url

def initialize_heygen_avatar(request_id):
    """
    Ініціалізує аватар HeyGen для початкового відображення
    """
    logger.info(f"[{request_id}] Ініціалізація аватара HeyGen")
    
    try:
        # Створюємо сесію з аватаром
        session_data = create_heygen_session(request_id)
        
        if not session_data or "session_id" not in session_data:
            logger.error(f"[{request_id}] Не вдалося створити сесію HeyGen")
            return ""
        
        session_id = session_data["session_id"]
        stream_url = session_data.get("stream_url", "")
        
        logger.info(f"[{request_id}] Створено сесію HeyGen: {session_id}")
        logger.info(f"[{request_id}] Stream URL: {stream_url}")
        
        # Відправляємо привітальне повідомлення
        welcome_message = "Вітаю! Я ваш віртуальний консультант з сонячних панелей. Розкажіть, яке рішення ви шукаєте, і я допоможу підібрати оптимальний варіант для вас."
        
        if send_text_to_avatar(session_id, welcome_message, request_id):
            logger.info(f"[{request_id}] Успішно відправлено привітальне повідомлення")
            return stream_url
        else:
            logger.error(f"[{request_id}] Не вдалося відправити привітальне повідомлення")
            return ""
    
    except Exception as e:
        logger.error(f"[{request_id}] Помилка при ініціалізації аватара HeyGen: {str(e)}")
        logger.error(f"[{request_id}] Трасування: {traceback.format_exc()}")
        return ""

def create_heygen_session(request_id):
    """
    Створює нову сесію з аватаром HeyGen
    """
    logger.info(f"[{request_id}] Створення нової сесії HeyGen")
    
    try:
        # Налаштування для запиту до HeyGen API
        url = settings.HEYGEN_API_URL
        logger.info(f"[{request_id}] URL для створення сесії HeyGen: {url}")
        
        headers = {
            "X-Api-Key": settings.HEYGEN_API_KEY,
            "Content-Type": "application/json"
        }
        
        # Дані для запиту
        data = {
            "avatar_id": settings.HEYGEN_AVATAR_ID,
            "quality": "standard",
            "voice": {
                "voice_id": "microsoft.uk-UA-OstapNeural",
                "language": "uk-UA"
            },
            "video_encoding": "VP8",
            "disable_idle_timeout": True
        }
        
        logger.info(f"[{request_id}] Дані запиту для створення сесії: {json.dumps(data, ensure_ascii=False)}")
        
        # Відправка запиту до HeyGen API
        response = requests.post(url, headers=headers, json=data, timeout=30)
        status_code = response.status_code
        
        logger.info(f"[{request_id}] Отримано відповідь від HeyGen API, статус: {status_code}")
        
        if status_code == 200:
            result = response.json()
            logger.info(f"[{request_id}] Успішно створено сесію HeyGen: {json.dumps(result, ensure_ascii=False)}")
            return result
        else:
            response_text = response.text
            logger.error(f"[{request_id}] Помилка при створенні сесії HeyGen: {status_code}, відповідь: {response_text[:200]}...")
            return None
    
    except Exception as e:
        logger.error(f"[{request_id}] Помилка при створенні сесії HeyGen: {str(e)}")
        logger.error(f"[{request_id}] Трасування: {traceback.format_exc()}")
        return None

def send_text_to_avatar(session_id, text, request_id):
    """
    Відправляє текст для озвучування аватаром HeyGen
    """
    logger.info(f"[{request_id}] Відправка тексту для озвучування аватаром HeyGen")
    
    try:
        # Налаштування для запиту до HeyGen API
        base_url = settings.HEYGEN_API_URL.replace('/sessions', '')
        url = f"{base_url}/tasks"
        
        logger.info(f"[{request_id}] URL для відправки тексту: {url}")
        
        headers = {
            "X-Api-Key": settings.HEYGEN_API_KEY,
            "Content-Type": "application/json"
        }
        
        # Дані для запиту
        data = {
            "session_id": session_id,
            "task_type": "REPEAT",
            "text": text
        }
        
        logger.info(f"[{request_id}] Дані запиту для відправки тексту: {json.dumps(data, ensure_ascii=False)}")
        
        # Відправка запиту до HeyGen API
        response = requests.post(url, headers=headers, json=data, timeout=30)
        status_code = response.status_code
        
        logger.info(f"[{request_id}] Отримано відповідь від HeyGen API, статус: {status_code}")
        
        if status_code == 200:
            result = response.json()
            logger.info(f"[{request_id}] Успішно відправлено текст для озвучування: {json.dumps(result, ensure_ascii=False)}")
            return True
        else:
            response_text = response.text
            logger.error(f"[{request_id}] Помилка при відправці тексту для озвучування: {status_code}, відповідь: {response_text[:200]}...")
            return False
    
    except Exception as e:
        logger.error(f"[{request_id}] Помилка при відправці тексту для озвучування: {str(e)}")
        logger.error(f"[{request_id}] Трасування: {traceback.format_exc()}")
        return False

def close_heygen_session(session_id, request_id):
    """
    Закриває сесію з аватаром HeyGen
    """
    logger.info(f"[{request_id}] Закриття сесії HeyGen: {session_id}")
    
    try:
        # Налаштування для запиту до HeyGen API
        url = f"{settings.HEYGEN_API_URL}/{session_id}"
        
        logger.info(f"[{request_id}] URL для закриття сесії: {url}")
        
        headers = {
            "X-Api-Key": settings.HEYGEN_API_KEY
        }
        
        # Відправка запиту до HeyGen API
        response = requests.delete(url, headers=headers, timeout=30)
        status_code = response.status_code
        
        logger.info(f"[{request_id}] Отримано відповідь від HeyGen API, статус: {status_code}")
        
        if status_code == 200:
            result = response.json()
            logger.info(f"[{request_id}] Успішно закрито сесію HeyGen: {json.dumps(result, ensure_ascii=False)}")
            return True
        else:
            response_text = response.text
            logger.error(f"[{request_id}] Помилка при закритті сесії HeyGen: {status_code}, відповідь: {response_text[:200]}...")
            return False
    
    except Exception as e:
        logger.error(f"[{request_id}] Помилка при закритті сесії HeyGen: {str(e)}")
        logger.error(f"[{request_id}] Трасування: {traceback.format_exc()}")
        return False
