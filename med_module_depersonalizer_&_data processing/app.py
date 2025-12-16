# app.py
import os
import shutil
from flask import Flask, request, render_template, jsonify, send_file
import processor
import export_to_excel

app = Flask(__name__)

# Пути
DATABASE = "personal_data.db"
FULL_EXCEL = "full_patients.xlsx"
MERGED_EXCEL = "merged_patients.xlsx"
PROCESS_FOLDER = "process_files"
CLEANED_FOLDER = "cleaned_docs"
ZIP_ARCHIVE = "cleaned_documents.zip"


# Создаём папки при старте
os.makedirs(PROCESS_FOLDER, exist_ok=True)
os.makedirs(CLEANED_FOLDER, exist_ok=True)


@app.route("/")
def index():
    return render_template("index.html")


# === 1. Загрузка файлов ===
@app.route("/upload_files", methods=["POST"])
def upload_files():
    if "files" not in request.files:
        return jsonify({"error": "Файлы не загружены"}), 400

    files = request.files.getlist("files")
    saved_files = []
    allowed_extensions = {".pdf", ".txt", ".rtf"}

    for file in files:
        if file.filename == "":
            continue
        ext = os.path.splitext(file.filename)[1].lower()
        if ext in allowed_extensions:
            filename = os.path.basename(file.filename)
            filepath = os.path.join(PROCESS_FOLDER, filename)
            file.save(filepath)
            saved_files.append(filename)
        else:
            return jsonify({"error": f"Неподдерживаемый формат: {file.filename}"}), 400

    return jsonify({"uploaded": saved_files})


# === 2. Начать обработку ===
@app.route("/start_processing", methods=["POST"])
def start_processing():
    data = request.get_json()
    region = data.get("region", "").strip()
    allow_duplicates = data.get(
        "allow_duplicates", False
    )  # По умолчанию — не разрешать

    if not region:
        return jsonify({"error": "Укажите регион"}), 400

    try:
        # ✅ Передаём allow_duplicates в функцию обработки
        processor.run_processing_cycle(region=region, allow_duplicates=allow_duplicates)

        # После успешной обработки — очищаем папку process_files
        for filename in os.listdir(PROCESS_FOLDER):
            filepath = os.path.join(PROCESS_FOLDER, filename)
            if os.path.isfile(filepath):
                os.remove(filepath)

        return jsonify(
            {
                "status": "success",
                "message": "Обработка завершена, входные файлы удалены.",
            }
        )
    except Exception as e:
        return jsonify({"error": f"Ошибка при обработке: {str(e)}"}), 500


# === 3. Экспорт всей базы ===
@app.route("/export_full", methods=["POST"])
def export_full():
    try:
        export_to_excel.export_database_to_excel(output_file=FULL_EXCEL)
        return send_file(FULL_EXCEL, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# === 4. Экспорт агрегированных пациентов ===
@app.route("/export_merged", methods=["POST"])
def export_merged():
    try:
        merged_df = export_to_excel.get_merged_patients_df(DATABASE)
        if merged_df.empty:
            return jsonify({"error": "Нет данных для экспорта"}), 400
        merged_df.to_excel(MERGED_EXCEL, index=False)
        return send_file(MERGED_EXCEL, as_attachment=True)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# === 5. Скачать очищенные файлы (ZIP) ===
@app.route("/download_cleaned", methods=["POST"])
def download_cleaned():
    try:
        # Проверяем, есть ли файлы
        cleaned_files = os.listdir(CLEANED_FOLDER)
        if not cleaned_files:
            return jsonify({"error": "Нет очищённых файлов для скачивания"}), 400

        # Создаём ZIP-архив
        shutil.make_archive("cleaned_documents", "zip", CLEANED_FOLDER)

        if not os.path.exists(ZIP_ARCHIVE):
            return jsonify({"error": "Не удалось создать архив"}), 500

        # Удаляем все файлы из cleaned_docs после архивации
        for filename in cleaned_files:
            os.remove(os.path.join(CLEANED_FOLDER, filename))

        # Отправляем ZIP
        return send_file(
            ZIP_ARCHIVE, as_attachment=True, download_name="cleaned_documents.zip"
        )

    except Exception as e:
        return jsonify({"error": f"Ошибка при создании архива: {str(e)}"}), 500


# === 6. Поиск по УИН ===
@app.route("/search_patient", methods=["POST"])
def search_patient():
    uin = request.json.get("uin", "").strip()
    if not uin:
        return jsonify({"error": "Введите УИН"}), 400

    try:
        patient_data = export_to_excel.get_patient_by_uin(uin, DATABASE)
        if patient_data:
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

            ordered_patient = {}
            for field in preferred_order:
                if field in patient_data:
                    ordered_patient[field] = patient_data[field]
            for key, value in patient_data.items():
                if key not in ordered_patient:
                    ordered_patient[key] = value

            return jsonify({"patient": ordered_patient})
        else:
            return jsonify({"error": "Пациент не найден"}), 404
    except Exception as e:
        return jsonify({"error": f"Ошибка базы данных: {str(e)}"}), 500


if __name__ == "__main__":
    print("🌐 Сервер запущен: http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=True)
