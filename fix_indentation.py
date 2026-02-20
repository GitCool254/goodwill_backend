import re

# Paths
INPUT_FILE = "app.py"
OUTPUT_FILE = "app_fixed.py"

with open(INPUT_FILE, "r", encoding="utf-8") as f:
    lines = f.readlines()

fixed_lines = []
for line in lines:
    stripped = line.strip()

    # Skip empty lines
    if not stripped:
        fixed_lines.append(line)
        continue

    # --- Fix multiple statements on one line (;) ---
    if ";" in line and not line.lstrip().startswith("#"):
        parts = line.split(";")
        indent = len(line) - len(line.lstrip())
        for part in parts:
            part = part.strip()
            if part:
                fixed_lines.append(" " * indent + part + "\n")
        continue

    # --- Fix inline if with multiple statements ---
    # e.g., if cond: do_this(); do_that()
    inline_if_match = re.match(r"^(\s*)if\s+.*:\s+(.+)", line)
    if inline_if_match:
        indent, stmt = inline_if_match.groups()
        # If multiple statements separated by comma or spaces
        stmts = re.split(r"\s{2,}|;", stmt)
        fixed_lines.append(f"{indent}{line.lstrip().split(':')[0]}:\n")
        for s in stmts:
            s = s.strip()
            if s:
                fixed_lines.append(f"{indent}    {s}\n")
        continue

    # Otherwise, keep line
    fixed_lines.append(line)

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    f.writelines(fixed_lines)

print(f"✅ Indentation fixed and saved to {OUTPUT_FILE}")
