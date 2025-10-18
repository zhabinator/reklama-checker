import os
import fitz  # PyMuPDF
import easyocr
from flask import Flask, request, jsonify
import google.generativeai as genai
import io

# --- Настройка ---
app = Flask(__name__)

# Настраиваем API-ключ Gemini
try:
    genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
except Exception as e:
    print(f"Ошибка конфигурации Google AI: {e}")

# Создаем "читалку" для изображений. 
# Мы делаем это один раз при старте, чтобы не загружать модель при каждом запросе.
reader = easyocr.Reader(['ru', 'en'], gpu=False)

# --- Функции-помощники для извлечения текста ---

def extract_text_from_pdf(file_stream):
    """Извлекает текст из PDF-файла."""
    text = ""
    with fitz.open(stream=file_stream, filetype="pdf") as doc:
        for page in doc:
            text += page.get_text()
    return text

def extract_text_from_image(file_stream):
    """Извлекает текст из изображения с помощью EasyOCR."""
    image_bytes = file_stream.read()
    # Используем detail=0, чтобы получить только список строк текста
    results = reader.readtext(image_bytes, detail=0, paragraph=True)
    return "\n".join(results)

def extract_text_from_txt(file_stream):
    """Читает текст из простого текстового файла."""
    return file_stream.read().decode('utf-8')


# --- Главная логика приложения ---

@app.route('/api/check', methods=['POST'])
def check_ad_file():
    # 1. Проверяем, пришел ли к нам файл
    if 'file' not in request.files:
        return jsonify({"error": "Файл не найден в запросе."}), 400
    
    file = request.files['file']
    filename = file.filename

    # Если имя файла пустое
    if filename == '':
        return jsonify({"error": "Выбран пустой файл."}), 400

    # 2. Определяем тип файла и используем нужный инструмент
    extracted_text = ""
    try:
        # Читаем файл в память один раз
        file_stream = io.BytesIO(file.read())

        if filename.lower().endswith('.pdf'):
            extracted_text = extract_text_from_pdf(file_stream)
        elif filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            extracted_text = extract_text_from_image(file_stream)
        elif filename.lower().endswith('.txt'):
            extracted_text = extract_text_from_txt(file_stream)
        else:
            return jsonify({"error": "Неподдерживаемый формат файла. Используйте PDF, JPEG, PNG или TXT."}), 400
            
        if not extracted_text.strip():
             return jsonify({"error": "Не удалось извлечь текст из файла. Возможно, это изображение без текста или пустой документ."}), 400

    except Exception as e:
        return jsonify({"error": f"Ошибка при обработке файла: {str(e)}"}), 500

    # 3. Отправляем извлеченный текст в Gemini (как и раньше)
    try:
        model = genai.GenerativeModel('gemini-pro')
        prompt = f"""
        Представь, что ты — опытный юрист, специализирующийся на рекламном праве в РФ.
        Проведи предварительный анализ следующего рекламного текста, извлеченного из файла, на наличие потенциальных рисков и нарушений ФЗ "О рекламе".

        Текст для анализа:
        ---
        {extracted_text}
        ---

        Выяви и укажи в своем ответе следующие моменты:
        1. Использование превосходных степеней ("лучший", "самый") без доказательств.
        2. Гарантии или обещания эффективности.
        3. Отсутствие обязательных предупреждений (о противопоказаниях, не является публичной офертой, возрастная маркировка).
        4. Некорректные сравнения с конкурентами.
        5. Любые другие формулировки, которые могут быть расценены как вводящие потребителя в заблуждение.

        Сформируй ответ в виде краткого, но емкого списка по пунктам. Если проблем не найдено, напиши об этом.
        """ # <-- ВОТ ИСПРАВЛЕНИЕ: Мы закрываем тройные кавычки здесь
        
        response = model.generate_content(prompt)
        return jsonify({"results": response.text})

    except Exception as e:
        return jsonify({"error": f"Произошла ошибка при обращении к AI-сервису: {e}"}), 500