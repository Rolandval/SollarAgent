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
    """Відображення головної сторінки"""
    logger.info(f"Запит головної сторінки. IP: {get_client_ip(request)}")
    return render(request, 'home.html')

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
        
        # Генеруємо відео з аватаром, який говорить текст відповіді
        video_start_time = time.time()
        video_url = generate_talking_avatar(ai_response, request_id)
        video_time = time.time() - video_start_time
        
        logger.info(f"[{request_id}] Отримано URL відео від D-ID за {video_time:.2f} сек: {video_url[:50]}...")
        
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

def generate_talking_avatar(text, request_id):
    """
    Генерує відео з аватаром, який говорить текст
    """
    logger.info(f"[{request_id}] Запит до D-ID API для створення відео")
    
    # Обмежуємо довжину тексту до 1000 символів (обмеження D-ID API)
    if len(text) > 1000:
        logger.warning(f"[{request_id}] Текст для D-ID API занадто довгий ({len(text)} символів), обмежуємо до 1000")
        text = text[:1000]
    
    # URL для статичного зображення аватара (використовується як запасний варіант)
    avatar_url = "https://create-images-results.d-id.com/DefaultPresenters/hussan/image.jpeg"
    
    try:
        # Налаштування для запиту до D-ID API
        url = settings.DID_URL
        headers = {
            "Authorization": f"Basic {settings.DID_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Дані для запиту
        data = {
            "presenter_id": "hussan",
            "script": {
                "type": "text",
                "input": text,
                "provider": {
                    "type": "microsoft",
                    "voice_id": "uk-UA-OstapNeural"
                },
                "ssml": "false"
            },
            "config": {
                "fluent": "true",
                "pad_audio": "0.0"
            }
        }
        
        # Відправка запиту до D-ID API для створення розмови
        logger.debug(f"[{request_id}] Відправка запиту до D-ID API: {settings.DID_URL}")
        did_response = requests.post(settings.DID_URL, headers=headers, json=data, timeout=30)
        
        # Перевірка успішності запиту
        status_code = did_response.status_code
        logger.debug(f"[{request_id}] Отримано відповідь від D-ID API, статус: {status_code}")
        
        if status_code == 200 or status_code == 201:
            result = did_response.json()
            logger.debug(f"[{request_id}] Отримано відповідь від D-ID API: {result}")
            
            # Отримуємо ID розмови
            talk_id = result.get("id")
            
            if not talk_id:
                logger.warning(f"[{request_id}] D-ID API не повернув ID розмови")
                return avatar_url
            
            # Чекаємо, поки відео буде готове
            status_url = f"{settings.DID_URL}/{talk_id}"
            max_attempts = 10
            attempts = 0
            
            while attempts < max_attempts:
                attempts += 1
                logger.debug(f"[{request_id}] Перевірка статусу відео, спроба {attempts}/{max_attempts}")
                
                status_response = requests.get(status_url, headers=headers)
                
                if status_response.status_code == 200:
                    status_data = status_response.json()
                    status = status_data.get("status")
                    
                    if status == "done":
                        video_url = status_data.get("result_url")
                        if video_url:
                            logger.info(f"[{request_id}] Успішно отримано URL відео: {video_url[:50]}...")
                            return video_url
                        else:
                            logger.warning(f"[{request_id}] D-ID API повернув статус 'done', але URL відео відсутній")
                            break
                    elif status == "error":
                        logger.error(f"[{request_id}] D-ID API повернув помилку: {status_data.get('error', 'Невідома помилка')}")
                        break
                    elif status in ["created", "processing"]:
                        logger.debug(f"[{request_id}] Відео все ще обробляється, статус: {status}")
                        time.sleep(2)  # Чекаємо 2 секунди перед наступною перевіркою
                    else:
                        logger.warning(f"[{request_id}] Невідомий статус відео: {status}")
                        break
                else:
                    logger.error(f"[{request_id}] Помилка при перевірці статусу відео: {status_response.status_code}")
                    break
            
            if attempts >= max_attempts:
                logger.warning(f"[{request_id}] Перевищено максимальну кількість спроб перевірки статусу відео")
        else:
            response_text = did_response.text
            logger.error(f"[{request_id}] Помилка D-ID API: {status_code}, відповідь: {response_text[:200]}...")
        
        # Якщо не вдалося отримати відео, повертаємо статичне зображення
        logger.info(f"[{request_id}] Використовуємо статичне зображення замість відео")
        return "https://create-images-results.d-id.com/DefaultPresenters/hussan/image.jpeg"
    
    except requests.RequestException as e:
        logger.error(f"[{request_id}] Помилка мережі при запиті до D-ID API: {str(e)}")
        # Повертаємо статичне зображення у випадку помилки
        return "https://create-images-results.d-id.com/DefaultPresenters/hussan/image.jpeg"
    except Exception as e:
        logger.error(f"[{request_id}] Неочікувана помилка при генерації відео: {str(e)}")
        logger.error(f"[{request_id}] Трасування: {traceback.format_exc()}")
        # Повертаємо статичне зображення у випадку помилки
        return "https://create-images-results.d-id.com/DefaultPresenters/hussan/image.jpeg"
