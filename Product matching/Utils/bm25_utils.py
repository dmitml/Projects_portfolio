
import os
import joblib
from rank_bm25 import BM25Okapi
from nltk.tokenize import word_tokenize
from utils.text_utils import preprocess_text

def prepare_bm25_model(save_dir_names='data', save_dir_model='models'):
    """
    Обучает BM25-модель на списке товарных наименований.

    Если сериализованная BM25-модель уже существует, она загружается
    с диска. В противном случае модель обучается на предобработанных наименованиях товаров
    и сохраняется в файл для повторного использования.

    Возвращает:
    -----------
    BM25Okapi
        Объект обученной BM25-модели, готовый к использованию для поиска и ранжирования.
        Возвращает None, если отсутствует файл с предобработанными наименованиями.
    """

    model_path = os.path.join(save_dir_model, 'bm25_model.joblib')
    names_path = os.path.join(save_dir_names, 'vink_names.joblib')

    # Создание директории под модель и необходимые проверки 
    if not os.path.exists(save_dir_model):
        os.makedirs(save_dir_model)
        print(f"Создана директория под модель: {save_dir_model}")

    if os.path.exists(model_path):
        print("BM25-модель на месте, обучение не требуется")
        return joblib.load(model_path)

    if not os.path.exists(names_path):
        print("Подготовьте обработанный датасет.")
        return None

    print("Обучаем BM25-модель...")
    vink_names = joblib.load(names_path)
    corpus = [word_tokenize(preprocess_text(name)) for name in vink_names]
    bm25_model = BM25Okapi(corpus)

    joblib.dump(bm25_model, model_path)
    print(f"BM25-модель сохранена в {model_path}")

    return bm25_model