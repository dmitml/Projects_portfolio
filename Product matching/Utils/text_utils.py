"""
Модуль для предобработки текста и извлечения эмбеддингов.

Основные функции:
1. `preprocess_text` — очищает текст от лишних символов, выполняет замену слов по словарю и приводит слова к их базовой форме.
2. `get_embedding` — извлекает эмбеддинг для переданного текста с использованием предоставленных векторных представлений слов.

Используемые библиотеки:
- `re`: для работы с регулярными выражениями.
- `nltk`: для токенизации и стемминга.
- `numpy`: для работы с векторами.

Зависимости:
1. NLTK: токенизатор `punkt` загружается автоматически при первом использовании.
"""

import re
from nltk.stem.snowball import SnowballStemmer
from nltk.tokenize import word_tokenize
import nltk
import numpy as np

# Автоматическая загрузка токенизатора punkt при необходимости
try:
    nltk.data.find("tokenizers/punkt")
except LookupError:
    nltk.download("punkt")

stemmer = SnowballStemmer(language='russian')
replacement_dict = {
    "прозр": "прозрачный",
    "проз": "прозрачный",
    "vi": "vilaseca"
}
stop_words = {'м', 'мм', 'мк', 'мкм', 'кг', 'г', 'для', 'на', 'с', 'и', 'плотностью'}

def preprocess_text(text):
    """
    Очищает и обрабатывает текст.

    Функция выполняет следующие операции на входном тексте:
    1. Приводит текст к нижнему регистру.
    2. Удаляет все символы, кроме букв (кириллица и латиница), цифр, пробелов, запятой и точки.
    3. Заменяет повторяющиеся знаки препинания (точки и запятые) между словами на один пробел.
    4. Исправляет формат чисел с разделителями.
    5. Убирает нежелательные пробелы между цифрами и буквами.
    6. Убирает единицу измерения "кг" и все числа, связанные с ней.
    7. Убирает ведущие нули в числах.
    8. Убирает лишние точки в конце текста.
    9. Удаляет стоп-слова.
    10. Заменяет слова по заданному словарю.
    11. Применяет стемминг к словам.

    Возвращает:
    str: Обработанный текст
    """
    text = str(text).lower()
    text = re.sub(r'[^а-яёa-z0-9\s,\.]', ' ', text)
    text = re.sub(r'([^\d])[\.,]+([^\d])', r'\1 \2', text)
    text = re.sub(r'(\d)[\.,]+(\d)', r'\1.\2', text)
    text = re.sub(r'(?<=\d)(?=[а-яa-z])|(?<=[а-яa-z])(?=\d)', ' ', text)
    text = re.sub(r'(\d)\s*[xх]\s*(\d)', r'\1 \2', text)
    text = re.sub(r'\b\d+(\.\d+)?\s*кг\b', ' ', text)
    text = re.sub(r'\b0+(\d+)\b', r'\1', text)
    text = re.sub(r'\.+$', '', text)

    words = text.split()
    words = [word for word in words if word not in stop_words]
    words = [replacement_dict.get(word, word) for word in words]
    words = [stemmer.stem(word) for word in words]

    return ' '.join(words)

def get_embedding(text, wv_embeddings, dim=None):
    """
    Извлекает эмбеддинг для переданного текста.

    Возвращает:
    Усредненный вектор эмбеддингов для слов в тексте или нулевой вектор, если слов нет в модели.

    Примечания:
    - Функция использует токенизацию и предобработку текста, определенные в других частях кода.
    """
        
    if dim is None:
        dim = wv_embeddings.vector_size

    cleaned_text = preprocess_text(text)
    words = word_tokenize(cleaned_text)
    word_vectors = [wv_embeddings[word] for word in words if word in wv_embeddings]

    if not word_vectors:
        return np.zeros(dim)

    return np.mean(word_vectors, axis=0)
