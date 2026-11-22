"""My Agent Chat - a light chat app with agent tools, for older PCs.
Uses only what comes with Python. No extra installs needed to run it.
"""
import json, os, queue, subprocess, tempfile, threading
import urllib.error, urllib.request
import tkinter as tk
from tkinter import messagebox, ttk

APP_NAME = "MyAgentChat"
VERSION = "1.0.0"
# OWNER: put the web address of your version.json here so every installed
# copy checks YOUR updates. Example: "https://example.com/version.json"
UPDATE_URL = ""

PROVIDERS = {
    "gemini": ("Google Gemini (free)", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions", "gemini-2.5-flash"),
    "groq": ("Groq (free)", "https://api.groq.com/openai/v1/chat/completions", "llama-3.3-70b-versatile"),
    "openrouter": ("OpenRouter (free models)", "https://openrouter.ai/api/v1/chat/completions", "meta-llama/llama-3.3-70b-instruct:free"),
    "mistral": ("Mistral (free tier)", "https://api.mistral.ai/v1/chat/completions", "mistral-small-latest"),
    "claude": ("Claude (Anthropic, paid)", "https://api.anthropic.com/v1/messages", "claude-sonnet-5-5"),
}

SYSTEM = ("You are a helpful assistant inside a Windows desktop app. You can use tools to "
          "list folders, read files and write files on the user's computer. Be concise and "
          "reply in the language the user writes in.")

TOOLS = [
    {"name": "list_folder", "description": "List the files and folders inside a folder.",
     "schema": {"type": "object", "properties": {"path": {"type": "string", "description": "Folder path"}}, "required": ["path"]}},
    {"name": "read_file", "description": "Read a text file.",
     "schema": {"type": "object", "properties": {"path": {"type": "string", "description": "File path"}}, "required": ["path"]}},
    {"name": "write_file", "description": "Create or overwrite a text file. The user must approve it.",
     "schema": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
]

DATA_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")


def load_settings():
    s = {"provider": "gemini", "keys": {}, "models": {}, "tools": True, "update_url": "", "mode": "chat"}
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            s.update(json.load(f))
    except Exception:
        pass
    if s.get("provider") not in PROVIDERS:
        s["provider"] = "gemini"
    for k in ("keys", "models"):
        if not isinstance(s.get(k), dict):
            s[k] = {}
    return s


def save_settings(s):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2)


def post_json(url, headers, body):
    h = {"Content-Type": "application/json", "User-Agent": APP_NAME}
    h.update(headers)
    req = urllib.request.Request(url, json.dumps(body).encode("utf-8"), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        hints = {401: " (the key is wrong for this provider)", 404: " (check the model name)",
                 429: " (free limit reached - wait a bit or switch provider)"}
        raise RuntimeError(f"Error {e.code}{hints.get(e.code, '')}: {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"No internet connection: {e.reason}")


def run_tool(name, args, confirm):
    try:
        if name == "list_folder":
            p = os.path.expanduser(args["path"])
            items = sorted(os.listdir(p))[:200]
            return "\n".join(("[folder] " if os.path.isdir(os.path.join(p, i)) else "") + i for i in items) or "(empty)"
        if name == "read_file":
            with open(os.path.expanduser(args["path"]), "r", encoding="utf-8", errors="replace") as f:
                return f.read(20000)
        if name == "write_file":
            p = os.path.expanduser(args["path"])
            if not confirm(f"Allow the AI to write this file?\n\n{p}\n\n({len(args['content'])} characters)"):
                return "The user refused to allow this."
            os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                f.write(args["content"])
            return "File saved."
    except Exception as e:
        return f"Tool error: {e}"
    return "Unknown tool."


def vtuple(v):
    return tuple(int(x) for x in v.strip().lstrip("v").split("."))


CHAT = dict(bg="#faf9f5", fg="#1f1e1d", muted="#8a8780", bubble="#efece3", accent="#c96442",
            border="#dcd9cf", input_bg="#ffffff", bar="#f0eee6", bar_fg="#3d3929", err="#b00020")
TERM = dict(bg="#050805", fg="#33ff66", muted="#1f9d45", err="#ff4d4d", warn="#ffd166",
            cyan="#4dd0e1", bar="#0a140a", bar_fg="#33ff66")
CHAT_TAGS = ("you", "bot", "tool", "err")  # lines shown in chat mode (cmd/sys are prompt-only)

HELP = """Commands:
  /chat <message>     talk to the AI            example: /chat hi
  /new                forget the conversation
  /clear              clear the screen
  /mode chat          switch to the chat page
  /provider [name]    show or change provider (gemini groq openrouter mistral claude)
  /model <name>       change the model
  /key <key>          save the key for the current provider
  /tools on|off       allow the AI to use file tools
  /status             show current settings
  /update             check for updates
  /exit               close the app"""


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"My Agent Chat {VERSION}")
        self.geometry("820x600")
        self.minsize(560, 400)
        self.s = load_settings()
        self.mode = self.s.get("mode") if self.s.get("mode") in ("chat", "prompt") else "chat"
        self.history, self.transcript = [], []
        self.cmd_hist, self.hist_i = [], 0
        self.q = queue.Queue()
        self.busy = False

        # top bar
        self.bar = tk.Frame(self)
        self.bar.pack(fill="x")
        self.status = tk.Label(self.bar, anchor="w", padx=10, pady=6)
        self.status.pack(side="left")
        self.btns = []
        for text, cmd in (("Settings", self.open_settings), ("Check updates", lambda: self.check_updates(True)),
                          ("New chat", self.new_chat), ("", self.toggle_mode)):
            b = tk.Button(self.bar, text=text, command=cmd, relief="flat", bd=0, padx=10, pady=4, cursor="hand2")
            b.pack(side="right", padx=2, pady=4)
            self.btns.append(b)
        self.mode_btn = self.btns[-1]

        # chat page
        self.chat_body = tk.Frame(self, bg=CHAT["bg"])
        self.clog = tk.Text(self.chat_body, wrap="word", state="disabled", bd=0, highlightthickness=0,
                            bg=CHAT["bg"], fg=CHAT["fg"], font=("Georgia", 11), padx=24, pady=12, cursor="arrow")
        sb = ttk.Scrollbar(self.chat_body, command=self.clog.yview)
        self.clog.config(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.clog.pack(side="left", fill="both", expand=True)
        self.clog.tag_config("you", background=CHAT["bubble"], font=("Segoe UI", 10), lmargin1=150, lmargin2=150,
                             rmargin=14, spacing1=12, spacing3=8)
        self.clog.tag_config("bot", font=("Georgia", 11), lmargin1=14, lmargin2=14, rmargin=90, spacing1=8, spacing3=16)
        self.clog.tag_config("tool", foreground=CHAT["muted"], font=("Segoe UI", 9, "italic"), lmargin1=14, lmargin2=14)
        self.clog.tag_config("err", foreground=CHAT["err"], font=("Segoe UI", 10), lmargin1=14, lmargin2=14, spacing3=10)
        self.clog.tag_config("hello", font=("Georgia", 22), justify="center", foreground=CHAT["fg"], spacing1=150)
        self.clog.tag_config("hello2", font=("Segoe UI", 10), justify="center", foreground=CHAT["muted"])

        self.chat_foot = tk.Frame(self, bg=CHAT["bg"], padx=40, pady=14)
        box = tk.Frame(self.chat_foot, bg=CHAT["input_bg"], highlightthickness=1, highlightbackground=CHAT["border"])
        box.pack(fill="x")
        self.inp = tk.Text(box, height=3, wrap="word", bd=0, highlightthickness=0, bg=CHAT["input_bg"],
                           fg=CHAT["fg"], font=("Segoe UI", 11), padx=10, pady=8)
        self.inp.pack(side="left", fill="x", expand=True)
        tk.Button(box, text="Send", command=self.chat_send, bg=CHAT["accent"], fg="white", relief="flat", bd=0,
                  padx=14, pady=6, cursor="hand2", activebackground="#b5573a", activeforeground="white"
                  ).pack(side="right", padx=8, pady=8)
        self.inp.bind("<Return>", lambda e: (self.chat_send(), "break")[1])
        self.inp.bind("<Shift-Return>", lambda e: None)

        # prompt (hacker terminal) page
        self.term_body = tk.Frame(self, bg=TERM["bg"])
        self.tlog = tk.Text(self.term_body, wrap="word", state="disabled", bd=0, highlightthickness=0,
                            bg=TERM["bg"], fg=TERM["fg"], font=("Consolas", 10), padx=10, pady=8,
                            insertbackground=TERM["fg"], selectbackground="#145a2a", cursor="arrow")
        sb2 = tk.Scrollbar(self.term_body, command=self.tlog.yview, bg=TERM["bar"], troughcolor=TERM["bg"])
        self.tlog.config(yscrollcommand=sb2.set)
        sb2.pack(side="right", fill="y")
        self.tlog.pack(side="left", fill="both", expand=True)
        for tag, col in (("cmd", TERM["cyan"]), ("you", TERM["cyan"]), ("bot", TERM["fg"]), ("tool", TERM["warn"]),
                         ("err", TERM["err"]), ("sys", TERM["muted"])):
            self.tlog.tag_config(tag, foreground=col)

        self.term_foot = tk.Frame(self, bg=TERM["bg"], padx=10, pady=8)
        tk.Label(self.term_foot, text="you@agent:~$", bg=TERM["bg"], fg=TERM["cyan"], font=("Consolas", 10, "bold")
                 ).pack(side="left")
        self.cmd = tk.Entry(self.term_foot, bg=TERM["bg"], fg=TERM["fg"], insertbackground=TERM["fg"], bd=0,
                            highlightthickness=0, font=("Consolas", 10))
        self.cmd.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self.cmd.bind("<Return>", self.term_enter)
        self.cmd.bind("<Up>", lambda e: self.hist_step(-1))
        self.cmd.bind("<Down>", lambda e: self.hist_step(1))

        self.say("sys", "=====================================\n  MY AGENT CHAT  //  PROMPT MODE  v" + VERSION +
                 "\n=====================================\n[*] talk to the AI with:  /chat your message\n[*] all commands:         /help")
        self.apply_mode()
        self.after(100, self.poll)
        if UPDATE_URL or self.s.get("update_url"):
            self.after(1500, lambda: self.check_updates(False))

    # ---------- modes ----------
    def toggle_mode(self):
        self.set_mode("prompt" if self.mode == "chat" else "chat")

    def set_mode(self, m):
        self.mode = m
        self.s["mode"] = m
        save_settings(self.s)
        self.apply_mode()

    def apply_mode(self):
        chat = self.mode == "chat"
        th = CHAT if chat else TERM
        self.configure(bg=th["bg"])
        self.bar.config(bg=th["bar"])
        self.status.config(bg=th["bar"], fg=th["bar_fg"], font=("Segoe UI", 9) if chat else ("Consolas", 9))
        for b in self.btns:
            b.config(bg=th["bar"], fg=th["bar_fg"], activebackground=th["bg"], activeforeground=th["bar_fg"],
                     font=("Segoe UI", 9) if chat else ("Consolas", 9))
        self.mode_btn.config(text="Prompt mode" if chat else "Chat mode")
        for w in (self.chat_body, self.chat_foot, self.term_body, self.term_foot):
            w.pack_forget()
        if chat:
            self.chat_foot.pack(side="bottom", fill="x")
            self.chat_body.pack(fill="both", expand=True)
            self.inp.focus_set()
        else:
            self.term_foot.pack(side="bottom", fill="x")
            self.term_body.pack(fill="both", expand=True)
            self.cmd.focus_set()
        self.render_all()
        self.refresh_status()

    # ---------- drawing ----------
    def visible(self):
        return [t for t in self.transcript if t[0] in CHAT_TAGS]

    def render_all(self):
        w = self.clog if self.mode == "chat" else self.tlog
        w.config(state="normal")
        w.delete("1.0", "end")
        w.config(state="disabled")
        if self.mode == "chat" and not self.visible():
            w.config(state="normal")
            w.insert("end", "How can I help you today?\n", "hello")
            w.insert("end", "Type a message below. Open Settings first to add your key.\n", "hello2")
            w.config(state="disabled")
        for tag, text in self.transcript:
            self.draw(tag, text)

    def draw(self, tag, text):
        if self.mode == "chat":
            if tag not in CHAT_TAGS:
                return
            w, line = self.clog, text + "\n"
            if tag == "tool":
                line = "• " + text + "\n"
            if tag == "err":
                line = "Something went wrong: " + text + "\n"
        else:
            w = self.tlog
            prefix = {"cmd": "you@agent:~$ ", "you": "you@agent:~$ /chat ", "bot": "[ai] ", "tool": "[*] ",
                      "err": "[!] ", "sys": ""}[tag]
            line = prefix + text + ("\n\n" if tag == "bot" else "\n")
        w.config(state="normal")
        w.insert("end", line, tag)
        w.config(state="disabled")
        w.see("end")

    def say(self, tag, text):
        self.transcript.append((tag, text))
        if not hasattr(self, "tlog") or not self.winfo_exists():
            return
        if self.mode == "chat" and tag in CHAT_TAGS and len(self.visible()) == 1:
            self.render_all()
        else:
            self.draw(tag, text)

    def refresh_status(self):
        p = self.s["provider"]
        t = f"{PROVIDERS[p][0]}  |  {self.s['models'].get(p) or PROVIDERS[p][2]}"
        if self.busy:
            t += "   ● working..."
        self.status.config(text=t)

    def new_chat(self):
        self.history = []
        self.transcript = []
        self.render_all()

    def confirm(self, text):
        holder = {"ev": threading.Event(), "ok": False}
        self.q.put(("confirm", text, holder))
        holder["ev"].wait()
        return holder["ok"]

    def poll(self):
        try:
            while True:
                m = self.q.get_nowait()
                if m[0] == "say":
                    self.say(m[1], m[2])
                elif m[0] == "done":
                    self.busy = False
                    self.refresh_status()
                elif m[0] == "confirm":
                    m[2]["ok"] = messagebox.askyesno("Permission needed", m[1])
                    m[2]["ev"].set()
                elif m[0] == "update":
                    self.offer_update(m[1])
                elif m[0] == "install":
                    subprocess.Popen([m[1], "/SILENT", "/CLOSEAPPLICATIONS"])
                    self.destroy()
                    return
        except queue.Empty:
            pass
        self.after(100, self.poll)

    # ---------- input ----------
    def chat_send(self):
        text = self.inp.get("1.0", "end").strip()
        if text and self.send_text(text):
            self.inp.delete("1.0", "end")

    def term_enter(self, _=None):
        line = self.cmd.get().strip()
        self.cmd.delete(0, "end")
        if line:
            self.run_command(line)

    def hist_step(self, d):
        if not self.cmd_hist:
            return "break"
        self.hist_i = max(0, min(len(self.cmd_hist), self.hist_i + d))
        self.cmd.delete(0, "end")
        if self.hist_i < len(self.cmd_hist):
            self.cmd.insert(0, self.cmd_hist[self.hist_i])
        return "break"

    def send_text(self, text):
        if not text:
            self.say("err", "Usage: /chat your message")
            return False
        if self.busy:
            self.say("err", "Still working on the last message. Wait a moment.")
            return False
        self.say("you", text)
        self.busy = True
        self.refresh_status()
        self.say("sys", "[*] contacting model...")
        threading.Thread(target=self.worker, args=(text,), daemon=True).start()
        return True

    def run_command(self, line):
        self.cmd_hist.append(line)
        self.hist_i = len(self.cmd_hist)
        if not line.lower().startswith("/chat "):  # /chat lines are echoed by send_text
            self.say("cmd", "/key ********" if line.lower().startswith("/key") else line)
        if not line.startswith("/"):
            self.say("err", "Unknown input. To talk to the AI type:  /chat your message   (or /help)")
            return
        name, _, arg = line[1:].partition(" ")
        name, arg, p = name.lower(), arg.strip(), self.s["provider"]
        if name == "chat":
            self.send_text(arg)
        elif name == "help":
            self.say("sys", HELP)
        elif name == "new":
            self.new_chat()
            self.say("sys", "[*] conversation cleared")
        elif name == "clear":
            self.transcript = []
            self.render_all()
        elif name == "mode":
            if arg in ("chat", "prompt"):
                self.set_mode(arg)
            else:
                self.say("err", "Use /mode chat   or   /mode prompt")
        elif name == "provider":
            if arg in PROVIDERS:
                self.s["provider"] = arg
                save_settings(self.s)
                self.refresh_status()
                self.say("sys", f"[*] provider is now {PROVIDERS[arg][0]}")
            else:
                self.say("sys", "Providers: " + "  ".join(("*" if k == p else "") + k for k in PROVIDERS)
                         + "\n(* = current)  change with /provider name")
        elif name == "model":
            if arg:
                self.s["models"][p] = arg
                save_settings(self.s)
                self.refresh_status()
                self.say("sys", f"[*] model for {p} set to {arg}")
            else:
                self.say("err", "Usage: /model model-name")
        elif name == "key":
            if arg:
                self.s["keys"][p] = arg
                save_settings(self.s)
                self.say("sys", f"[*] key saved for {p}")
            else:
                self.say("err", "Usage: /key your-key")
        elif name == "tools":
            if arg in ("on", "off"):
                self.s["tools"] = arg == "on"
                save_settings(self.s)
                self.say("sys", f"[*] file tools {arg}")
            else:
                self.say("err", "Use /tools on   or   /tools off")
        elif name == "status":
            self.say("sys", f"version   {VERSION}\nprovider  {p}\nmodel     {self.s['models'].get(p) or PROVIDERS[p][2]}\n"
                            f"key       {'set' if self.s['keys'].get(p) else 'NOT SET'}\ntools     {'on' if self.s.get('tools', True) else 'off'}")
        elif name == "update":
            self.check_updates(True)
        elif name == "exit":
            self.destroy()
        else:
            self.say("err", f"Unknown command /{name}. Type /help")

    # ---------- chatting ----------
    def worker(self, text):
        self.history.append({"role": "user", "content": text})
        try:
            p = self.s["provider"]
            key = self.s["keys"].get(p, "").strip()
            if not key:
                raise RuntimeError("No key for this provider yet. Open Settings and paste it.")
            model = self.s["models"].get(p) or PROVIDERS[p][2]
            use_tools = self.s.get("tools", True)
            if p == "claude":
                if not key.startswith("sk-ant-"):
                    raise RuntimeError("Claude keys start with sk-ant-. For a Gemini or Groq key, pick that provider in Settings.")
                reply = self.run_claude(key, model, use_tools)
            else:
                reply = self.run_openai(PROVIDERS[p][1], key, model, use_tools)
            reply = reply or "(empty reply)"
            self.history.append({"role": "assistant", "content": reply})
            self.q.put(("say", "bot", reply))
        except Exception as e:
            if self.history and self.history[-1]["role"] == "user":
                self.history.pop()
            self.q.put(("say", "err", str(e)))
        self.q.put(("done",))

    def run_openai(self, url, key, model, use_tools):
        msgs = [{"role": "system", "content": SYSTEM}] + list(self.history)
        tools = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["schema"]}} for t in TOOLS]
        for _ in range(8):
            body = {"model": model, "messages": msgs}
            if use_tools:
                body["tools"] = tools
            m = post_json(url, {"Authorization": "Bearer " + key}, body)["choices"][0]["message"]
            calls = m.get("tool_calls")
            if not calls:
                return m.get("content") or ""
            msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
            for c in calls:
                name = c["function"]["name"]
                args = json.loads(c["function"].get("arguments") or "{}")
                self.q.put(("say", "tool", f"Using tool: {name} {args.get('path', '')}"))
                msgs.append({"role": "tool", "tool_call_id": c.get("id", ""), "name": name,
                             "content": run_tool(name, args, self.confirm)})
        return "(Stopped: too many tool steps.)"

    def run_claude(self, key, model, use_tools):
        msgs = list(self.history)
        tools = [{"name": t["name"], "description": t["description"], "input_schema": t["schema"]} for t in TOOLS]
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        for _ in range(8):
            body = {"model": model, "max_tokens": 2000, "system": SYSTEM, "messages": msgs}
            if use_tools:
                body["tools"] = tools
            data = post_json(PROVIDERS["claude"][1], headers, body)
            blocks = data.get("content", [])
            uses = [b for b in blocks if b.get("type") == "tool_use"]
            if not uses:
                return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
            msgs.append({"role": "assistant", "content": blocks})
            results = []
            for b in uses:
                self.q.put(("say", "tool", f"Using tool: {b['name']} {b['input'].get('path', '')}"))
                results.append({"type": "tool_result", "tool_use_id": b["id"],
                                "content": run_tool(b["name"], b["input"], self.confirm)})
            msgs.append({"role": "user", "content": results})
        return "(Stopped: too many tool steps.)"

    # ---------- settings ----------
    def open_settings(self):
        w = tk.Toplevel(self)
        w.title("Settings")
        w.geometry("580x370")
        w.transient(self)
        w.grab_set()
        keys = dict(self.s["keys"])
        models = dict(self.s["models"])
        names = {v[0]: k for k, v in PROVIDERS.items()}
        cur = {"p": self.s["provider"]}
        f = ttk.Frame(w, padding=12)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Provider").grid(row=0, column=0, sticky="w", pady=4)
        prov = ttk.Combobox(f, state="readonly", values=list(names.keys()))
        prov.set(PROVIDERS[cur["p"]][0])
        prov.grid(row=0, column=1, sticky="ew")
        ttk.Label(f, text="API key").grid(row=1, column=0, sticky="w", pady=4)
        key_e = ttk.Entry(f, show="*")
        key_e.grid(row=1, column=1, sticky="ew")
        ttk.Label(f, text="Model").grid(row=2, column=0, sticky="w", pady=4)
        model_e = ttk.Entry(f)
        model_e.grid(row=2, column=1, sticky="ew")
        tools_v = tk.BooleanVar(value=self.s.get("tools", True))
        ttk.Checkbutton(f, text="Let the AI use file tools (turn off if a model gives errors)", variable=tools_v).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)
        ttk.Label(f, text="Update link").grid(row=4, column=0, sticky="w", pady=4)
        upd_e = ttk.Entry(f)
        upd_e.insert(0, self.s.get("update_url", ""))
        upd_e.grid(row=4, column=1, sticky="ew")
        ttk.Label(f, text="Free keys: aistudio.google.com/apikey (Gemini), console.groq.com/keys (Groq).\nClaude keys: console.anthropic.com", foreground="#666").grid(row=5, column=0, columnspan=2, sticky="w", pady=8)

        def load(p):
            key_e.delete(0, "end"); key_e.insert(0, keys.get(p, ""))
            model_e.delete(0, "end"); model_e.insert(0, models.get(p) or PROVIDERS[p][2])

        def stash():
            keys[cur["p"]] = key_e.get().strip()
            models[cur["p"]] = model_e.get().strip()

        def changed(_=None):
            stash()
            cur["p"] = names[prov.get()]
            load(cur["p"])

        def save():
            stash()
            self.s.update({"provider": cur["p"], "keys": keys, "models": models,
                           "tools": tools_v.get(), "update_url": upd_e.get().strip()})
            save_settings(self.s)
            self.refresh_status()
            w.destroy()

        prov.bind("<<ComboboxSelected>>", changed)
        load(cur["p"])
        ttk.Button(f, text="Save", command=save).grid(row=6, column=1, sticky="e", pady=8)

    # ---------- updates ----------
    def check_updates(self, manual):
        url = UPDATE_URL or self.s.get("update_url", "")
        if not url:
            if manual:
                messagebox.showinfo("Updates", "No update link is set. Add one in Settings.")
            return

        def job():
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": APP_NAME}), timeout=20) as r:
                    info = json.loads(r.read().decode("utf-8"))
                if vtuple(info["version"]) > vtuple(VERSION):
                    self.q.put(("update", info))
                elif manual:
                    self.q.put(("say", "tool", f"You have the newest version ({VERSION})."))
            except Exception as e:
                if manual:
                    self.q.put(("say", "err", f"Could not check for updates: {e}"))
        threading.Thread(target=job, daemon=True).start()

    def offer_update(self, info):
        if not messagebox.askyesno("Update available", f"Version {info['version']} is available.\n\n{info.get('notes', '')}\n\nInstall it now?"):
            return
        self.say("tool", "Downloading update...")

        def job():
            try:
                path = os.path.join(tempfile.gettempdir(), "MyAgentChatSetup.exe")
                urllib.request.urlretrieve(info["url"], path)
                self.q.put(("install", path))
            except Exception as e:
                self.q.put(("say", "err", f"Update failed: {e}"))
        threading.Thread(target=job, daemon=True).start()


if __name__ == "__main__":
    App().mainloop()
