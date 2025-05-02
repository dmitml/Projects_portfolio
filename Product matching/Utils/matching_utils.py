import numpy as np
import pandas as pd
from nltk.tokenize import word_tokenize
from sklearn.metrics.pairwise import cosine_similarity
from utils.text_utils import preprocess_text, get_embedding

pd.set_option('display.max_colwidth', None)

def match_query(query_text, vink_names, bm25_model, fasttext_model, k_top=10, n_top=5):
    """
    Выполняет сопоставление входного текстового запроса с наименованиями товаров, используя 
    BM25 для отбора кандидатов и FastText для ранжирования по косинусному сходству.

    Сначала BM25 выбирает k_top наиболее релевантных наименований товаров. Затем 
    считается косинусное сходство между эмбеддингом запроса и эмбеддингами кандидатов 
    с помощью FastText. Возвращаются n_top наиболее похожих результатов.

    Возвращает:
    -----------
    pandas.DataFrame
        Таблица с n_top наиболее похожими наименованиями товаров и их сходством:
        - '№' — порядковый номер
        - 'Наименование товара' — отобранный кандидат
        - 'Сходство' — косинусное сходство с запросом
    """

    # Проверка наличия обработанного датасета
    if not vink_names or len(vink_names) == 0:
        raise ValueError("Список vink_names пуст. Проверь, что данные загружены корректно.")

    # Проверка наличия моделей
    if bm25_model is None:
        raise ValueError("Модель BM25 не загружена.")
    if fasttext_model is None or not hasattr(fasttext_model, 'wv'):
        raise ValueError("FastText-модель не загружена или повреждена.")

    embeddings = fasttext_model.wv

    # Обработка запроса
    query_clean = preprocess_text(query_text)
    query_tokens = word_tokenize(query_clean)

    # Получаем кандидатов из BM25 
    scores = bm25_model.get_scores(query_tokens)
    top_indices = np.argsort(scores)[::-1][:k_top]
    bm25_candidates = [vink_names[i] for i in top_indices]

    # Получаем эмбеддинги и доранжируем кандидатов
    query_vec = get_embedding(query_text, embeddings).reshape(1, -1)

    candidate_vectors = [
        get_embedding(name, embeddings).reshape(1, -1)
        for name in bm25_candidates
    ]
    similarities = [cosine_similarity(query_vec, vec)[0][0] for vec in candidate_vectors]

    df = pd.DataFrame({
        'Наименование товара': bm25_candidates,
        'Сходство': similarities,
    }).sort_values(by='Сходство', ascending=False).head(n_top)

    # Добавляем колонку "№"
    df.insert(0, '№', range(1, len(df) + 1))
    df = df.reset_index(drop=True)

    return df
