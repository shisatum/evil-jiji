# Jiji

An agentic desktop pet that watches your screen and offers sardonic help. Powered by a vision LLM.

## Features

- **Clippy mode** — Jiji glances at your screen and comments on what you're doing
- **Agentic mode** — Give Jiji a task and it will autonomously click, type, and navigate your desktop

## Setup

### Dependencies

```bash
pip install pillow mss pyautogui requests
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

This is the recommended path for running fully offline on a GPU with 6–8 GB VRAM.

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

1. Install Ollama from https://ollama.com
2. Pull a vision model:
   ```bash
   ollama pull llava
   ```
3. Leave both `USE_LOCAL` and `USE_GROQ` set to `False`

> **Note:** llama3.2-vision is broken in Ollama 0.30.4+. Use llava, or roll back to Ollama v0.24.0 for llama3.2-vision support.

---

## Running Jiji

```bash
python main.py
```

- **Left-click** Jiji to trigger a screen comment
- **Right-click** Jiji to give it a desktop task
- **Esc** cancels the current task (press again to quit)
- Jiji can be dragged anywhere on screen
