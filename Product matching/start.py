"""
Поиск похожих товарных наименований по запросу пользователя с использованием Streamlit

Приложение использует:
- Обработанный список оригинальных наименований (`vink_names`)
- BM25-модель для поиска кандидатов
- FastText-модель для ранжирования кандидатов по косинусному сходству эмбеддингов

Основной функционал:
- Ввод текстового запроса пользователем
- Выбор количества похожих товаров для отображения (от 1 до 10)
- Отображение таблицы с наиболее похожими наименованиями, отсортированной по убыванию сходства

Функции:
--------
- `init_models`: инициализация и кэширование необходимых моделей и данных
- `match_query`: поиск и ранжирование товаров по введённому запросу
"""

import streamlit as st
from utils.dataset_utils import prepare_processed_and_synthetic_datasets
from utils.bm25_utils import prepare_bm25_model
from utils.fasttext_utils import train_and_save_fasttext_model
from utils.matching_utils import match_query
from config import DATA_PATH

# Предварительная инициализация моделей
@st.cache_resource
def init_models():
    """
    Инициализирует и кэширует ресурсы: обработанный список наименований товаров,
    BM25-модель и FastText-модель, чтобы ресурсоёмкие операции выполнялись 
    только один раз при первом запуске.
    """

    vink_names, _ = prepare_processed_and_synthetic_datasets(csv_path=DATA_PATH)
    bm25_model = prepare_bm25_model()
    fasttext_model = train_and_save_fasttext_model('data/synthetic_data.csv')
    return vink_names, bm25_model, fasttext_model

st.title("🔍 Поиск похожих товаров")

# Инициализируем модели
vink_names, bm25_model, fasttext_model = init_models()

# Форма для ввода запроса
with st.form("search_form"):
    st.markdown("<h5>Введите наименование товара:</h5>", unsafe_allow_html=True)
    query = st.text_input(
        "Введите наименование товара", 
        placeholder="Например, ПВХ ECO-FIX 1050х2450х6мм прозрачный",
        label_visibility="collapsed"
        )

    # Оформление выпадающего списка и кнопки "Найти"
    st.markdown("<h6>Сколько товаров показать:</h6>", unsafe_allow_html=True)
    col1, col2 = st.columns([0.15, 1])  # пропорции

    with col1:
        n_top = st.selectbox(
            "Сколько товаров показать",  
            options=list(range(1, 11)), 
            index=4,
            label_visibility="collapsed"  
        )


    with col2:
        submit = st.form_submit_button("Найти")


# Обработка после нажатия кнопки
if submit and query:
    st.markdown("<h6>Результаты поиска (по убыванию сходства):</h6>", unsafe_allow_html=True)
    result_df = match_query(query_text=query, vink_names=vink_names, bm25_model=bm25_model, fasttext_model=fasttext_model, n_top=n_top)
    
    result_df["Сходство"] = result_df["Сходство"].round(3)
    st.dataframe(result_df, use_container_width=True, hide_index=True)