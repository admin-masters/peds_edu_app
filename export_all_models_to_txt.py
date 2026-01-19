import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(BASE_DIR, "ALL_DJANGO_MODELS.txt")

EXCLUDE_DIRS = {"venv", "env", ".venv", "__pycache__", "migrations"}

def export_models_to_txt(base_dir):
    with open(OUTPUT_FILE, "w", encoding="utf-8") as output:
        output.write("DJANGO MODELS EXPORT\n")
        output.write("=" * 80 + "\n\n")

        for root, dirs, files in os.walk(base_dir):
            # Skip unwanted directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]

            if "models.py" in files:
                model_path = os.path.join(root, "models.py")
                app_name = os.path.basename(root)

                output.write(f"\n\nAPP: {app_name}\n")
                output.write("-" * 80 + "\n")
                output.write(f"FILE: {model_path}\n")
                output.write("-" * 80 + "\n\n")

                with open(model_path, "r", encoding="utf-8") as model_file:
                    output.write(model_file.read())

    print(f"✅ All models.py exported to {OUTPUT_FILE}")


if __name__ == "__main__":
    export_models_to_txt(BASE_DIR)
