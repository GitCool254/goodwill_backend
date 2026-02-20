import re

with open("app.py", "r", encoding="utf-8") as f:
    lines = f.readlines()

fixed_lines = []
for line in lines:
    stripped = line.strip()
    if not stripped:
        fixed_lines.append(line)
        continue

    # Split multiple statements after colon
    if ":" in line and not line.lstrip().startswith("#"):
        parts = line.split(":")
        if len(parts) > 1:
            indent = len(parts[0]) - len(parts[0].lstrip())
            fixed_lines.append(parts[0] + ":\n")
            rest = ":".join(parts[1:]).strip()
            # Split by ';' if multiple statements
            for stmt in rest.split(";"):
                stmt = stmt.strip()
                if stmt:
                    fixed_lines.append(" " * (indent + 4) + stmt + "\n")
            continue

    fixed_lines.append(line)

with open("app_fixed.py", "w", encoding="utf-8") as f:
    f.writelines(fixed_lines)

print("✅ Pre-fixed indentation saved to app_fixed.py")
