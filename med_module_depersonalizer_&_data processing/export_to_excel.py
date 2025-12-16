import os
import sqlite3
import pandas as pd


def export_database_to_excel(
    db_name="personal_data.db", output_file="personal_data_export.xlsx"
):
    """
    Экспортирует таблицу 'patients' из SQLite-базы в Excel-файл.

    Аргументы:
        db_name (str): Имя файла базы данных (в той же директории).
        output_file (str): Имя выходного Excel-файла.
    """
    print("Внимание, это может занять значительное время.")

    # Проверяем, существует ли база
    if not os.path.exists(db_name):
        raise FileNotFoundError(
            f"База данных '{db_name}' не найдена в текущей директории."
        )

    try:
        # Подключаемся и читаем таблицу patients
        with sqlite3.connect(db_name) as conn:
            print("Чтение данных из таблицы 'patients'...")
            df = pd.read_sql_query("SELECT * FROM patients", conn)

        # Сохраняем в Excel
        df.to_excel(output_file, sheet_name="patients", index=False)
        print(
            f"\n✅ Данные из таблицы 'patients' успешно экспортированы в: {output_file}"
        )

    except sqlite3.Error as e:
        raise RuntimeError(f"Ошибка при работе с базой данных: {e}")
    except Exception as e:
        raise RuntimeError(f"Ошибка при экспорте в Excel: {e}")


def get_merged_patients_df(db_name="personal_data.db"):
    """
    Возвращает объединённый DataFrame пациентов, сгруппированных по УИН.
    Для каждого столбца берётся первое непустое (и не равное 'не указано' / 'Данные отсутствуют') значение.
    Если таких нет — возвращается первое значение (например, 'не указано').

    :param db_name: путь к базе данных SQLite
    :return: pd.DataFrame — объединённые данные пациентов
    """
    print("Внимание, это может занять значительное время.")
    print("Объединение записей пациентов по УИН с агрегацией всех доступных данных...")

    if not os.path.exists(db_name):
        raise FileNotFoundError(
            f"База данных '{db_name}' не найдена в текущей директории."
        )

    try:
        with sqlite3.connect(db_name) as conn:
            df = pd.read_sql_query("SELECT * FROM patients", conn)

        if df.empty:
            print("Таблица 'patients' пуста.")
            return pd.DataFrame()  # Возвращаем пустой DataFrame

        if "УИН" not in df.columns:
            raise ValueError("В таблице 'patients' отсутствует столбец 'УИН'")

        # Сохраняем порядок столбцов
        columns_order = df.columns.tolist()

        # Список значений, которые считаем "пустыми" / "неинформативными"
        missing_indicators = {
            "не указано",
            "данные отсутствуют",
            "",
            " ",
            "нет данных",
            "unknown",
            "n/a",
            "nan",
        }

        # Приводим всё к строкам
        df = df.astype(str)

        # Функция: определяет, является ли значение "пустым"
        def is_missing(value):
            return value.strip().lower() in missing_indicators

        # Функция агрегации: берёт первое "настоящее" значение, иначе — первое из группы
        def first_non_missing_or_any(series):
            non_missing = series[~series.apply(is_missing)]
            return non_missing.iloc[0] if len(non_missing) > 0 else series.iloc[0]

        # Агрегация по всем столбцам, кроме УИН
        agg_dict = {col: first_non_missing_or_any for col in df.columns if col != "УИН"}
        merged_df = df.groupby("УИН", as_index=False).agg(agg_dict)

        # Восстанавливаем порядок столбцов
        merged_df = merged_df[columns_order]

        print(f"✅ Успешно объединено {len(merged_df)} уникальных пациентов.")
        return merged_df

    except sqlite3.Error as e:
        raise RuntimeError(f"Ошибка при работе с базой данных: {e}")
    except Exception as e:
        raise RuntimeError(f"Ошибка при объединении данных: {e}")


def get_patient_by_uin(uin, db_name="personal_data.db"):
    # Явно указываем порядок столбцов
    preferred_order = [
        "ФИО",
        "Дата рождения",
        "Пол пациента",
        "Возраст пациента на момент госпитализации",
        "Адрес",
        "Номер СНИЛС",
        "Номер полиса ОМС",
        "УИН",
        "Повторная госпитализация",
        "Регион",
        "Название больницы",
        "Дата госпитализации",
        "Дата выписки",
        "Дата смерти",
        "УИН документа",
    ]

    try:
        with sqlite3.connect(db_name) as conn:
            # Читаем только нужные столбцы, в нужном порядке
            cols_str = ", ".join([f'"{col}"' for col in preferred_order])
            query = f"SELECT {cols_str} FROM patients WHERE УИН = ?"
            df = pd.read_sql_query(query, conn, params=(str(uin),))

        if df.empty:
            return None

        patient_series = df.iloc[0]
        result_dict = patient_series.to_dict()

        # Вручную создаём упорядоченный словарь
        ordered = {}
        for col in preferred_order:
            if col in result_dict:
                ordered[col] = result_dict[col]
        # Добавляем остальные, если есть
        for k, v in result_dict.items():
            if k not in ordered:
                ordered[k] = v

        return ordered

    except Exception as e:
        raise RuntimeError(f"Ошибка при поиске пациента: {e}")


