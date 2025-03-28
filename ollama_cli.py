import os
import shlex
import subprocess
import requests
import json
import readline
import re
from pathlib import Path

CONFIG_PATH = Path.home() / ".ollama-cli-config"

class OllamaCLI:
    def __init__(self):
        self.cwd = os.getcwd()
        self.config = self.load_config()
        self.session = requests.Session()
        self.server = self.config.get("OLLAMA_HOST", "http://localhost:11434")
        self.model = self.config.get("OLLAMA_MODEL", "llama3")

    def load_config(self):
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH) as f:
                return dict(line.strip().split("=", 1) for line in f if "=" in line)
        return {}

    def save_config(self):
        with open(CONFIG_PATH, "w") as f:
            for k, v in self.config.items():
                f.write(f"{k}={v}\n")

    def prompt(self):
        return input("% ").strip()

    def run(self):
        print("Welcome to the Ollama CLI. Type '@help' for commands.")
        while True:
            try:
                command = self.prompt()
                if not command:
                    continue
                if command.startswith("@"):  # LLM command
                    self.handle_llm_command(command)
                elif command.startswith("cd "):
                    self.change_dir(command[3:].strip())
                else:
                    self.run_shell_command(command)
            except (EOFError, KeyboardInterrupt):
                print("\nExiting CLI.")
                break

    def change_dir(self, path):
        try:
            os.chdir(path)
            self.cwd = os.getcwd()
        except Exception as e:
            print(f"cd: {e}")

    def run_shell_command(self, cmd):
        try:
            result = subprocess.run(shlex.split(cmd), cwd=self.cwd, capture_output=True, text=True)
            print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="")
        except Exception as e:
            print(f"Error running command: {e}")

    def handle_llm_command(self, command):
        parts = command.split(" ", 1)
        cmd = parts[0][1:]
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "server":
            self.server = arg
            self.config["OLLAMA_HOST"] = arg
            self.save_config()
            print(f"Changed Ollama server to: {self.server}")
        elif cmd == "model":
            self.model = arg
            self.config["OLLAMA_MODEL"] = arg
            self.save_config()
            print(f"Using model: {self.model}")
        elif cmd in ("write", "modify", "run"):
            self.send_to_llm(cmd, arg)
        elif cmd == "help":
            self.print_help()
        else:
            self.send_to_llm("chat", command[1:])

    def send_to_llm(self, mode, content):
        prompt = self.format_prompt(mode, content)
        print(f"[LLM] Sending {mode} command to {self.server} using model {self.model}...")

        try:
            response = self.session.post(
                f"{self.server}/api/generate",
                json={"model": self.model, "prompt": prompt, "stream": False},
                timeout=60,
            )
            response.raise_for_status()
            output = response.json().get("response", "")
            self.handle_llm_response(mode, output)
        except Exception as e:
            print(f"LLM request failed: {e}")

    def format_prompt(self, mode, content):
        system_msg = {
            "write": (
                "You are acting as a backend service for a CLI. "
                "Return only a raw JSON object: {\"files\": [{\"path\": \"filename\", \"content\": \"...\"}]}"
            ),
            "modify": (
                "You are modifying existing files based on intent. "
                "Return only a raw JSON object: {\"files\": [{\"path\": \"filename\", \"content\": \"...\"}]}"
            ),
            "run": (
                "You are analyzing the output of a shell command. "
                "Return only a raw JSON object: {\"analysis\": \"Your explanation here.\"}"
            ),
            "chat": (
                "You are a helpful assistant. Respond only as raw JSON: {\"message\": \"Reply text here.\"}"
            )
        }.get(mode, "Respond only with raw JSON format. Do not use markdown.")

        return f"SYSTEM: {system_msg}\n\nUSER INPUT:\n{content}"

    def handle_llm_response(self, mode, output):
        output = output.strip()

        # Try to extract JSON from within code block if present (robust to whitespace)
        fenced_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", output, re.DOTALL)
        if fenced_match:
            output = fenced_match.group(1).strip()

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            print("[ERROR] Failed to parse JSON from LLM.")
            print(output)
            return

        if mode in ("write", "modify"):
            for f in data.get("files", []):
                filepath = Path(self.cwd) / f["path"]
                filepath.parent.mkdir(parents=True, exist_ok=True)
                with open(filepath, "w") as out_file:
                    out_file.write(f["content"])
                print(f"[LLM] Wrote file: {f['path']}")
        elif mode == "run":
            print(f"[LLM Analysis]\n{data.get('analysis')}")
        elif mode == "chat":
            print(f"[LLM Message]\n{data.get('message')}")

    def print_help(self):
        print("""
@write <instruction>   - Ask LLM to write code/files.
@modify <instruction>  - Ask LLM to modify current files.
@run <cmd>             - Run shell command and send output to LLM.
@server <url>          - Set remote Ollama server.
@model <model>         - Set model for LLM.
@help                  - Show this message.
Other input runs as shell commands or uses @ prefix for LLM.
""")

if __name__ == "__main__":
    OllamaCLI().run()

