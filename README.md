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

### Choosing a vision backend

Jiji supports three backends. Set the flags at the top of `main.py`:

| Backend | Flag | Notes |
|---------|------|-------|
| Local llama-cpp | `USE_LOCAL = True` | Runs fully offline on your GPU |
| Groq (cloud) | `USE_GROQ = True` | Fast, free tier is plenty |
| Ollama (local) | both `False` | Requires Ollama running locally |

---

## Local model setup (llama-cpp-python)

> [!WARNING]
> **The local llama-cpp-python method does not currently work with Llama 3.2 Vision.** The mllama architecture is broken in recent llama.cpp releases. Preferred alternatives:
> - **Groq** (cloud, free tier) — fastest and most reliable
> - **Ollama v0.24.0 + llama3.2-vision** — best local quality
> - **Ollama (any version) + LLaVA** — easiest local setup

This will be the recommended offline path once the mllama regression is fixed upstream.

### 1. Download the model

Get the **Q4_K_M** quant (~6 GB) from HuggingFace — it's the only quant that fits in 8 GB VRAM:

👉 https://huggingface.co/leafspark/Llama-3.2-11B-Vision-Instruct-GGUF

Download: `Llama-3.2-11B-Vision-Instruct-Q4_K_M.gguf`

### 2. Install llama-cpp-python with CUDA support

```bash
pip install "llama-cpp-python[server]" --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
```

> For a different CUDA version, replace `cu121` with `cu118`, `cu124`, etc. to match your driver.  
> Check your CUDA version with: `nvcc --version`

### 3. Start the server

```bash
python -m llama_cpp.server \
  --model "C:\path\to\Llama-3.2-11B-Vision-Instruct-Q4_K_M.gguf" \
  --n_gpu_layers -1 \
  --n_ctx 4096 \
  --port 8000
```

- `--n_gpu_layers -1` offloads all layers to GPU (fastest)
- `--n_ctx 4096` sets the context window (increase to 8192 if you have headroom)
- Keep this terminal open while Jiji is running

### 4. Enable local mode in Jiji

At the top of `main.py`, set:

```python
USE_LOCAL = True
```

---

## Groq setup (cloud)

1. Get a free API key at https://console.groq.com
2. Set at the top of `main.py`:

```python
USE_GROQ    = True
GROQ_API_KEY = "your-key-here"
```

---

## Ollama setup (local)

Leave both `USE_LOCAL` and `USE_GROQ` set to `False` (the default).

### Option A — LLaVA (works on any Ollama version)

1. Install Ollama from https://ollama.com
2. Pull LLaVA:
   ```bash
   ollama pull llava
   ```
3. In `main.py`, set:
   ```python
   OLLAMA_MODEL = "llava"
   ```

### Option B — Llama 3.2 Vision (requires Ollama v0.24.0)

Llama 3.2 Vision is broken in Ollama 0.30.x due to a regression in mllama architecture support. Roll back to v0.24.0 to use it.

1. **Uninstall your current Ollama** via Windows Settings → Apps → Ollama → Uninstall.  
   Your pulled models in `C:\Users\<you>\.ollama\models` will survive.

2. **Download the v0.24.0 installer:**  
   👉 https://github.com/ollama/ollama/releases/tag/v0.24.0  
   Grab `OllamaSetup.exe` and run it.

3. **Pull the model:**
   ```bash
   ollama pull llama3.2-vision
   ```

4. In `main.py`, set:
   ```python
   OLLAMA_MODEL = "llama3.2-vision"
   ```

> **Tip:** Ollama auto-updates in the background. To stay on v0.24.0, dismiss any "Update available" prompts.

---

## Running Jiji

```bash
python main.py
```

- **Left-click** Jiji to trigger a screen comment
- **Right-click** Jiji to give it a desktop task
- **Esc** cancels the current task (press again to quit)
- Jiji can be dragged anywhere on screen
