# Jiji v1.24
import tkinter as tk
import keyboard
import ctypes
import pystray
import numpy as np
import os
import datetime
import hashlib
import pyautogui
import mss
import random
import json
import requests
import base64
import math
import re
import threading
from io import BytesIO
from PIL import Image, ImageTk

# --- CONFIGURATION ---
SHOW_RAW_LLM_OUTPUT = True

# Set USE_GROQ = True and paste your key from console.groq.com to use Llama 3.2 Vision.
# The free tier is more than enough for Jiji's usage.
USE_GROQ = False
GROQ_API_KEY = ""
GROQ_MODEL   = "meta-llama/llama-4-scout-17b-16e-instruct"  # or "llama-3.2-90b-vision-preview" for more reasoning

# Local llama-cpp-python server (highest priority when USE_LOCAL = True)
# Run: python -m llama_cpp.server --model <path>.gguf --n_gpu_layers -1 --n_ctx 4096 --port 8000
# Recommended model: leafspark/Llama-3.2-11B-Vision-Instruct-GGUF  Q4_K_M (~6 GB, fits GTX 1070)
USE_LOCAL      = False
LOCAL_BASE_URL = "http://localhost:8000/v1"
LOCAL_MODEL    = "llama3.2-vision"  # cosmetic label sent to the local server

# Local fallback via Ollama (used when USE_GROQ = False and USE_LOCAL = False)
# Requires Ollama v0.24.0 — llama3.2-vision is broken in 0.30.x+
OLLAMA_MODEL = "llama3.2-vision"

# Vision resolution for Clippy mode (left-click screen analysis)
# True  → 1024px PNG  (sharper, recommended for local models)
# False → 512px JPEG  (faster, lower token cost for Groq/cloud)
HIGH_RES_VISION = True

MEMORY_FILE = "jiji_memory.json"  # persists Jiji's recent comments across sessions

pyautogui.FAILSAFE = True

_tray_icon = None

def nuke_process():
    print("\n[KILLSWITCH] Jiji has been vaporized.")
    if _tray_icon is not None:
        try:
            _tray_icon.stop()
            import time
            time.sleep(0.3)
        except Exception:
            pass
    os._exit(0)

def _handle_esc(app):
    """Context-aware killswitch: aborts tasks first, kills process second."""
    app.awaiting_offer = False
    app.btn_frame.pack_forget()
    if app.is_agentic:
        app.exit_agentic_mode()
    elif app.awaiting_input:
        app.task_entry.destroy()
        app.awaiting_input = False
        app.dialogue.pack(pady=5)
        app.awake = False
        app.is_idling = True
        app.change_state("sleep", "*Cancelled*")
        app.root.after(1000, lambda: app.dialogue.config(text="*No thoughts, head empty.*") if not app.awake else None)
    else:
        nuke_process()

class JijiApp:
    def __init__(self, root):
        self.root = root
        self.is_idling = True

        self.is_agentic = False
        self.agentic_task = ""
        self.agentic_queue = []
        self.last_agentic_action = None
        self.action_history = []
        self.awaiting_input = False
        self.awaiting_offer = False
        self.pending_offer = ""
        self.pending_offer_task = ""
        self.recent_comments = []
        self.last_screenshot_hash = ""

        # Lifecycle & Dragging variables
        self.awake = False
        self.actions_remaining = 0
        self.drag_start_x = 0
        self.drag_start_y = 0
        self._dragging = False

        try:
            self.sheet = Image.open("sprites.png").convert("RGBA")
        except FileNotFoundError:
            print("Missing 'sprites.png'. Put it in the same folder.")
            os._exit(1)

        bg_rgba = self.sheet.getpixel((0, 0))
        self.bg_hex = f"#{bg_rgba[0]:02x}{bg_rgba[1]:02x}{bg_rgba[2]:02x}"

        self.build_frames()
        self.current_state = "sleep"
        self.anim_index = 0

        self.win_w = 280

        self.setup_window()

        self._load_memory()
        self.animate()

    def _capture_screenshot(self, callback):
        self.root.withdraw()
        self.root.after(150, lambda: self._do_capture(callback))

    def _do_capture(self, callback):
        with mss.MSS() as sct:
            screenshot = sct.grab(sct.monitors[1])
            img = Image.frombytes("RGB", screenshot.size, screenshot.bgra, "raw", "BGRX")
        self.root.deiconify()
        callback(img)

    def _call_api(self, prompt, img_str, on_result, on_error, json_mode=False, timeout=120, mime="image/jpeg"):
        """Unified vision API call — routes to local llama-cpp server, Groq, or Ollama based on config."""
        if USE_LOCAL:
            payload = {
                "model": LOCAL_MODEL,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_str}"}}
                ]}],
                "stream": False
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            headers = {"Content-Type": "application/json"}
            url = f"{LOCAL_BASE_URL}/chat/completions"
        elif USE_GROQ:
            content = [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{img_str}"}}
            ]
            payload = {
                "model": GROQ_MODEL,
                "messages": [{"role": "user", "content": content}],
                "stream": False
            }
            if json_mode:
                payload["response_format"] = {"type": "json_object"}
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
            url = "https://api.groq.com/openai/v1/chat/completions"
        else:
            payload = {
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "images": [img_str],
                "stream": False
            }
            if json_mode:
                payload["format"] = "json"
            headers = {}
            url = "http://localhost:11434/api/generate"

        def _fetch():
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=timeout)
                if USE_LOCAL or USE_GROQ:
                    resp_json = response.json()
                    if "choices" not in resp_json:
                        err = resp_json.get("error", {})
                        err_type = err.get("type", "")
                        msg = err.get("message", str(resp_json))
                        if err_type == "tokens":
                            retry_after = 60
                            import re as _re
                            import time as _time
                            m = _re.search(r"try again in (?:(\d+)m)?([\d.]+)s", msg)
                            if m:
                                minutes = int(m.group(1)) if m.group(1) else 0
                                seconds = float(m.group(2))
                                retry_after = int(minutes * 60 + seconds) + 2
                            print(f"[Groq rate limit] {msg}\nRetrying in {retry_after}s.")
                            for remaining in range(retry_after, 0, -1):
                                self.root.after(0, lambda r=remaining: self.dialogue.config(
                                    text=f"*Over quota.\nRetrying in {r}s...*"
                                ))
                                _time.sleep(1)
                            self.root.after(0, lambda: self.dialogue.config(text="*Retrying...*"))
                            response2 = requests.post(url, json=payload, headers=headers, timeout=timeout)
                            resp_json = response2.json()
                        else:
                            raise KeyError(f"Groq error: {msg}")
                    result = resp_json["choices"][0]["message"]["content"]
                else:
                    result = response.json().get("response", "")
                self.root.after(0, lambda r=result: on_result(r))
            except Exception as e:
                self.root.after(0, lambda err=e: on_error(err))

        threading.Thread(target=_fetch, daemon=True).start()

    def _load_memory(self):
        try:
            with open(MEMORY_FILE) as f:
                self.recent_comments = json.load(f).get("comments", [])[-15:]
        except (FileNotFoundError, json.JSONDecodeError):
            self.recent_comments = []

    def _save_to_memory(self, comment):
        self.recent_comments.append(comment)
        self.recent_comments = self.recent_comments[-15:]
        try:
            with open(MEMORY_FILE, "w") as f:
                json.dump({"comments": self.recent_comments}, f, indent=2)
        except Exception as e:
            print(f"Memory save error: {e}")

    def _get_screenshot_hash(self, img):
        small = img.resize((64, 64))
        return hashlib.md5(small.tobytes()).hexdigest()

    def prepare_vision_payload(self, img, fmt="JPEG", quality=85):
        """Encodes a screenshot for the vision API at native resolution."""
        buffered = BytesIO()
        if fmt == "PNG":
            img.save(buffered, format="PNG")
        else:
            img.save(buffered, format="JPEG", quality=quality)
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def unmap_coordinates(self, rel_x, rel_y):
        """Converts 0.0-1.0 model coordinates to true screen pixels."""
        tx = int(rel_x * self.screen_w)
        ty = int(rel_y * self.screen_h)
        return max(0, min(self.screen_w - 1, tx)), max(0, min(self.screen_h - 1, ty))

    def get_raw_slice(self, col, row):
        box = (col * 32, row * 32, (col + 1) * 32, (row + 1) * 32)
        crop = self.sheet.crop(box)
        new_size = (crop.width * 3, crop.height * 3)
        return crop.resize(new_size, Image.Resampling.NEAREST)

    def apply_recolor(self, pil_image):
        arr = np.array(pil_image)
        mask = (arr[:, :, 0] > 240) & (arr[:, :, 1] > 240) & (arr[:, :, 2] > 240)
        arr[mask, :3] = [40, 40, 40]
        return ImageTk.PhotoImage(Image.fromarray(arr))

    def build_frames(self):
        raw_frames = {
            "idle": [self.get_raw_slice(0, 0)],
            "sit_up": [self.get_raw_slice(0, 0)],
            "groom": [self.get_raw_slice(1, 0), self.get_raw_slice(0, 0)],
            "scratch": [self.get_raw_slice(2, 0), self.get_raw_slice(0, 0)],
            "yawn": [
                self.get_raw_slice(4, 0), self.get_raw_slice(4, 0),
                self.get_raw_slice(4, 0), self.get_raw_slice(4, 0),
                self.get_raw_slice(0, 0)
            ],
            "sleep": [self.get_raw_slice(5, 0), self.get_raw_slice(6, 0), self.get_raw_slice(5, 0)],
            "shock": [self.get_raw_slice(7, 0)],
            "run_S":  [self.get_raw_slice(0, 1), self.get_raw_slice(1, 1)],
            "run_SE": [self.get_raw_slice(2, 1), self.get_raw_slice(3, 1)],
            "run_E":  [self.get_raw_slice(4, 1), self.get_raw_slice(5, 1)],
            "run_NE": [self.get_raw_slice(6, 1), self.get_raw_slice(7, 1)],
            "run_N":  [self.get_raw_slice(0, 2), self.get_raw_slice(1, 2)],
            "run_NW": [self.get_raw_slice(2, 2), self.get_raw_slice(3, 2)],
            "run_W":  [self.get_raw_slice(4, 2), self.get_raw_slice(5, 2)],
            "run_SW": [self.get_raw_slice(6, 2), self.get_raw_slice(7, 2)],
            "scratch_wall_up":    [self.get_raw_slice(0, 3), self.get_raw_slice(1, 3)],
            "scratch_wall_down":  [self.get_raw_slice(2, 3), self.get_raw_slice(3, 3)],
            "scratch_wall_left":  [self.get_raw_slice(4, 3), self.get_raw_slice(5, 3)],
            "scratch_wall_right": [self.get_raw_slice(6, 3), self.get_raw_slice(7, 3)]
        }

        self.frames = {}
        for state, pil_list in raw_frames.items():
            self.frames[state] = [self.apply_recolor(img) for img in pil_list]

    def setup_window(self):
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.wm_attributes("-transparentcolor", self.bg_hex)
        self.root.configure(bg=self.bg_hex)

        self.screen_w, self.screen_h = pyautogui.size()

        self.win_x = self.screen_w - 300
        self.win_y = self.screen_h - 300
        self.root.geometry(f"{self.win_w}x600+{int(self.win_x)}+{int(self.win_y)}")

        self.frame = tk.Frame(self.root, bg=self.bg_hex, width=self.win_w, height=600)
        self.frame.pack_propagate(False)
        self.frame.pack(fill=tk.BOTH, expand=True)

        self.sprite_label = tk.Label(self.frame, bg=self.bg_hex, borderwidth=0)
        self.sprite_label.pack(pady=(10, 0))

        self.dialogue = tk.Label(self.frame, text="*No thoughts, head empty.*", fg="white", bg="#222222",
                                 font=("Courier", 10, "bold"), wraplength=self.win_w - 20)
        self.dialogue.pack(pady=5)

        for widget in [self.sprite_label, self.dialogue]:
            widget.bind("<ButtonPress-1>", self.start_drag)
            widget.bind("<B1-Motion>", self.do_drag)
            widget.bind("<ButtonRelease-1>", self.on_left_release)
            widget.bind("<Button-3>", self.prompt_agentic)

        # Normal-mode click approval buttons (shown only when Jiji wants to click something)
        self.btn_frame = tk.Frame(self.frame, bg=self.bg_hex)
        self.btn_yes = tk.Button(self.btn_frame, text="OK", bg="#2e7d32", fg="white",
                                 command=self.action_approved, relief="flat")
        self.btn_yes.pack(side=tk.LEFT, padx=5)
        self.btn_no = tk.Button(self.btn_frame, text="NOPE", bg="#c62828", fg="white",
                                command=self.action_denied, relief="flat")
        self.btn_no.pack(side=tk.RIGHT, padx=5)

    def on_left_release(self, event):
        if self._dragging:
            self._dragging = False
            return
        if self.awaiting_offer and not self.pending_offer:
            self.awaiting_offer = False
            self.awake = False
            self.is_idling = True
            self.change_state("sleep", "*Fine.*")
        elif not self.awake:
            self.wake_up()

    def wake_up(self):
        self.awake = True
        self.actions_remaining = 1
        self.is_idling = False
        self.change_state("yawn", "*Yawns*")
        self.root.after(2000, self.agent_see)

    def start_drag(self, event):
        self._dragging = False
        self.drag_start_x = event.x_root
        self.drag_start_y = event.y_root

    def do_drag(self, event):
        self._dragging = True
        dx = event.x_root - self.drag_start_x
        dy = event.y_root - self.drag_start_y
        self.win_x += dx
        self.win_y += dy
        self.root.geometry(f"{self.win_w}x600+{int(self.win_x)}+{int(self.win_y)}")
        self.drag_start_x = event.x_root
        self.drag_start_y = event.y_root

    def animate(self):
        self.anim_index += 1

        current_len = len(self.frames[self.current_state])

        if self.anim_index >= current_len:
            self.anim_index = 0

            if self.current_state == "yawn":
                self.current_state = "idle"
            elif self.is_idling:
                if not self.awake:
                    self.current_state = "sleep"
                elif random.random() < 0.4:
                    idle_states = [
                        "idle", "groom", "scratch",
                        "scratch_wall_up", "scratch_wall_down",
                        "scratch_wall_left", "scratch_wall_right"
                    ]
                    self.current_state = random.choice(idle_states)

        frame_img = self.frames[self.current_state][self.anim_index]
        self.sprite_label.config(image=frame_img)

        delay = 100 if self.current_state.startswith("run") else 400
        self.root.after(delay, self.animate)

    def change_state(self, new_state, text=None):
        self.current_state = new_state
        self.anim_index = 0

        if text is not None:
            self.dialogue.config(text=text)

        if new_state in self.frames and self.frames[new_state]:
            self.sprite_label.config(image=self.frames[new_state][0])

    # --- AGENTIC MODE LOGIC ---
    def prompt_agentic(self, event):
        if self.is_agentic: return
        self.awake = True
        self.is_idling = False
        self.awaiting_input = True
        self.change_state("sit_up", "Awaiting orders...")

        self.dialogue.pack_forget()

        self.task_entry = tk.Entry(self.frame, width=25, bg="#333333", fg="white",
                                   font=("Courier", 10), borderwidth=0, insertbackground="white")
        self.task_entry.pack(pady=5)
        self.task_entry.focus_set()
        self.task_entry.bind("<Return>", self.start_agentic_mode)

    def start_agentic_mode(self, event):
        self.awaiting_input = False
        user_input = self.task_entry.get()
        self.task_entry.destroy()
        self.dialogue.pack(pady=5)

        if not user_input.strip():
            self.awake = False
            self.is_idling = True
            self.change_state("sleep", "*Nevermind*")
            return

        self.agentic_task = user_input
        self.change_state("idle", "Thinking...")
        self._capture_screenshot(lambda img: self._classify_input(img, user_input))

    def _classify_input(self, img, user_input):
        img_str = self.prepare_vision_payload(img, fmt="PNG")
        prompt = (
            f'You are Jiji, the sardonic black cat. The user typed: "{user_input}"\n'
            "Is this a desktop TASK to perform, or a QUESTION/conversation?\n"
            '- Desktop task (open app, click something, type something, automate the desktop): {"type": "task"}\n'
            '- Question or chat: {"type": "answer", "text": "your answer in Jiji\'s sardonic voice, 30 words max"}\n'
            "Reply with ONLY one JSON object."
        )
        self._call_api(prompt, img_str, self._process_classification,
                       self._handle_normal_error, json_mode=True)

    def _process_classification(self, result):
        data = {}
        try:
            data = json.loads(result)
        except json.JSONDecodeError:
            data = {"type": "task"}

        if data.get("type") == "answer":
            answer = str(data.get("text", "")).strip().strip('"')
            self.change_state("sit_up", f'"{answer}"')
            self.awaiting_offer = True
        else:
            self.is_agentic = True
            self.last_agentic_action = None
            self.action_history = []
            self.change_state("idle", f"Task: {self.agentic_task}")
            self.root.after(1000, self.agentic_step)

    def exit_agentic_mode(self):
        self.is_agentic = False
        self.agentic_task = ""
        self.agentic_queue.clear()
        self.last_agentic_action = None
        self.action_history = []
        self.awake = False
        self.is_idling = True
        self.change_state("sleep", "*Task done. Sleeping.*")
        self.root.after(1000, lambda: self.dialogue.config(text="*No thoughts, head empty.*") if not self.awake else None)

    def agentic_step(self):
        if not self.is_agentic: return

        if len(self.agentic_queue) > 0:
            current_action = self.agentic_queue.pop(0)
            self.execute_agentic_action(current_action)
            return

        self.change_state("idle", "Working...")
        self._capture_screenshot(self._continue_agentic_step)

    def _continue_agentic_step(self, img):
        if not self.is_agentic: return

        img_str = self.prepare_vision_payload(img, fmt="PNG")

        history_block = ""
        if self.action_history:
            lines = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(self.action_history[-8:]))
            history_block = f"\nActions already completed:\n{lines}\n"

        # Loop detection: warn if any action appears 3+ times in recent history
        loop_warning = ""
        if len(self.action_history) >= 3:
            from collections import Counter
            counts = Counter(self.action_history[-8:])
            repeated = [(a, n) for a, n in counts.items() if n >= 3]
            if repeated:
                worst = max(repeated, key=lambda x: x[1])
                loop_warning = (
                    f"\n⚠️ LOOP DETECTED: You have done '{worst[0]}' {worst[1]} times already. "
                    f"This is NOT working. Do NOT repeat it. Try a completely different approach to complete the task.\n"
                )

        # Nudge: guide the model through the win+r → type → enter sequence step by step
        type_nudge = ""
        if self.action_history:
            last = self.action_history[-1]
            if last == "press_key 'win+r'":
                type_nudge = "\n⚠️ You just opened the Run dialog. Your ONLY valid next action is: type the application name. Do NOT press win+r again.\n"
            elif last.startswith("type '") and len(self.action_history) >= 2 and self.action_history[-2] == "press_key 'win+r'":
                type_nudge = "\n⚠️ You just typed in the Run dialog. Your ONLY valid next action is: press_key 'enter' to launch it. Do NOT press win+r again.\n"
            elif (last == "press_key 'enter'" and len(self.action_history) >= 3
                  and self.action_history[-2].startswith("type '")
                  and self.action_history[-3] == "press_key 'win+r'"):
                type_nudge = "\n⚠️ You just launched an application from the Run dialog. Check the screenshot — if it is now open, output 'done' immediately. Do NOT press win+r again.\n"

        prompt = f"""You are a desktop automation agent. You are NOT a character — do not use any personality or voice in the "thought" field; use it only for brief task reasoning.
Task: "{self.agentic_task}"
{history_block}{loop_warning}{type_nudge}
Study the screenshot and decide the single best NEXT action.

RULES:
- Run dialog sequence — follow these steps IN ORDER, one per turn:
    1. press_key "win+r"  (opens the dialog)
    2. type the executable name  (e.g. notepad, calc, chrome, cmd)
    3. press_key "enter"  (launches it)
  NEVER press "enter" on a Run dialog that has no text typed yet.
  ONLY press "enter" after a type action appears in the history above.
- Before trying to open an app, check the taskbar at the bottom of the screen — if it's already open there, click its taskbar button to bring it to focus instead of launching a new instance
- Click a text field before typing into it — search bar, address bar, or text box
- Browser search: click the address bar at the very top first
- New line while typing: press_key "enter" between type actions
- Save: press_key "ctrl+s"  |  Close: press_key "alt+f4"
- Output "done" only after the task is fully complete

Output exactly ONE of these JSON formats — no other keys, no extra text:
  {{"thought": "...", "action": "click", "x": 0.45, "y": 0.82}}
  {{"thought": "...", "action": "type", "text": "notepad"}}
  {{"thought": "...", "action": "press_key", "key": "enter"}}
  {{"thought": "...", "action": "press_key", "key": "win+r"}}
  {{"thought": "...", "action": "done"}}"""

        self._call_api(prompt, img_str, self._process_agentic_response, self._handle_agentic_error,
                       json_mode=True, timeout=120, mime="image/png")

    def _process_agentic_response(self, result):
        if not self.is_agentic: return
        if SHOW_RAW_LLM_OUTPUT:
            print(f"\n--- RAW LLM OUTPUT (AGENTIC) ---\n{result}\n----------------------")

        data = {}
        try:
            data = json.loads(result)
        except json.JSONDecodeError:
            json_match = re.search(r'(\{.*?\}|\[.*?\])', result, re.DOTALL)
            clean_result = json_match.group(1) if json_match else result
            try:
                data = json.loads(clean_result)
            except json.JSONDecodeError:
                print("Agentic JSON Error: Could not parse response.")

        if isinstance(data.get("thought"), dict):
            nested = data["thought"]
            data["thought"] = f"H: {nested.get('horizontal')}, V: {nested.get('vertical')}"

        # Normalize model shorthands when "action" key is missing
        if isinstance(data, dict) and "action" not in data:
            if "type" in data and isinstance(data.get("type"), str):
                # {"type": "notepad"} → {"action": "type", "text": "notepad"}
                data["text"] = data.pop("type")
                data["action"] = "type"
            elif "press_key" in data and isinstance(data.get("press_key"), str):
                # {"press_key": "enter"} → {"action": "press_key", "key": "enter"}
                data["key"] = data.pop("press_key")
                data["action"] = "press_key"

        parsed_actions = []
        if isinstance(data, dict):
            if "actions" in data and isinstance(data["actions"], list):
                parsed_actions = data["actions"]
            elif "action" in data or "x" in data or "text" in data or "key" in data:
                parsed_actions = [data]
        elif isinstance(data, list):
            parsed_actions = data

        expanded_actions = []
        simulated_last_action = getattr(self, 'last_agentic_action', None)

        for act in parsed_actions:
            act_type = str(act.get("action", "")).lower()

            raw_x = act.get("x")
            raw_y = act.get("y")

            if raw_x is None or raw_y is None:
                thought_str = str(act.get("thought", ""))
                decimals = re.findall(r'(0\.\d+)', thought_str)
                if len(decimals) >= 2:
                    raw_x = decimals[-2]
                    raw_y = decimals[-1]

            has_coords = raw_x is not None and raw_y is not None and str(raw_x).strip().lower() != 'null'
            has_text  = "text" in act and bool(str(act["text"]).strip()) and str(act["text"]).strip().lower() != 'null'
            has_key   = "key" in act and bool(str(act.get("key", "")).strip())

            if act_type == "press_key" and has_key:
                expanded_actions.append(act)
                simulated_last_action = "press_key"
            elif has_coords and has_text:
                if act_type == "type" and simulated_last_action == "click":
                    print("Ignoring hallucinated coordinates on 'type' action because we just clicked.")
                    act["action"] = "type"
                    expanded_actions.append(act)
                    simulated_last_action = "type"
                else:
                    print("Splitting combined action into two separate queue steps!")
                    expanded_actions.append({"action": "click", "x": raw_x, "y": raw_y})
                    expanded_actions.append({"action": "type", "text": act["text"]})
                    simulated_last_action = "type"
            elif act_type == "done" and has_text:
                print("Overriding premature 'done' action to 'type' because text was provided.")
                act["action"] = "type"
                expanded_actions.append(act)
                simulated_last_action = "type"
            else:
                if has_coords:
                    act["x"] = raw_x
                    act["y"] = raw_y
                expanded_actions.append(act)
                if act_type in ["click", "type", "press_key", "done"]:
                    simulated_last_action = act_type

        if expanded_actions:
            self.agentic_queue.extend(expanded_actions)
            first_action = self.agentic_queue.pop(0)
            self.execute_agentic_action(first_action)
        else:
            self.change_state("idle", "Unsure what to do...")
            self.root.after(3000, self.agentic_step)

    def agentic_run_to_click(self, tx, ty, rel_x, rel_y):
        dest_x = max(0, min(tx - 100, self.screen_w - 200))
        dest_y = max(0, min(ty - 100, self.screen_h - 200))
        dist = math.hypot(dest_x - self.win_x, dest_y - self.win_y)
        if dist < 15:
            self._do_agentic_click(tx, ty, rel_x, rel_y)
            return
        steps = int(dist / 15)
        dx = (dest_x - self.win_x) / steps
        dy = (dest_y - self.win_y) / steps
        self.change_state(self.get_run_direction(dx, dy), "Running...")
        self.move_window_agentic(dx, dy, steps, tx, ty, rel_x, rel_y)

    def move_window_agentic(self, dx, dy, steps_left, tx, ty, rel_x, rel_y):
        if not self.is_agentic:
            return
        if steps_left <= 0:
            self._do_agentic_click(tx, ty, rel_x, rel_y)
            return
        self.win_x += dx
        self.win_y += dy
        self.root.geometry(f"{self.win_w}x600+{int(self.win_x)}+{int(self.win_y)}")
        self.root.after(20, self.move_window_agentic, dx, dy, steps_left - 1, tx, ty, rel_x, rel_y)

    def _do_agentic_click(self, tx, ty, rel_x, rel_y):
        self.change_state("shock", "*Clicking!*")
        pyautogui.moveTo(tx, ty, duration=0.4)
        pyautogui.click()
        self.action_history.append(f"click at ({rel_x:.2f}, {rel_y:.2f})")
        self.root.after(2000, self.agentic_step)

    def _handle_agentic_error(self, e):
        print(f"Agentic LLM Error: {e}")
        self.change_state("sleep", "*Brain freeze*")
        self.root.after(4000, self.agentic_step)

    def execute_agentic_action(self, action_data):
        if not self.is_agentic: return
        action = str(action_data.get("action", "none")).lower()

        if action == "done" and action_data.get("text") and str(action_data["text"]).lower() != "null":
            print("Overriding premature 'done' to 'type'.")
            action = "type"
        elif action not in ["click", "type", "press_key", "done"]:
            if "x" in action_data and str(action_data["x"]).lower() != "null":
                print(f"Overriding fake action '{action}' to 'click'.")
                action = "click"
            elif "key" in action_data and str(action_data["key"]).lower() != "null":
                print(f"Overriding fake action '{action}' to 'press_key'.")
                action = "press_key"
            elif "text" in action_data and str(action_data["text"]).lower() != "null":
                print(f"Overriding fake action '{action}' to 'type'.")
                action = "type"
            else:
                action = "none"

        self.last_agentic_action = action

        print(f"\n[JIJI EXECUTES]: {action.upper()} -> {action_data}\n")

        if action == "click":
            raw_x = action_data.get("x")
            raw_y = action_data.get("y")

            try:
                if raw_x is None or raw_y is None:
                    raise ValueError("Missing coordinates")
                rel_x = float(raw_x)
                rel_y = float(raw_y)
            except (ValueError, TypeError):
                print(f"Coordinate Parse Error (Received X:{raw_x}, Y:{raw_y}). Attempting rescue from thought...")
                thought = str(action_data.get("thought", ""))
                decimals = re.findall(r'(0\.\d+)', thought)

                if len(decimals) >= 2:
                    rel_x = float(decimals[-2])
                    rel_y = float(decimals[-1])
                    print(f"Rescued missing keys from thought text: {rel_x}, {rel_y}")
                else:
                    print("Rescue failed. Defaulting to center (0.5, 0.5)")
                    rel_x, rel_y = 0.5, 0.5

            rel_x = max(0.0, min(1.0, rel_x))
            rel_y = max(0.0, min(1.0, rel_y))

            tx, ty = self.unmap_coordinates(rel_x, rel_y)
            self.agentic_run_to_click(tx, ty, rel_x, rel_y)

        elif action == "type":
            text = str(action_data.get("text", ""))
            self.change_state("scratch", "Typing...")
            # Normalize both JSON-parsed newlines and literal \n from sloppy LLM output
            normalized = text.replace("\\n", "\n")
            parts = normalized.split("\n")
            for i, part in enumerate(parts):
                keyboard.write(part, delay=0.02)
                if i < len(parts) - 1:
                    pyautogui.press("enter")
            label = text[:30] + ("..." if len(text) > 30 else "")
            self.action_history.append(f"type '{label}'")

            self.root.after(2000, self.agentic_step)

        elif action == "press_key":
            key = str(action_data.get("key", "")).strip()
            if not key:
                self.change_state("idle", "Skipping empty key...")
                self.root.after(1000, self.agentic_step)
                return
            self.change_state("shock", f"Pressing {key}...")
            if "+" in key:
                pyautogui.hotkey(*key.split("+"))
            else:
                pyautogui.press(key)
            self.action_history.append(f"press_key '{key}'")

            # Give apps extra time to appear after Enter; 1s for other keys
            delay = 3000 if key == "enter" else 1000
            self.root.after(delay, self.agentic_step)

        elif action == "done":
            self.change_state("sit_up", "Task complete!")
            self.agentic_queue.clear()
            self.root.after(4000, self.exit_agentic_mode)

        else:
            self.change_state("idle", "Skipping weird action...")
            self.root.after(1000, self.agentic_step)


    # --- NORMAL MODE LOGIC ---
    def agent_see(self):
        if self.is_agentic or self.awaiting_input or self.awaiting_offer:
            return

        if not self.awake:
            return

        if self.actions_remaining <= 0:
            self.awake = False
            self.is_idling = True
            self.change_state("sleep", "*Going back to sleep...*")
            self.root.after(1000, lambda: self.dialogue.config(text="*No thoughts, head empty.*") if not self.awake else None)
            return

        self.actions_remaining -= 1

        self.is_idling = False
        self.change_state("idle", "Screenshotting...")
        self._capture_screenshot(self.agent_think)

    def agent_think(self, screenshot_image):
        self.change_state("idle", "Reading...")
        img_str = self.prepare_vision_payload(
            screenshot_image,
            fmt="PNG" if HIGH_RES_VISION else "JPEG"
        )

        now = datetime.datetime.now()
        time_str = now.strftime("%I:%M %p").lstrip("0")

        current_hash = self._get_screenshot_hash(screenshot_image)
        screen_unchanged = bool(self.last_screenshot_hash and current_hash == self.last_screenshot_hash)
        self.last_screenshot_hash = current_hash
        stasis_note = ("The screen has not changed since last time. "
                       "The user has been idle. You may call this out.\n") if screen_unchanged else ""

        memory_note = ""
        if self.recent_comments:
            past = "\n".join(f'- "{c}"' for c in self.recent_comments)
            memory_note = f"You have already said all of these recently. Do NOT repeat any of them, word for word or in substance:\n{past}\n"

        prompt = (
            "You are Jiji, the sardonic black cat from Kiki's Delivery Service. "
            f"The current time is {time_str}. "
            f"{stasis_note}"
            f"{memory_note}"
            "Look at this screenshot and identify what the user is doing "
            "(coding, writing, browsing, gaming, listening to music, etc.). "
            "Make a short, witty or cutting remark about it (15 words max). "
            "Then optionally offer one specific thing you could do to help them. "
            "If you make an offer, phrase it in Jiji's reluctant, sardonic voice "
            "and name the specific app or thing — never say 'that'. "
            "(e.g. 'I could open Spotify for you. If you insist.' or "
            "'Want me to save that file? Before you lose it.' or "
            "'I could close Discord for you. Since you clearly can\\'t.'). "
            "Also include a clear, imperative offer_task for an automation agent "
            "(e.g. 'Open Spotify', 'Save the current file', 'Open YouTube in Chrome'). "
            'Respond with ONLY a JSON object: '
            '{"comment": "your remark", "offer": "sardonic offer, or null", "offer_task": "imperative task, or null"}'
        )
        self._call_api(prompt, img_str, self._process_clippy_response,
                       self._handle_normal_error, json_mode=True, timeout=120)

    def _process_clippy_response(self, result):
        if not self.awake or self.is_agentic: return
        if SHOW_RAW_LLM_OUTPUT:
            print(f"\n--- RAW LLM OUTPUT (CLIPPY) ---\n{result}\n----------------------")

        data = {}
        try:
            data = json.loads(result)
        except json.JSONDecodeError:
            data = {"comment": result.strip().strip('"'), "offer": None}

        comment = str(data.get("comment", "")).strip().strip('"').strip("'")

        # Hard dedup: if the LLM repeated a saved comment anyway, don't re-save it
        def _norm(s):
            import re
            return re.sub(r'[^a-z0-9]', '', s.lower())
        if any(_norm(comment) == _norm(c) for c in self.recent_comments):
            print(f"[MEMORY] Duplicate comment detected, skipping save: \"{comment}\"")
        else:
            self._save_to_memory(comment)
        offer = data.get("offer")
        if not isinstance(offer, str) or offer.strip().lower() in ("null", "none", ""):
            offer = None

        offer_task = data.get("offer_task")
        if not isinstance(offer_task, str) or offer_task.strip().lower() in ("null", "none", ""):
            offer_task = offer  # fall back to offer text if offer_task missing

        self.is_idling = True
        self.pending_offer = offer or ""
        self.pending_offer_task = offer_task or ""
        self.change_state("sit_up", f'"{comment}"')

        if offer:
            self.root.after(1500, lambda: self._show_offer(comment, offer))
        else:
            self.awaiting_offer = True

    def _show_offer(self, comment, offer):
        self.awaiting_offer = True
        self.dialogue.config(text=f'"{comment}"\n\n{offer}')
        self.btn_frame.pack(pady=5)

    def _handle_normal_error(self, e):
        print(f"LLM Error: {e}")
        self.awaiting_offer = False
        self.awake = False
        self.is_idling = True
        self.btn_frame.pack_forget()
        self.change_state("sleep", "Head empty.")

    def get_run_direction(self, dx, dy):
        angle = math.degrees(math.atan2(dy, dx))
        if   -22.5 <= angle <  22.5: return "run_E"
        elif  22.5 <= angle <  67.5: return "run_SE"
        elif  67.5 <= angle < 112.5: return "run_S"
        elif 112.5 <= angle < 157.5: return "run_SW"
        elif 157.5 <= angle <= 180 or -180 <= angle < -157.5: return "run_W"
        elif -157.5 <= angle < -112.5: return "run_NW"
        elif -112.5 <= angle <  -67.5: return "run_N"
        elif  -67.5 <= angle <  -22.5: return "run_NE"
        return "run_E"

    def action_approved(self):
        self.awaiting_offer = False
        self.btn_frame.pack_forget()
        task = self.pending_offer_task or self.pending_offer
        self.pending_offer = ""
        self.pending_offer_task = ""
        self.is_agentic = True
        self.last_agentic_action = None
        self.action_history = []
        self.agentic_task = task
        self.change_state("idle", f"Task: {task}")
        self.root.after(1000, self.agentic_step)

    def action_denied(self):
        self.awaiting_offer = False
        self.awake = False
        self.btn_frame.pack_forget()
        self.is_idling = True
        self.change_state("sleep", "*Fine. Sleeping.*")

def _make_tray_icon_image():
    """Crop top-left of sprites.png for the tray icon; fall back to a dark square."""
    try:
        sheet = Image.open("sprites.png").convert("RGBA")
        return sheet.crop((0, 0, 32, 32)).resize((32, 32), Image.Resampling.LANCZOS)
    except Exception:
        return Image.new("RGBA", (32, 32), (20, 20, 20, 255))

def create_jiji():
    print("Jiji V1.24 online. ESC to abort task or kill. Left click to wake up. Left drag to move. Right click to give task.")

    # Hide the console window at startup
    hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    ctypes.windll.user32.ShowWindow(hwnd, 0)  # SW_HIDE

    root = tk.Tk()
    app = JijiApp(root)
    keyboard.add_hotkey('esc', lambda: _handle_esc(app))

    # System tray icon
    def toggle_console():
        visible = ctypes.windll.user32.IsWindowVisible(hwnd)
        ctypes.windll.user32.ShowWindow(hwnd, 0 if visible else 5)

    tray_menu = pystray.Menu(
        pystray.MenuItem("Show/Hide Log", toggle_console, default=True),
        pystray.MenuItem("Quit Jiji", lambda icon, item: root.after(0, nuke_process)),
    )
    global _tray_icon
    tray_icon = pystray.Icon("Jiji", _make_tray_icon_image(), "Jiji", tray_menu)
    _tray_icon = tray_icon
    threading.Thread(target=tray_icon.run, daemon=True).start()

    root.mainloop()

if __name__ == "__main__":
    create_jiji()
