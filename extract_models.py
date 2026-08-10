import os

app_file = "app.py"
models_file = "models.py"

with open(app_file, "r", encoding="utf-8") as f:
    lines = f.readlines()

models_lines = []
new_app_lines = []

in_models_section = False
in_hallazgos_section = False

for i, line in enumerate(lines):
    # Models part 1: 180 to 678
    # Let's detect by class Area(db.Model)
    if "class Area(db.Model):" in line:
        in_models_section = True
    
    if in_models_section:
        if line.startswith("# ==================== RUTAS ===================="):
            in_models_section = False
            new_app_lines.append(line)
        else:
            models_lines.append(line)
    elif "class HallazgoSistemaNormativo(db.Model):" in line:
        in_hallazgos_section = True
        models_lines.append(line)
    elif in_hallazgos_section:
        if line.startswith("# ==================== STARTUP ===================="):
            in_hallazgos_section = False
            new_app_lines.append(line)
        else:
            models_lines.append(line)
    else:
        new_app_lines.append(line)

with open("models.py", "w", encoding="utf-8") as f:
    f.write("from extensions import db\n")
    f.write("from datetime import datetime\n\n")
    f.writelines(models_lines)

with open("app_new.py", "w", encoding="utf-8") as f:
    f.writelines(new_app_lines)

print("Extraction complete. Check models.py and app_new.py")
