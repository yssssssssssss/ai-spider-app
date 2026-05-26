# JOYCODE.md — Repository Guide

## Project Overview

AI-driven Android mobile app automation suite for e-commerce platforms (Taobao, PDD). Provides screenshot capture, image cropping, and VLM-powered UI interaction via multiple driver backends.

## Project Structure

```
├── config.py                 # Centralized config: paths, Appium caps, keyword
├── step1-down_img.py         # Legacy Appium scroll-screenshot (unittest-based)
├── step2-cut_img.py          # OpenCV image cropper: detects non-white regions
├── run_workflow.py           # uiautomator2 workflow engine with popup/dedup
├── run_workflow_vlm.py       # VLM (AutoGLM) + uiautomator2 hybrid workflow
├── run_hybrid.py             # AutoGLM navigation + uiautomator2 scroll loop
├── run_autoglm.py            # Pure AutoGLM natural-language task runner
├── taobao.ipynb              # Jupyter notebook (legacy reference)
├── Open-AutoGLM/             # Git submodule: AI phone-agent framework
│   ├── phone_agent/          # Core agent, model client, action handlers
│   ├── requirements.txt
│   └── setup.py
└── data/                     # Output screenshots (keyword/base, keyword/cropped)
```

## Tech Stack

- **Language**: Python 3.12
- **Drivers**: Appium (legacy), uiautomator2 (primary), AutoGLM/VLM (AI-powered)
- **Vision**: OpenCV, Pillow, perceptual hashing for deduplication
- **Deps**: `Pillow>=12.0.0`, `openai>=2.9.0`, `requests>=2.31.0`

## Build / Run Commands

```bash
# 1. Install submodule dependencies
pip install -e Open-AutoGLM/

# 2. Legacy Appium scroll-screenshot
python step1-down_img.py

# 3. Crop screenshots
python step2-cut_img.py [input_path] [output_dir]

# 4. Workflow engine (rule-based)
python run_workflow.py

# 5. VLM-powered workflow
export PHONE_AGENT_BASE_URL="https://..."
python run_workflow_vlm.py --model autoglm-phone-9b

# 6. Hybrid: AutoGLM navigate + uiautomator2 scroll
python run_hybrid.py --keyword "智能手表" --scrolls 60

# 7. Pure AutoGLM task
python run_autoglm.py "打开淘宝搜索智能手表并截图"
```

## Coding Conventions

- **Configuration**: All paths and caps live in `config.py`. Use `os.path.join` and `os.getenv` for portability; never hardcode absolute paths.
- **Imports**: Group as `stdlib > third-party > local`. Insert `Open-AutoGLM` via `sys.path.insert(0, ...)` when needed.
- **Naming**: `snake_case` for variables/functions, `PascalCase` for classes, `UPPER_CASE` for module-level constants.
- **Comments**: Docstrings in Chinese. Keep log/print messages bilingual (emoji + Chinese) for readability.
- **Error Handling**: Wrap UI interactions in `try/except`; print warnings with `⚠️` prefix instead of raising.

## Testing Guidelines

- No formal test suite yet. `step1-down_img.py` uses `unittest` as a runner scaffold.
- Validate manually: ensure Appium server (`localhost:4723`) or `adb` device is connected before running.
- Check `data/` output: screenshots should increment filenames (`{keyword}_{n}.png`) and cropped images should be square-ish (aspect ratio 0.95–1.05).
- When modifying `Open-AutoGLM/`, run its built-in check: `python Open-AutoGLM/main.py --check`.

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `TB_KEYWORD` | Search keyword (default: `智能手表`) |
| `APPIUM_SERVER_URL` | Appium endpoint (default: `http://localhost:4723`) |
| `PHONE_AGENT_BASE_URL` | VLM API base URL |
| `PHONE_AGENT_MODEL` | VLM model name (default: `autoglm-phone-9b`) |
| `PHONE_AGENT_API_KEY` | VLM API key |
| `PHONE_AGENT_DEVICE_ID` | Optional target device serial |
