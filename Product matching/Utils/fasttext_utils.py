
import os
import random
import numpy as np
import pandas as pd
from tqdm import tqdm
from gensim.models import FastText
from nltk.tokenize import word_tokenize
from utils.text_utils import preprocess_text
from config import DATA_PATH


def train_and_save_fasttext_model(csv_path=DATA_PATH, model_save_path='models/fasttext_model_full.model', vector_size=200, epochs=5):    
    """
    Обучает FastText-модель на паре оригинальных и синтетических наименований товаров 
    или загружает уже обученную модель из файла, если она существует.

    Модель обучается на тексте, составленном из объединения колонок 'vink_name' и 'vink_name_synt'.
    Каждый текст предварительно очищается и токенизируется. После обучения модель сохраняется на диск.

    Возвращает:
    -----------
    gensim.models.FastText
        Обученная или загруженная FastText-модель.
    """

    if os.path.exists(model_save_path):
        print(f"FastText-модель на месте, обучение не требуется")
        return FastText.load(model_save_path)

    df = pd.read_csv(csv_path)

    print(f"Приступаем к обучению FastText-модели на {df.shape[0]} строках")

    def create_corpus(df, col1, col2):
        """
        Создаёт корпус для обучения модели FastText из двух текстовых колонок датафрейма.

        Для каждой строки объединяет значения двух указанных колонок, применяет предобработку
        текста и токенизацию, после чего добавляет результат в список. Используется для
        генерации обучающего корпуса на паре оригинального и синтетического названия товара.

        Возвращает:
        -----------
        Список токенизированных и предобработанных строк, готовых к обучению модели FastText.
        """

        corpus = []
        for _, row in tqdm(df.iterrows(), total=df.shape[0], desc="Создание корпуса"):
            text = f"{row[col1]} {row[col2]}"
            processed = preprocess_text(text)
            corpus.append(word_tokenize(processed))
        return corpus

    corpus = create_corpus(df, 'vink_name', 'vink_name_synt')

    # Фиксируем воспроизводимость результатов и обучаем модель
    SEED = 42
    random.seed(SEED)
    np.random.seed(SEED)

    class TqdmCorpus:
        def __init__(self, corpus): self.corpus = corpus
        def __iter__(self): return (doc for doc in tqdm(self.corpus, desc="Обучение FastText"))

    model = FastText(
        sentences=TqdmCorpus(corpus),
        vector_size=vector_size,
        window=5,
        epochs=epochs,
        seed=SEED,
        workers=1
    )

    model.save(model_save_path)
    print(f"FastText-модель сохранена в {model_save_path}")

    return model
