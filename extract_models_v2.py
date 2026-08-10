import os

app_file = "app.py"
models_file = "models.py"

with open(app_file, "r", encoding="utf-8") as f:
    lines = f.readlines()

models_lines = []
new_app_lines = []

in_models_1 = False
in_models_2 = False

for i, line in enumerate(lines):
    # Model block 1 (lines 180 to 678 approx)
    if "class Area(db.Model):" in line:
        in_models_1 = True
    
    if in_models_1:
        if line.startswith("# ==================== RUTAS DE LA"):
            in_models_1 = False
            new_app_lines.append(line)
        else:
            models_lines.append(line)
            continue
            
    # Model block 2 (lines 3307 to 3461 approx)
    if "class HallazgoSistemaNormativo(db.Model):" in line:
        in_models_2 = True
    
    if in_models_2:
        if "from modulos.rutas_hallazgos import hallazgos_bp" in line:
            in_models_2 = False
            new_app_lines.append(line)
        else:
            models_lines.append(line)
            continue
            
    # If we get here, it belongs to app.py
    if not in_models_1 and not in_models_2:
        new_app_lines.append(line)

with open("models.py", "w", encoding="utf-8") as f:
    f.write("from extensions import db\n")
    f.write("from datetime import datetime\n\n")
    f.writelines(models_lines)

with open("app_new.py", "w", encoding="utf-8") as f:
    f.writelines(new_app_lines)

print(f"Extracted {len(models_lines)} lines to models.py")
print(f"app_new.py has {len(new_app_lines)} lines")
