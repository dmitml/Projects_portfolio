# Стандартная библиотека
from datetime import datetime
from pathlib import Path
import hashlib
import json
import os
import random
import re
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Tuple

# Сторонние пакеты
import pandas as pd
import pymorphy3

# from llama_cpp import Llama
from striprtf.striprtf import rtf_to_text
import export_to_excel
import requests
from dotenv import load_dotenv

load_dotenv("YANDEX_CLOUD_KEYS.env")

# Читаем переменные
FOLDER_ID = os.getenv("FOLDER_ID")
API_KEY_YANDEX = os.getenv("API_KEY_YANDEX")

# Проверка, что всё загружено
if not FOLDER_ID or not API_KEY_YANDEX:
    raise EnvironmentError(
        "Не удалось загрузить FOLDER_ID или API_KEY_YANDEX из YANDEX_CLOUD_KEYS.env"
    )

# Список для проверки дат
DATE_KEYS = ["Дата рождения", "Дата госпитализации", "Дата выписки", "Дата смерти"]
# Путь к модели
# MODEL_PATH = "YandexGPT-5-Lite-8B-instruct-Q4_K_M.gguf"


def load_text(file_path):
    """
    Извлекает текст из файла (PDF, TXT, RTF) с Google Drive

    Аргументы:
        file_path (str): Полный путь к файлу

    Возвращает:
        tuple: (извлеченный_текст: str, тип_файла: str)
               Например: ("Текст документа...", ".pdf")

    Исключения:
        FileNotFoundError: Если файл не найден
        ValueError: Если формат не поддерживается или не удалось декодировать
        RuntimeError: Если ошибка при чтении PDF
    """
    import os
    import fitz  # Импорт внутри функции для избежания конфликтов

    # Проверка существования файла
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Файл не найден: {file_path}")

    # Определение расширения файла
    file_ext = os.path.splitext(file_path)[1].lower()

    text_content = None

    # Обработка TXT
    if file_ext == ".txt":
        encodings = ["utf-8-sig", "cp1251", "iso-8859-1", "utf-16"]

        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding, errors="replace") as f:
                    content = f.read()
                    content = content.lstrip("\ufeff\x00\r\n\t ")

                    if any("\u0400" <= c <= "\u04ff" for c in content):
                        text_content = content
                        break

                    if "" in content:
                        continue

                    text_content = content
                    break

            except (UnicodeDecodeError, Exception):
                continue

        if text_content is None:
            raise ValueError(f"Не удалось декодировать файл {file_path}")

    # Обработка RTF
    elif file_ext == ".rtf":
        try:
            from striprtf.striprtf import rtf_to_text
        except ImportError:
            raise ImportError(
                "Модуль striprtf не установлен. Установите: pip install striprtf"
            )

        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text_content = rtf_to_text(f.read())

    # Обработка PDF
    elif file_ext == ".pdf":
        text = []
        try:
            doc = fitz.open(file_path)
            for page in doc:
                page_text = page.get_text("text", sort=True)

                # Извлечение таблиц
                tables = page.find_tables()
                if tables:
                    table_text = "\n".join(
                        "\t".join(cell.strip() for cell in row)
                        for table in tables
                        for row in table.extract()
                    )
                    page_text += "\n\n" + table_text

                text.append(page_text)

            text_content = "\n\n".join(text)
            doc.close()

        except Exception as e:
            raise RuntimeError(f"Ошибка чтения PDF: {str(e)}") from e

    else:
        raise ValueError(f"Неподдерживаемый формат файла: {file_ext}")

    # Возвращаем текст и тип файла
    return text_content, file_ext


def check_and_mark_document(
    text: str, hash_db_path: str = "document_hashes.json"
) -> bool:
    """
    Проверяет, обрабатывался ли уже документ по хешу содержимого.
    Если нет — добавляет хеш в базу.

    Аргументы:
        text (str): Текст документа
        hash_db_path (str): Путь к JSON-файлу с хешами

    Возвращает:
        bool: True — документ уже был (дубликат), False — новый, добавлен в базу
    """
    # Нормализуем текст: убираем лишние пробелы и приводим к нижнему регистру
    normalized = " ".join(text.strip().lower().split())
    doc_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    # Создаём директорию, если нужно
    dir_path = os.path.dirname(hash_db_path)
    if dir_path:  # если путь не в текущей директории
        os.makedirs(dir_path, exist_ok=True)

    # Если файл с хешами не существует — значит, это первый документ
    if not os.path.exists(hash_db_path):
        try:
            with open(hash_db_path, "w", encoding="utf-8") as f:
                json.dump([doc_hash], f, ensure_ascii=False, indent=2)
        except Exception as e:
            raise RuntimeError(
                f"Не удалось создать файл базы хешей: {hash_db_path}"
            ) from e
        return False  # новый документ

    # Читаем существующие хеши
    try:
        with open(hash_db_path, "r", encoding="utf-8") as f:
            known_hashes = json.load(f)
        if not isinstance(known_hashes, list):
            known_hashes = []
    except (json.JSONDecodeError, Exception):
        known_hashes = []  # если файл битый — начинаем с чистого листа

    # Проверяем, есть ли уже такой хеш
    if doc_hash in known_hashes:
        return True  # дубликат

    # Если нет — добавляем
    known_hashes.append(doc_hash)
    try:
        with open(hash_db_path, "w", encoding="utf-8") as f:
            json.dump(known_hashes, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise RuntimeError(
            f"Не удалось обновить файл базы хешей: {hash_db_path}"
        ) from e

    return False  # новый документ, успешно добавлен


# Функция проверки, является ли текст эпикризом
def is_epicrisis(text: str) -> bool:
    """
    Проверяет, является ли текст эпикризом (выписным/посмертным).

    Возвращает:
        bool: True, если текст похож на эпикриз, иначе False
    """
    # Ключевые слова и структура
    keywords = [
        "диагноз",
        "жалоб",
        "анамнез",
        "лечен",
        "рекомендац",
        "нозологическ",
        "сопутствующ",
        "клиническ",
        "посмертн",
        "заключительн",
        "основн",
        "история болезни",
        "мкб",
        "стационарн",
        "выписн",
        "обследован",
        "состоян",
        "эпикриз",
        "паспортн",
        "госпитализ",
        "амбулаторн",
        "рецепт",
        "назначен",
    ]

    structure = [
        "дата поступл",
        "дата выпис",
        "дата смерт",
        "рекомендац:",
        "жалоб",
        "состоян",
        "проведен",
        "обследован",
        "заключительн диагн",
        "основн диагн",
        "эпикриз\n",
        "ф.и.о.",
        "возраст",
        "полис",
        "снилс",
        "диагноз при поступл",
        "диагноз заключительн",
    ]

    # Проверка длины
    if not text or len(text.strip()) < 100:
        return False

    lower_text = text.lower()

    # Считаем совпадения
    found_keywords = sum(1 for kw in keywords if kw in lower_text)
    found_structure = sum(1 for s in structure if s in lower_text)

    # Условие: хотя бы 4 ключевых слова и 2 структурных элемента
    return found_keywords >= 4 and found_structure >= 2


# Функция выбора промпта в зависимости от типа файла
def load_prompt_by_ext(file_ext):
    """
    Загружает текстовый файл-шаблон в зависимости от расширения файла.

    Поддерживаемые типы:
        .pdf  -> prompt_pdf.txt
        .txt  -> prompt_txt.txt
        .rtf  -> prompt_rtf.txt

    Аргументы:
        file_ext (str): Расширение файла (например, '.pdf', '.txt', '.rtf')

    Возвращает:
        str: Содержимое соответствующего prompt-файла

    Исключения:
        ValueError: Если расширение не поддерживается
        FileNotFoundError: Если соответствующий prompt-файл не найден
    """
    # Определяем имя файла-шаблона в зависимости от расширения
    prompt_files = {
        ".pdf": "prompt_pdf.txt",
        ".txt": "prompt_txt.txt",
        ".rtf": "prompt_rtf.txt",
    }

    # Приводим к нижнему регистру на всякий случай
    file_ext = file_ext.lower()

    if file_ext not in prompt_files:
        raise ValueError(f"Нет поддержки prompt-файла для расширения: {file_ext}")

    prompt_filename = prompt_files[file_ext]
    prompt_path = os.path.join(os.getcwd(), prompt_filename)  # Ищем в корне проекта

    # Проверяем, существует ли файл
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(f"Файл-шаблон не найден: {prompt_path}")

    # Читаем и возвращаем содержимое
    with open(prompt_path, "r", encoding="utf-8") as f:
        return f.read().strip()


def validate_keys(
    data: Dict, prompt_num: int, dict_keys: Dict[int, List[str]]
) -> Tuple[bool, List[str]]:
    """
    Проверяет наличие обязательных ключей в данных.

    Аргументы:
        data (dict): Словарь с данными (например, извлечённый JSON).
        prompt_num (int): Номер промпта (чтобы выбрать нужный набор ключей).
        dict_keys (dict): Словарь: {номер_промпта -> список обязательных ключей}

    Возвращает:
        (bool, list):
            - True, если все ключи есть; False — если есть пропущенные,
            - Список отсутствующих ключей.
    """
    required_keys = dict_keys.get(prompt_num, [])
    missing_keys = [key for key in required_keys if key not in data]
    return (len(missing_keys) == 0, missing_keys)


def normalize_for_verification(text: str) -> str:
    """
    Нормализует текст для проверки совпадений:
    - Приводит к нижнему регистру
    - Заменяет все знаки препинания на пробел
    - Схлопывает множественные пробелы в один
    - Удаляет пробелы в начале и конце

    Аргументы:
        text (str): Входной текст

    Возвращает:
        str: Нормализованный текст
    """
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text)  # Заменяем пунктуацию на пробел
    text = re.sub(r"\s+", " ", text)  # Множественные пробелы → один
    return text.strip()


def clean_json_string(content: str) -> str:
    """
    Очищает строку от обёрток вроде ```json ... ``` и лишних символов.

    Убирает:
    - ```json и ``` (регистронезависимо)
    - Внешние кавычки и пробелы
    - Лишние пробелы внутри

    Аргументы:
        content (str): Входная строка (возможно, с JSON в обёртке)

    Возвращает:
        str: Очищенная строка, готовая к парсингу как JSON
    """
    # Удаляем ```json и ``` (в начале и конце, регистронезависимо)
    clean_content = re.sub(
        r"^\s*```json\s*|\s*```\s*$", "", content, flags=re.IGNORECASE
    )

    # Убираем пробелы, кавычки и апострофы по краям
    clean_content = clean_content.strip().strip('"').strip("'")

    # Заменяем множественные пробелы на один
    clean_content = re.sub(r"\s+", " ", clean_content)

    return clean_content


def extract_json(content: str) -> Optional[Dict]:
    """
    Извлекает JSON из строкового ответа модели.

    Поддерживает:
    - Ответы с обёрткой ```json ... ```
    - Ответы с текстом до/после JSON
    - Лишние кавычки и пробелы

    Аргументы:
        content (str): Строка, возможно содержащая JSON

    Возвращает:
        dict или None: Распарсенный JSON или None, если извлечь не удалось
    """
    try:
        # Используем независимую функцию очистки
        clean_content = clean_json_string(content)

        # Находим первую { и последнюю }
        start_idx = clean_content.find("{")
        end_idx = clean_content.rfind("}")

        if start_idx == -1 or end_idx == -1 or end_idx < start_idx:
            return None

        json_str = clean_content[start_idx : end_idx + 1]

        return json.loads(json_str)

    except json.JSONDecodeError as e:
        print(f"❌ Ошибка парсинга JSON: {str(e)}")
        return None
    except Exception as e:
        print(f"❌ Неожиданная ошибка при извлечении JSON: {e}")
        return None


def validate_date(date_str: str) -> bool:
    """Проверяет дату в различных форматах"""
    if not date_str:
        return False

    formats = [
        "%d.%m.%Y",
        "%d.%m.%y",
        "%Y-%m-%d",
        "%Y-%m",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%B %d, %Y",
        "%b %d, %Y",
    ]

    for fmt in formats:
        try:
            datetime.strptime(date_str, fmt)
            return True
        except ValueError:
            continue
    return False


def validate_gender(gender: str) -> bool:
    """Проверяет пол с учетом различных вариантов написания"""
    return gender.lower() in {
        "м",
        "ж",
        "муж",
        "жен",
        "мужской",
        "женский",
        "m",
        "f",
    }


def validate_text(text: str) -> bool:
    """Проверяет, что строка содержит только буквы и разрешенные символы"""
    pattern = r"^[^\W\d_][\w\s\-,.]*$"
    return bool(re.fullmatch(pattern, text, re.UNICODE))


def validate_snils(snils: str) -> bool:
    """
    Проверяет корректность СНИЛС по следующим правилам:
    - Формат: XXX-XXX-XXX YY (допускаются пробелы, дефисы)
    - Номер > 001-001-998
    - Контрольное число рассчитывается по алгоритму ПФР
    - Не допускаются 3 одинаковые цифры подряд

    Аргумент:
        snils (str): Строка с номером СНИЛС

    Возвращает:
        bool: True, если СНИЛС валиден, иначе False
    """
    if not snils or not isinstance(snils, str):
        return False

    # Удаляем все символы, кроме цифр
    digits = re.sub(r"\D", "", snils)

    # Должно быть ровно 11 цифр: 9 + 2 (контрольное число)
    if len(digits) != 11:
        return False

    number_part = digits[:9]  # первые 9 цифр — номер
    control_part = int(digits[9:11])  # последние 2 — контрольное число

    # Преобразуем номер в целое число
    try:
        number = int(number_part)
    except ValueError:
        return False

    # Условие: номер должен быть больше 1001998
    if number <= 1001998:
        return False

    # Проверка на три одинаковые цифры подряд
    cleaned_digits = "".join(re.findall(r"\d", snils))  # только цифры
    for i in range(len(cleaned_digits) - 2):
        if cleaned_digits[i] == cleaned_digits[i + 1] == cleaned_digits[i + 2]:
            return False

    # Расчёт контрольной суммы
    # Веса: с 9 до 1 (для 9 цифр), позиции с конца: 9,8,7,6,5,4,3,2,1
    weights = [9, 8, 7, 6, 5, 4, 3, 2, 1]
    total = sum(int(digit) * weight for digit, weight in zip(number_part, weights))

    # Применение правил контрольного числа
    if total < 100:
        expected_control = total
    elif total in (100, 101):
        expected_control = 0
    else:
        expected_control = total % 101
        if expected_control >= 100:
            expected_control = 0

    # Сравниваем с переданным контрольным числом
    return control_part == expected_control


def is_full_fio(fio: str) -> bool:
    """
    Проверяет, что в ФИО минимум два слова длиннее одной буквы.
    Игнорирует инициалы с точками, дефисы, апострофы.
    """
    if not fio:
        return False

    parts = fio.strip().split()
    long_words = 0

    for part in parts:
        # Убираем ., -, ' — чтобы не считать их при подсчёте длины
        clean = re.sub(r"[.\-']", "", part)
        if len(clean) > 1:
            long_words += 1

    return long_words >= 2


def validate_oms(oms: str) -> bool:
    """
    Проверяет, является ли строка валидным номером полиса ОМС (нового образца).

    Правила:
    - Только цифры
    - Ровно 21 символ
    - Не может быть пустым или "не указано"

    Аргумент:
        oms (str): Строка с номером полиса ОМС

    Возвращает:
        bool: True, если номер валиден, иначе False
    """
    if not oms or not isinstance(oms, str):
        return False

    # Приводим к строке и убираем пробелы по краям
    oms = oms.strip()

    # Исключаем явные "заглушки"
    if oms.lower() in (
        "не указано",
        "отсутствует",
        "нет",
        "n/a",
        "-",
        "—",
        "null",
        "none",
        "",
    ):
        return False

    # Удаляем всё, кроме цифр (на случай, если модель добавила дефисы, пробелы и т.п.)
    digits = "".join(filter(str.isdigit, oms))

    # Проверяем длину
    if len(digits) != 21:
        return False

    # Убедимся, что вся строка — только цифры (и после очистки не изменилась логически)
    # Необязательно, но можно проверить, что не все цифры одинаковые (защита от 111...111)
    if digits == digits[0] * 21:
        return False  # подозрительно: 111111111111111111111

    return True


def normalize_birthdate(date_str: str) -> str | None:
    """
    Нормализует дату рождения к формату ДД.ММ.ГГГГ.
    Возвращает строку или None, если не удаётся распарсить.
    """
    if not date_str:
        return None
    date_str = date_str.strip()
    if date_str.lower() in ("не указано", "отсутствует", "нет", "n/a", "-", "—"):
        return None

    formats = ["%d.%m.%Y", "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime("%d.%m.%Y")
        except ValueError:
            continue
    return None


def hash_personal_data(patient: dict, hash_size: int = 16) -> dict:
    """
    Хэширует персональные данные пациента.
    Возвращает словарь: {поле: hex-хэш}, для отсутствующих — нулевой хэш.

    Использует: ФИО (нормализованное), Дата рождения, Регион
    """
    # 1. Нормализуем ФИО: только если полное
    fio = patient.get("ФИО")
    if fio and is_full_fio(fio):
        # Приводим к нижнему регистру, разбиваем, сортируем (на случай "Иван Иванов" vs "Иванов Иван")
        fio_clean = " ".join(sorted(re.sub(r"[^\w\s]", "", fio).lower().split()))
    else:
        fio_clean = None

    # 2. Нормализуем дату рождения
    birth_date = normalize_birthdate(patient.get("Дата рождения"))

    # 3. Регион — берём как есть, но чистим
    region = patient.get("Регион")
    if region:
        region = re.sub(r"[^\w\s]", "", region).strip().lower()
        region = " ".join(region.split())  # убираем лишние пробелы
        if not region:
            region = None
    else:
        region = None

    # Поля для хэширования
    fields = {
        "ФИО": fio_clean,
        "Дата рождения": birth_date,
        "Регион": region,
    }

    # Генерируем нулевой хэш нужной длины
    zero_hash = "0" * (hash_size * 2)
    hashes = {}

    for key, value in fields.items():
        if value is None:
            hashes[key] = zero_hash
        else:
            h = hashlib.blake2b(value.encode("utf-8"), digest_size=hash_size)
            hashes[key] = h.hexdigest()

    return hashes


def generate_patient_uin(hashes: dict) -> str | None:
    """
    Генерирует УИН как конкатенацию хэшей: ФИО + Дата рождения + Регион.

    Возвращает None, если хотя бы одно из этих полей — нулевой хэш.
    """
    required_keys = ["ФИО", "Дата рождения", "Регион"]

    for key in required_keys:
        if key not in hashes:
            return None
        if set(hashes[key]) == {"0"}:  # проверяем, не "000...0"
            return None

    return hashes["ФИО"] + hashes["Дата рождения"] + hashes["Регион"]


def generate_document_id() -> str:
    """
    При каждом вызове выдает уникальный номер UUID для документа
    """
    return str(uuid.uuid4())


# Создаём глобальный экземпляр анализатора (один раз при импорте)
morph = pymorphy3.MorphAnalyzer()


def sanitize_document_text(
    document_text: str, full_json: dict, file_ext: str, output_dir: str = "."
):
    """
    Удаляет из текста персональные данные, найденные в full_json.
    Сохраняет очищенный текст в .txt файл с именем, равным значению full_json['УИН документа'].

    Аргументы:
        document_text (str): Исходный текст документа
        full_json (dict): Извлечённые данные, включая 'УИН документа'
        file_ext (str): Расширение изначального файла
        output_dir (str): Каталог для сохранения (по умолчанию — текущий)

    Возвращает:
        str: Путь к сохранённому файлу
    """
    if not document_text or not isinstance(document_text, str):
        raise ValueError("document_text должен быть непустой строкой")

    if "УИН документа" not in full_json:
        raise KeyError("В full_json отсутствует ключ 'УИН документа'")

    uin = full_json["УИН документа"]
    if not uin or not isinstance(uin, str):
        raise ValueError("УИН документа должен быть непустой строкой")

    # Очищаем УИН от недопустимых символов для имени файла (Windows/Linux)
    safe_uin = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", uin)
    output_path = os.path.join(output_dir, f"{safe_uin}.txt")

    cleaned_text = document_text

    # Поля, содержащие персональные данные
    sensitive_fields = {
        "ФИО",
        "Пол пациента",
        "Дата рождения",
        "Адрес",
        "Номер СНИЛС",
        "Номер полиса ОМС",
    }

    values_to_remove = set()

    for key, value in full_json.items():
        if key not in sensitive_fields:
            continue
        if not value or not isinstance(value, str):
            continue
        value = value.strip()

        if key == "ФИО":
            # Добавляем полное ФИО
            if value:
                values_to_remove.add(value)

            # Разбиваем на части (фамилия, имя, отчество)
            parts = re.split(r"\s+", value)
            for part in parts:
                part = part.strip()
                if not part:
                    continue

                # Всегда добавляем исходную часть (даже короткие: "А.", "Ли")
                values_to_remove.add(part)

                # Пробуем просклонять через pymorphy2
                try:
                    parsed = morph.parse(part)
                    if not parsed:
                        continue

                    # Берём самый вероятный разбор
                    best = parsed[0]

                    # Генерируем все формы из лексемы
                    for form in best.lexeme:
                        word = form.word
                        if word and len(word) >= 2:
                            values_to_remove.add(word)

                except Exception as e:
                    # Игнорируем ошибки (редко, но бывает)
                    pass

        else:
            # Для остальных полей — только если длина >=3
            if len(value) >= 3:
                values_to_remove.add(value)

        if key == "Дата рождения":
            if not value or not isinstance(value, str):
                continue
            value = value.strip()
            if len(value) < 10:  # формат DD.MM.YYYY — минимум 10 символов
                continue

            # Добавляем исходную дату
            values_to_remove.add(value)
            values_to_remove.add(value + "г.")
            values_to_remove.add(value + " г.")
            values_to_remove.add(value + " года")
            values_to_remove.add(value + "года")
            values_to_remove.add(value + "года.")
            values_to_remove.add(value + "г")
            values_to_remove.add(value + " г")
            values_to_remove.add(value + " года.")

            try:
                # Парсим дату в формате DD.MM.YYYY
                day_str, month_str, year_str = value.split(".")
                day = int(day_str)
                month = int(month_str)
                year = int(year_str)

                # Названия месяцев в родительном падеже (для "3 декабря 1954")
                months_rus = [
                    "января",
                    "февраля",
                    "марта",
                    "апреля",
                    "мая",
                    "июня",
                    "июля",
                    "августа",
                    "сентября",
                    "октября",
                    "ноября",
                    "декабря",
                ]
                if 1 <= month <= 12:
                    month_name = months_rus[month - 1]

                    # Добавляем словесные формы
                    values_to_remove.add(f"{day} {month_name} {year}")
                    values_to_remove.add(f"{day:02d} {month_name} {year}")
                    values_to_remove.add(f"{day} {month_name} {year}г.")
                    values_to_remove.add(f"{day} {month_name} {year} года")
                    values_to_remove.add(f"{day:02d} {month_name} {year} года")

                    # С заглавной буквы (в начале предложения)
                    values_to_remove.add(f"{day} {month_name.capitalize()} {year}")
                    values_to_remove.add(f"{day:02d} {month_name.capitalize()} {year}")
                    values_to_remove.add(f"{day} {month_name.capitalize()} {year}г.")
                    values_to_remove.add(f"{day} {month_name.capitalize()} {year} года")
                    values_to_remove.add(
                        f"{day:02d} {month_name.capitalize()} {year} года"
                    )

            except (ValueError, IndexError, Exception):
                # Если не получилось разобрать дату — оставляем только исходное значение
                pass

        elif key == "Номер СНИЛС":
            if not value or not isinstance(value, str):
                continue
            value = value.strip()

            # Оставляем только цифры
            digits = re.sub(r"\D", "", value)
            if len(digits) != 11:
                # СНИЛС должен быть 11 цифр
                continue

            # Разбиваем на части: первые 9 и последние 2
            body = digits[:9]  # 123456789
            ctrl = digits[9:]  # 00

            # Добавляем все возможные форматы
            formats = [
                f"{body[:3]}-{body[3:6]}-{body[6:]} {ctrl}",  # 123-456-789 00
                f"{body[:3]}-{body[3:6]}-{body[6:]}- {ctrl}",  # 123-456-789- 00
                f"{body[:3]}-{body[3:6]}-{body[6:]}{ctrl}",  # 123-456-78900
                f"{body[:3]} {body[3:6]} {body[6:]} {ctrl}",  # 123 456 789 00
                f"{body} {ctrl}",  # 123456789 00
                f"{body}{ctrl}",  # 12345678900
            ]

            for fmt in formats:
                values_to_remove.add(fmt)

        elif key == "Адрес":
            if not value or not isinstance(value, str):
                continue
            value = value.strip()
            if len(value) < 3:
                continue

            # Полный адрес
            values_to_remove.add(value)

            # Разбиваем на "чистые" слова (только буквы/цифры)
            words = re.findall(r"[а-яА-ЯёЁa-zA-Z0-9]+", value)

            # Биграммы и триграммы
            for i in range(len(words) - 1):
                bigram = f"{words[i]} {words[i+1]}"
                if len(bigram) >= 3:
                    values_to_remove.add(bigram)
            for i in range(len(words) - 2):
                trigram = f"{words[i]} {words[i+1]} {words[i+2]}"
                if len(trigram) >= 5:
                    values_to_remove.add(trigram)

            # Добавляем типовые шаблоны, которые могут быть в тексте
            # Даже если их нет в full_json — удаляем по шаблону
            patterns = [
                r"д\.\s*\d+",  # д. 10
                r"кв\.\s*\d+",  # кв. 25
                r"[а-яА-ЯёЁ]+[аяую]я\s+область",  # Воронежская область
                r"[а-яА-ЯёЁ]+[ыйий]\s+район",  # Куйбышевский район
                r"город\s+[а-яА-ЯёЁ]+",  # город Москва
                r"село\s+[а-яА-ЯёЁ]+",
                r"пос[её]лок\s+[а-яА-ЯёЁ]+",
                r"ул\.\s*[а-яА-ЯёЁ]+",
                r"улица\s+[а-яА-ЯёЁ]+",
            ]

            for pattern in patterns:
                if re.search(pattern, value, re.IGNORECASE):
                    # Добавляем как шаблон для поиска — но не в values_to_remove
                    # Будем удалять отдельно
                    pass

    # Удаляем значения: сначала самые длинные (чтобы не сломать контекст)
    for value in sorted(values_to_remove, key=len, reverse=True):
        escaped = re.escape(value)
        pattern = rf"\b{escaped}\b"
        cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE)

    address_patterns = [
        r"д\.\s*\d+",
        r"кв\.\s*\d+",
        r"[а-яА-ЯёЁ]+[аяую]я\s+область",
        r"[а-яА-ЯёЁ]+[ыйий]\s+район",
        r"город\s+[а-яА-ЯёЁ]+",
        r"село\s+[а-яА-ЯёЁ]+",
        r"пос[её]лок\s+[а-яА-ЯёЁ]+",
        r"ул\.\s*[а-яА-ЯёЁ]+",
        r"улица\s+[а-яА-ЯёЁ]+",
    ]

    for pattern in address_patterns:
        cleaned_text = re.sub(pattern, "", cleaned_text, flags=re.IGNORECASE)

    # Очищаем от лишних пробелов и переносов
    cleaned_text = re.sub(r" +", " ", cleaned_text)  # множественные пробелы → один
    cleaned_text = re.sub(r"\n+", "\n", cleaned_text)  # множественные переносы → один
    cleaned_text = cleaned_text.strip()

    # Добавляем метаданные в начало
    patient_uin = full_json.get("УИН", "не указан")
    patient_age = full_json.get(
        "Возраст пациента на момент госпитализации", "не указан"
    )
    patient_sex = full_json.get("Пол пациента", "не указан")

    header = (
        f"УИН пациента: {patient_uin}\n\n"
        f"Возраст пациента на момент госпитализации: {patient_age}\n\n"
        f"Пол пациента: {patient_sex}\n\n"
        f"Расширение изначального файла: {file_ext}\n\n"
    )
    cleaned_text = header + cleaned_text

    # Создаём директорию, если её нет
    os.makedirs(output_dir, exist_ok=True)

    # Сохраняем очищенный текст
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(cleaned_text)

    print(f"Очищенный текст сохранён: {output_path}")
    return output_path


def save_errors(errors: dict, full_json: dict, output_dir: str = "errors"):
    """
    Сохраняет словарь errors в JSON-файл с именем, равным значению full_json['УИН документа'].

    Аргументы:
        errors (dict): Словарь с результатами валидации
        full_json (dict): Данные, содержащие 'УИН документа'
        output_dir (str): Каталог для сохранения

    Возвращает:
        str: Путь к сохранённому файлу
    """
    if "УИН документа" not in full_json:
        raise KeyError("В full_json отсутствует ключ 'УИН документа'")

    uin = full_json["УИН документа"]
    if not uin or not isinstance(uin, str):
        raise ValueError("УИН документа должен быть непустой строкой")

    # Очищаем УИН от недопустимых символов для имени файла
    safe_uin = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", uin)
    output_path = os.path.join(output_dir, f"{safe_uin}.json")

    # Создаём директорию, если её нет
    os.makedirs(output_dir, exist_ok=True)

    # Сохраняем errors в формате JSON с удобочитаемым отступом
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(errors, f, ensure_ascii=False, indent=2)

    print(f"Ошибки сохранены: {output_path}")
    return output_path


def save_full_json_to_sql(full_json: dict, db_path: str):
    """
    Добавляет одну запись (один документ) в SQL-базу.
    Создаёт таблицу, если её нет.
    Не проверяет дубли — каждый документ сохраняется.
    """
    # 1. Переводим full_json в DataFrame (одна строка)
    df = pd.DataFrame([full_json])  # список из одного словаря → одна строка

    # 2. Сохраняем в SQL
    with sqlite3.connect(db_path) as conn:
        df.to_sql(
            name="patients",  # имя таблицы
            con=conn,
            if_exists="append",  # добавляем, не перезаписываем
            index=False,  # не сохраняем индекс
            method="multi",  # быстрее при вставке
        )

    print(
        f"✅ Документ сохранён в БД: УИН документа = {full_json.get('УИН документа')}"
    )


def mark_readmission(full_json: dict, uins: set, db_path: str):
    """
    Проверяет, есть ли УИН из full_json в списке uins.
    Если есть — обновляет поле "Повторная госпитализация" = 1.
    """
    uin_to_check = full_json.get("УИН")
    if not uin_to_check:
        return

    try:
        if uin_to_check in uins:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE patients SET "Повторная госпитализация" = 1 WHERE УИН = ?',
                (uin_to_check,),
            )
            conn.commit()
            conn.close()
            print(f"🔁 Повторная госпитализация: УИН {uin_to_check} помечен.")
        # else: новый пациент — ничего не делаем (он будет добавлен позже)
    except sqlite3.Error as e:
        print(f"❌ Ошибка при обновлении повторной госпитализации: {e}")
        if "conn" in locals():
            conn.close()


def fix_age(full_json: dict) -> str:
    """
    Исправляет поле 'Возраст' в full_json.
    Если возраст не число — пытается вычислить из:
        Дата госпитализации - Дата рождения

    Аргументы:
        full_json (dict): Словарь с данными (включая даты)

    Возвращает:
        str: Исправленный возраст (в виде строки) или "не указано"
    """
    # Поля дат
    birth_date_str = full_json.get("Дата рождения", "").strip()
    hosp_date_str = full_json.get("Дата госпитализации", "").strip()

    # Формат даты
    date_format = "%d.%m.%Y"

    def parse_date(date_str: str) -> datetime:
        if not date_str:
            return None
        try:
            return datetime.strptime(date_str.strip(), date_format)
        except ValueError:
            return None

    # Попробуем распарсить даты
    birth_date = parse_date(birth_date_str)
    hosp_date = parse_date(hosp_date_str)

    # Текущий возраст
    current_age = full_json.get("Возраст пациента на момент госпитализации", "").strip()

    # Проверяем, является ли возраст числом
    if current_age and re.fullmatch(r"\d+", current_age):
        return current_age  # ✅ Уже корректный возраст

    # Если даты есть — вычисляем возраст
    if birth_date and hosp_date:
        # Разница в годах
        age = hosp_date.year - birth_date.year
        # Уточняем: если день рождения ещё не наступил в год госпитализации
        if (hosp_date.month, hosp_date.day) < (birth_date.month, birth_date.day):
            age -= 1
        return str(age)

    # Если не удалось вычислить
    return "Данные отсутствуют"


def model(prompt: str) -> str:
    """
    Принимает текстовый промпт и возвращает ответ модели YandexGPT.
    """
    try:
        # Вызов облака
        response_text = yandex_gpt_generate(
            api_key=API_KEY_YANDEX,
            folder_id=FOLDER_ID,
            prompt=prompt,
            model="yandexgpt-lite",  # можно использовать "yandexgpt-pro" при необходимости
            temperature=0.1,
            max_tokens=10000,
            timeout=45,
        )
        return response_text.strip()
    except Exception as e:
        # Обработка ошибок
        print(f"❌ Ошибка при генерации: {e}")
        return "Извините, произошла ошибка при генерации ответа."


def yandex_gpt_generate(
    api_key: str,
    folder_id: str,
    prompt: str,
    model: str = "yandexgpt",
    temperature: float = 0.1,
    max_tokens: int = 12000,
    timeout: int = 45,
) -> str:
    """
    Генерирует ответ с помощью YandexGPT.

    :param api_key: API-ключ Yandex Cloud
    :param folder_id: ID каталога в Yandex Cloud
    :param prompt: Входной промпт
    :param model: Модель (по умолчанию "yandexgpt")
    :param temperature: Температура генерации
    :param max_tokens: Максимальное количество токенов
    :param timeout: Таймаут запроса
    :return: Сгенерированный текст
    :raises RuntimeError: Если запрос не удался
    """
    headers = {
        "Authorization": f"Api-Key {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "modelUri": f"gpt://{folder_id}/{model}",
        "messages": [{"role": "user", "text": prompt}],
        "completionOptions": {
            "temperature": temperature,
            "maxTokens": max_tokens,
        },
    }

    try:
        response = requests.post(
            "https://llm.api.cloud.yandex.net/foundationModels/v1/completion",
            headers=headers,
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        return data["result"]["alternatives"][0]["message"]["text"]
    except (requests.RequestException, json.JSONDecodeError, KeyError) as e:
        raise RuntimeError(f"YandexGPT request failed: {str(e)}")


def run_processing_cycle(region: str, allow_duplicates: bool = False):

    # Заданием путь к папке process_files, в которой лежат документы для обработки (рядом со скриптом)
    folder_path = os.path.join(os.path.dirname(__file__), "process_files")

    # Получаем список файлов
    files = [
        os.path.join(folder_path, f)
        for f in os.listdir(folder_path)
        if os.path.isfile(
            os.path.join(folder_path, f)
        )  # проверка, что это файл (не папка)
        and f.lower().endswith((".pdf", ".txt", ".rtf"))
    ]

    print(f"Найдено {len(files)} файлов: {files}")

    # Загружаем базу SQL
    uins = set()
    db_path = "personal_data.db"

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Всегда пытаемся создать таблицу, если её нет
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS patients (
                УИН TEXT,
                ФИО TEXT,
                "Дата рождения" TEXT,
                "Пол пациента" TEXT,
                "Адрес" TEXT,
                "Возраст пациента на момент госпитализации" TEXT,
                "Номер СНИЛС" TEXT,
                "Номер полиса ОМС" TEXT,
                "Название больницы" TEXT,
                "Дата госпитализации" TEXT,
                "Дата выписки" TEXT,
                "Дата смерти" TEXT,
                "Повторная госпитализация" INTEGER,
                "Регион" TEXT,
                "УИН документа" TEXT
            )
    """
        )

        # Читаем таблицу
        cursor.execute("SELECT DISTINCT УИН FROM patients")
        uins = {row[0] for row in cursor.fetchall()}
        conn.close()

        print(f"✅ Загружено {len(uins)} уникальных УИН.")

    except sqlite3.Error as e:
        print(f"⚠️ Не удалось загрузить данные из базы: {e}")
        print(
            "🔧 Будет использована пустая база. Новые записи создадут таблицу при сохранении."
        )
        # uins остаётся пустым set()
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        # Можно выйти или продолжить с чистого листа

    # Запускаем цикл обработки
    for file_path in files:
        print(f"\n📄 Обработка файла: {file_path}")

        model_json = None
        full_json = None
        document_text = None
        file_ext = None
        success = False

        try:
            # === 🔹 ШАГ 0: Загрузка и предварительная проверка (вне цикла попыток) ===
            document_text, file_ext = load_text(file_path)

            # Проверка на дубликат
            is_duplicate = check_and_mark_document(document_text)

            if is_duplicate and not allow_duplicates:
                print("  ❌ Документ уже обработан (дубликат). Пропускаем.")
                continue  # 🔴 Пропускаем, если дубли запрещены

            # ✅ Иначе — обрабатываем (даже если дубликат, но разрешено)
            print("  ✅ Новый документ или дубликат разрешён — продолжаем...")

            # Проверка: эпикриз ли это?
            if not is_epicrisis(document_text):
                print("  ❌ Документ не является эпикризом")
                errors = {"Документ эпикриз": False}
                full_json = {"УИН документа": generate_document_id()}
                save_errors(errors, full_json, output_dir="errors")
                continue  # 🔁 Переходим к следующему файлу

            # Проверка расширения
            if file_ext not in [".pdf", ".txt", ".rtf"]:
                print("  ❌ Неподдерживаемый формат файла")
                errors = {"Верный формат файла": False}
                full_json = {"УИН документа": generate_document_id()}
                save_errors(errors, full_json, output_dir="errors")
                continue  # 🔁

            # === 🔁 Цикл попыток (максимум 3) ===
            max_attempts = 3  # Количество попыток 3
            success = False
            keys_valid = True
            missing_keys = []

            for attempt in range(1, max_attempts + 1):
                print(f"  Попытка {attempt}...")

                try:
                    # --- Шаг 2: Подготовка промпта ---
                    prompt = load_prompt_by_ext(file_ext)

                    # Усиливаем промпт при повторных попытках
                    if attempt > 1:
                        missing_fields_msg = ""
                        if not keys_valid and missing_keys:
                            missing_fields_msg = f"Особенно важно заполнить следующие поля: {', '.join(missing_keys)}. "

                        prompt += (
                            "\n\nВАЖНО: Предыдущий ответ содержал ошибки. "
                            "Убедитесь, что все поля заполнены корректно и полностью. "
                            "Особое внимание уделите формату: даты (ДД.ММ.ГГГГ), ФИО (полностью), СНИЛС, ОМС. "
                            f"{missing_fields_msg}"
                            "Не возвращайте неполные данные, инициалы или заглушки вроде 'Не указано'."
                        )

                    combined_input = (
                        f"{prompt}\n\n<DOCUMENT>\n{document_text}\n</DOCUMENT>"
                    )

                    # --- Шаг 3: Запрос к модели ---
                    model_answer = model(combined_input)
                    model_json = extract_json(model_answer)

                    if model_json is None:
                        raise ValueError("Не удалось извлечь JSON из ответа модели")

                    # --- Шаг 4: Валидация ---
                    all_required_keys = [
                        "ФИО",
                        "Пол пациента",
                        "Дата рождения",
                        "Адрес",
                        "Номер СНИЛС",
                        "Номер полиса ОМС",
                        "Название больницы",
                        "Дата госпитализации",
                        "Дата выписки",
                        "Дата смерти",
                    ]
                    keys_valid, missing_keys = validate_keys(
                        model_json, prompt_num=1, dict_keys={1: all_required_keys}
                    )

                    errors = {
                        "Документ эпикриз": True,
                        "Верный формат файла": True,
                        "Все ключи": keys_valid,
                        "ФИО": is_full_fio(model_json.get("ФИО", "")),
                        "Пол пациента": validate_gender(
                            model_json.get("Пол пациента", "")
                        ),
                        "Дата рождения": validate_date(
                            model_json.get("Дата рождения", "")
                        ),
                        "Возраст пациента на момент госпитализации": True,
                        "Адрес": bool(model_json.get("Адрес")),
                        "Номер СНИЛС": validate_snils(
                            model_json.get("Номер СНИЛС", "")
                        ),
                        "Номер полиса ОМС": validate_oms(
                            model_json.get("Номер полиса ОМС", "")
                        ),
                        "Название больницы": bool(model_json.get("Название больницы")),
                        "Дата госпитализации": validate_date(
                            model_json.get("Дата госпитализации", "")
                        ),
                        "Дата выписки": validate_date(
                            model_json.get("Дата выписки", "")
                        ),
                        "Дата смерти": validate_date(model_json.get("Дата смерти", "")),
                    }

                    # Проверка дат
                    for key in DATE_KEYS:
                        value = model_json.get(key, "")
                        errors[key] = validate_date(value)

                    # --- Шаг 5: Проверка успеха ---
                    if all(errors.values()):
                        print("  ✅ Все поля валидны!")
                        success = True
                        break  # Успешно — выходим из попыток
                    else:
                        print(
                            f"  ❌ Ошибки найдены: {[k for k, v in errors.items() if not v]}"
                        )
                        if attempt < max_attempts:
                            print("  Повторный запрос...")
                        else:
                            print("  ⚠️ Максимум попыток достигнут.")

                except Exception as e:
                    print(f"  Ошибка на попытке {attempt}: {str(e)}")
                    if attempt == max_attempts:
                        # Только при последней попытке сохраняем ошибки
                        errors = {
                            "Ошибка извлечения JSON": (
                                True if model_json is None else False
                            ),
                            "Неизвестная ошибка": str(e),
                        }
                        full_json = {"УИН документа": generate_document_id()}
                        save_errors(errors, full_json, output_dir="errors")
                    # Продолжение в следующей попытке

            # === После цикла попыток ===
            if model_json is not None:
                # ✅ Даже если валидация не прошла — сохраняем данные
                full_json = model_json.copy()
                full_json["Регион"] = region
                full_json["Возраст пациента на момент госпитализации"] = fix_age(
                    full_json
                )

                patient_uin = generate_patient_uin(hash_personal_data(full_json))
                full_json["УИН"] = patient_uin

                # Проверяем, повторный ли пациент
                is_returning = patient_uin in uins
                full_json["Повторная госпитализация"] = 1 if is_returning else 0
                full_json["УИН документа"] = generate_document_id()

                # Сохраняем очищенный текст
                sanitize_document_text(
                    document_text, full_json, file_ext, output_dir="cleaned_docs"
                )

                # Сохраняем ОШИБКИ (чтобы знать, что не так)
                save_errors(
                    errors, full_json, output_dir="errors"
                )  # сохраняем ошибки (если были предупреждения)

                try:
                    save_full_json_to_sql(full_json, db_path=db_path)
                    if not is_returning:
                        uins.add(patient_uin)
                    print(
                        f"✅ Данные сохранены в БД (с ошибками: {[k for k, v in errors.items() if not v]})"
                    )
                except Exception as e:
                    print(f"❌ Ошибка при сохранении в базу: {e}")
                    # Всё равно сохраняем ошибку
                    save_errors(
                        {"Ошибка сохранения в БД": False},
                        full_json,
                        output_dir="errors",
                    )

                    # Устанавливаем success только если всё валидно
                if all(errors.values()):
                    success = True
                    print("  ✅ Все поля валидны!")
                else:
                    success = False
                    print(
                        f"  ⚠️ Сохранены с ошибками: {[k for k, v in errors.items() if not v]}"
                    )

            else:
                # JSON не извлечён — только ошибка
                print(f"❌ Не удалось извлечь JSON после {max_attempts} попыток.")
                full_json = {"УИН документа": generate_document_id()}
                save_errors(
                    {"Ошибка извлечения JSON": True}, full_json, output_dir="errors"
                )

        except Exception as e:
            # На случай, если упало что-то вне попыток (например, load_text)
            print(f"❌ Критическая ошибка при обработке файла: {e}")
            full_json = {"УИН документа": generate_document_id()}
            save_errors({"Критическая ошибка": str(e)}, full_json, output_dir="errors")
