from pathlib import Path

BASE_DIR = Path(__file__).parent

try:
    with open(BASE_DIR / "planner_prompt.md", "r", encoding="utf-8") as f:
        planner_prompt = f.read()
except FileNotFoundError:
    planner_prompt = ""

try:
    with open(BASE_DIR / "vector_prompt.md", "r", encoding="utf-8") as f:
        vector_prompt = f.read()
except FileNotFoundError:
    vector_prompt = ""

try:
    with open(BASE_DIR / "spatial_prompt.md", "r", encoding="utf-8") as f:
        spatial_prompt = f.read()
except FileNotFoundError:
    spatial_prompt = ""

try:
    with open(BASE_DIR / "answer_prompt.md", "r", encoding="utf-8") as f:
        answer_prompt = f.read()
except FileNotFoundError:
    answer_prompt = ""

try:
    with open(BASE_DIR / "web_prompt.md", "r", encoding="utf-8") as f:
        web_prompt = f.read()
except FileNotFoundError:
    web_prompt = ""

try:
    with open(BASE_DIR / "summary_prompt.md", "r", encoding="utf-8") as f:
        summary_prompt = f.read()
except FileNotFoundError:
    summary_prompt = ""

try:
    with open(BASE_DIR / "router_prompt.md", "r", encoding="utf-8") as f:
        router_prompt = f.read()
except FileNotFoundError:
    router_prompt = ""
