"""
Модуль для подготовки обработанного и синтетического датасетов.

Содержит функции для:
- Модификации текстовых наименований с помощью различных эвристик .
- Генерации синтетических наименований товаров на основе оригинальных.
- Подготовки обработанного списка товаров и соответствующих синтетических вариантов.

Сохраняет:
- `data/vink_names.joblib` — список оригинальных названий товаров.
- `data/synthetic_data.csv` — таблица с оригинальными и синтетическими наименованиями.

Константы:
- `DATA_PATH` — путь к исходному CSV с товарами (задается в config.py).
"""

import os
import re
import random
import pandas as pd
from tqdm import tqdm
import joblib
from config import DATA_PATH

# Пути к исходному, обработанному и синтетическому датасетам
GOODS_DATA_PATH = DATA_PATH
VINK_NAMES_PATH = 'data/vink_names.joblib'
SYNTHETIC_DATA_PATH = 'data/synthetic_data.csv'

# ---------- Функции модификации наименований ---------- #

def remove_numbers(name):
    return re.sub(r'\d+', '', name).strip() or name

def keep_only_numbers(name):
    numbers = re.findall(r'\d+', name)
    return ' '.join(numbers) if numbers else name

def shuffle_words(name):
    words = name.split()
    random.shuffle(words)
    return ' '.join(words)

def remove_random_words(name):
    words = name.split()
    num_to_remove = random.randint(1, min(3, len(words)))
    for _ in range(num_to_remove):
        if words:
            words.pop(random.randint(0, len(words) - 1))
    return ' '.join(words)

def remove_english_words_and_shuffle(name):
    words = [word for word in name.split() if not re.match(r'[A-Za-z]+', word)]
    random.shuffle(words)
    return ' '.join(words)

def remove_random_numbers(name):
    words = name.split()
    words = [word for word in words if not word.isdigit() or random.random() > 0.5]
    return ' '.join(words)

def remove_russian_words_and_shuffle(name):
    words = [word for word in name.split() if not re.match(r'[А-Яа-я]+', word)]
    random.shuffle(words)
    return ' '.join(words)

def remove_numbers_and_shuffle(name):
    return shuffle_words(remove_numbers(name))

def keep_only_numbers_and_shuffle(name):
    return shuffle_words(keep_only_numbers(name))

def remove_random_numbers_and_shuffle(name):
    return shuffle_words(remove_random_numbers(name))

mod_functions = [
    remove_numbers,
    keep_only_numbers,
    shuffle_words,
    remove_random_words,
    remove_english_words_and_shuffle,
    remove_random_numbers,
    remove_russian_words_and_shuffle,
    remove_numbers_and_shuffle,
    keep_only_numbers_and_shuffle,
    remove_random_numbers_and_shuffle
]

# ---------- Генерация синтетических данных ---------- #

def generate_synthetic_names(df, column='vink_name', k=10):
    """
    Генерирует синтетические варианты наименований товаров с помощью случайных модификаций.

    Для каждой строки в указанной колонке датафрейма `df` применяется `k` случайно выбранных
    функций модификации текста из заранее заданного списка `mod_functions`. Каждое изменение
    сохраняется вместе с оригинальным наименованием в выходной датафрейм.

    Возвращает:
    -----------
    pd.DataFrame
        Датафрейм с двумя колонками:
        - 'vink_name' — оригинальное наименование
        - 'vink_name_synt' — синтетически модифицированное наименование
    """
    synthetic_data = []

    for name in tqdm(df[column].tolist(), desc="Генерация синтетических наименований"):
        sampled_funcs = random.choices(mod_functions, k=k)
        for func in sampled_funcs:
            variant = func(name)
            if variant.strip():
                synthetic_data.append({'vink_name': name, 'vink_name_synt': variant})

    return pd.DataFrame(synthetic_data)


# ---------- Основная функция подготовки ---------- #

def prepare_processed_and_synthetic_datasets(csv_path=DATA_PATH):
    """
    Загружает и подготавливает обработанный и синтетический датасеты наименований товаров.

    Если файлы с обработанными и синтетическими данными уже существуют, они загружаются.
    В противном случае функция читает исходный CSV-файл, очищает данные, фильтрует неподходящие
    наименования и генерирует синтетические варианты с помощью набора модификаций. Результаты
    сохраняются на диск для повторного использования.

    Возвращает:
    -----------
    vink_names : list of str
        Список уникальных, очищенных наименований товаров.
    synthetic_data : pd.DataFrame
        Датафрейм с синтетически изменёнными наименованиями.
    """

    if os.path.exists(VINK_NAMES_PATH) and os.path.exists(SYNTHETIC_DATA_PATH):
        print("Обработанный и синтетический датасет на месте, подготовка не требуется.")
        vink_names = joblib.load(VINK_NAMES_PATH)
        synthetic_data = pd.read_csv(SYNTHETIC_DATA_PATH)
        return vink_names, synthetic_data

    if not os.path.exists(csv_path):
        raise FileNotFoundError(f"Исходный файл не найден: {csv_path}")

    print("Загружаем исходные данные и готовим обработанный и синтетический датасеты...")

    # Подготовка обработанного датасета
    goods = pd.read_csv(csv_path)
    goods = goods[['sku_id', 'sku_name']].drop_duplicates().dropna()
    goods.columns = ['vink_id', 'vink_name']

    bad_names = {'ТЕСТ', 'v', 'test', 'тест', 'Наклейка', 'Образцы', 'Канцелярия', 'Этикетка'}
    goods = goods[~goods['vink_name'].isin(bad_names)]

    vink_names = goods['vink_name'].tolist()

    # Генерация синтетических данных
    synthetic_data = generate_synthetic_names(goods)

    os.makedirs('data', exist_ok=True)
    joblib.dump(vink_names, VINK_NAMES_PATH)
    synthetic_data.to_csv(SYNTHETIC_DATA_PATH, index=False)

    print(f"Обработанный и синтетический датасеты сохранены в: {VINK_NAMES_PATH} и {SYNTHETIC_DATA_PATH}")

    return vink_names, synthetic_data