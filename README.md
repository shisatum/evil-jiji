# Jiji

An agentic desktop pet that watches your screen and offers sardonic help. Powered by a vision LLM.

## Features

- **Clippy mode** — Jiji glances at your screen and comments on what you're doing
- **Agentic mode** — Give Jiji a task and it will autonomously click, type, and navigate your desktop

## Setup

### 1. Install Python 3

Download and install Python 3.10 or newer from https://www.python.org/downloads/

> ⚠️ During installation, check **"Add Python to PATH"** before clicking Install.

Verify it worked by opening a terminal and running:
```bash
python --version
```

### 2. Install dependencies

```bash
pip install pillow mss pyautogui requests keyboard numpy pystray
```

### 3. Choose a vision backend

Jiji supports three backends, configurable via the **system tray icon → Settings**:

| # | Backend | Notes |
|---|---------|-------|
| 1 | **Ollama v0.24.0** (recommended) | Best local quality, runs fully offline |
| 2 | **Groq** (cloud) | Fast, free tier is plenty |
| 3 | **Local llama-cpp** | Offline, but currently broken — see warning below |

---

## Backend 1 — Ollama with Llama 3.2 Vision (recommended)

The best balance of quality and simplicity for local use.

Requires **Ollama v0.24.0** — llama3.2-vision is broken in Ollama 0.30.x.

1. **Uninstall your current Ollama** via Windows Settings → Apps → Ollama → Uninstall.  
   Your pulled models in `C:\Users\<you>\.ollama\models` will survive.

2. **Download the v0.24.0 installer:**  
   👉 https://github.com/ollama/ollama/releases/tag/v0.24.0  
   Grab `OllamaSetup.exe` and run it.

3. **Pull the model:**
   ```bash
   ollama pull llama3.2-vision
   ```

4. In the **Settings menu** (system tray → Settings → Backend), select **Ollama**.

> **Tip:** Ollama auto-updates in the background. To stay on v0.24.0, dismiss any "Update available" prompts.

---

## Backend 2 — Groq (cloud)

Fast cloud inference with a generous free tier. Requires an internet connection.

1. Get a free API key at https://console.groq.com
2. In the **Settings menu** (system tray → Settings), select **Groq** as the backend and paste your API key.

---

## Backend 3 — Local llama-cpp-python

> [!WARNING]
> **This backend does not currently work with Llama 3.2 Vision.** The mllama architecture is broken in recent llama.cpp releases. Use Ollama v0.24.0 or Groq instead.
>
> This will be the recommended fully-offline path once the upstream regression is fixed.

For when it does work:

### 1. Download the model

Get the **Q4_K_M** quant (~6 GB) from HuggingFace — the only quant that fits in 8 GB VRAM:

👉 https://huggingface.co/leafspark/Llama-3.2-11B-Vision-Instruct-GGUF

Download: `Llama-3.2-11B-Vision-Instruct-Q4_K_M.gguf`

### 2. Install llama-cpp-python with CUDA support

```bash
pip install "llama-cpp-python[server]" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

> For a different CUDA version, replace `cu121` with `cu118`, `cu124`, etc.  
> Check your version with: `nvcc --version`

### 3. Start the server

```bash
python -m llama_cpp.server \
  --model "C:\path\to\Llama-3.2-11B-Vision-Instruct-Q4_K_M.gguf" \
  --n_gpu_layers -1 \
  --n_ctx 4096 \
  --port 8000
```

Keep this terminal open while Jiji is running.

### 4. Select Local in Settings

In the **Settings menu** (system tray → Settings → Backend), select **Local llama-cpp**.

---

## Running Jiji

```bash
python main.py
```

Or just double-click `main.py` in File Explorer.

- **Left-click** Jiji to trigger a screen comment
- **Right-click** Jiji to give it a task or ask a question
- **Esc** cancels the current task (press again to quit)
- **System tray icon** → Settings to configure the backend and other options
- Jiji can be dragged anywhere on screen
