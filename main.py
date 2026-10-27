
import sys
import os
import json
import re
import html
import shutil
import threading
import subprocess
import webbrowser
from pathlib import Path
from urllib.parse import quote_plus

import requests
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QLineEdit, QPushButton, QLabel, QMessageBox, QDialog
)

# ============================================================
# CONFIGURATION
# ============================================================

OLLAMA_URL = "http://127.0.0.1:11434/api/chat"
MODEL_NAME = "llama3:latest"
ENABLE_TTS = True
VOICE_RECORD_SECONDS = 5
WHISPER_MODEL_SIZE = "base"

HOME = Path.home()
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".bmp", ".gif",
    ".webp", ".tif", ".tiff"
}


# ============================================================
# WINDOWS FOLDER HELPERS
# ============================================================

def known_folder(name):
    name = str(name).strip().lower().replace("\\", "/")
    candidates = []

    if name in {"documents", "my documents", "documents folder"}:
        for variable in ("OneDrive", "OneDriveConsumer"):
            if os.environ.get(variable):
                candidates.append(Path(os.environ[variable]) / "Documents")
        candidates.append(HOME / "Documents")

    elif name in {"desktop", "my desktop", "desktop folder"}:
        for variable in ("OneDrive", "OneDriveConsumer"):
            if os.environ.get(variable):
                candidates.append(Path(os.environ[variable]) / "Desktop")
        candidates.append(HOME / "Desktop")

    elif name in {"downloads", "downloads folder"}:
        candidates.append(HOME / "Downloads")

    else:
        return None

    for path in candidates:
        if path.exists():
            return path.resolve()

    return candidates[-1].resolve()


def resolve_path(raw_path):
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("Please specify a file or folder path.")

    raw_path = os.path.expandvars(
        os.path.expanduser(raw_path.strip())
    )

    aliases = {
        "documents": "documents",
        "my documents": "documents",
        "documents folder": "documents",
        "desktop": "desktop",
        "my desktop": "desktop",
        "desktop folder": "desktop",
        "downloads": "downloads",
        "downloads folder": "downloads",
    }

    normalized = raw_path.lower().replace("/", "\\").strip()

    if normalized in aliases:
        return known_folder(aliases[normalized])

    path = Path(raw_path)
    if not path.is_absolute():
        path = HOME / path

    return path.resolve()


def safe_roots():
    roots = [HOME.resolve()]

    for variable in ("OneDrive", "OneDriveConsumer", "USERPROFILE"):
        value = os.environ.get(variable)
        if value:
            base = Path(value)
            roots.extend([
                base.resolve(),
                (base / "Documents").resolve(),
                (base / "Desktop").resolve(),
            ])

    return roots


def ensure_safe_path(path):
    path = path.resolve()

    for root in safe_roots():
        try:
            path.relative_to(root)
            return
        except ValueError:
            pass

    raise PermissionError(
        "For safety, file operations are limited to your user folders."
    )


def find_named_folder(name):
    wanted = name.casefold().strip()
    roots = [
        known_folder("documents"),
        known_folder("desktop"),
        known_folder("downloads"),
        HOME,
    ]

    excluded = {
        ".git", "node_modules", ".venv", "venv",
        "__pycache__", "AppData"
    }
    seen = set()

    for root in roots:
        if not root or not root.exists() or not root.is_dir():
            continue

        try:
            ensure_safe_path(root)
        except PermissionError:
            continue

        for current, dirs, _files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in excluded]

            for directory in dirs:
                path = (Path(current) / directory).resolve()

                if path in seen:
                    continue

                seen.add(path)

                if directory.casefold() == wanted:
                    return path

    return None


# ============================================================
# WINDOWS AND USB HELPERS
# ============================================================

def run_powershell(script, timeout=30):
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "RemoteSigned",
            "-Command", script
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False
    )

    if result.returncode != 0:
        raise RuntimeError(
            (result.stderr or result.stdout).strip()
            or "Windows command failed."
        )

    return result.stdout.strip()


def list_usb_drives():
    script = r"""
$items = @(
    Get-CimInstance Win32_LogicalDisk |
    Where-Object { $_.DriveType -eq 2 } |
    ForEach-Object {
        [PSCustomObject]@{
            Letter = [string]$_.DeviceID
            Label = [string]$_.VolumeName
            FileSystem = [string]$_.FileSystem
            SizeBytes = [int64]$_.Size
        }
    }
)
ConvertTo-Json -InputObject $items -Compress
"""

    output = run_powershell(script)

    if not output:
        return []

    data = json.loads(output)
    return data if isinstance(data, list) else [data]


def human_size(value):
    value = float(value or 0)

    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024

    return f"{value:.1f} TB"


# ============================================================
# USB FORMATTING
# ============================================================

def format_usb_drive(letter, expected_label, expected_size_bytes):
    """
    Full-format a removable drive only after UI confirmation.
    Recheck the drive letter, label and capacity first.
    """
    letter = str(letter).upper().strip()

    if not re.fullmatch(r"[A-Z]:", letter):
        raise ValueError("Invalid drive letter.")

    drives = list_usb_drives()

    matches = [
        drive for drive in drives
        if str(drive.get("Letter", "")).upper() == letter
    ]

    if len(matches) != 1:
        raise RuntimeError(
            "Drive is no longer detected as a removable USB drive."
        )

    drive = matches[0]
    current_label = str(drive.get("Label") or "").strip()
    current_size = int(drive.get("SizeBytes") or 0)

    if current_label.casefold() != str(expected_label or "").strip().casefold():
        raise RuntimeError(
            "USB volume label changed since confirmation. Nothing was formatted."
        )

    if current_size != int(expected_size_bytes or 0):
        raise RuntimeError(
            "USB capacity changed since confirmation. Nothing was formatted."
        )

    drive_letter = letter[0]

    script = (
        "$ErrorActionPreference='Stop'; "
        f"$d=Get-CimInstance Win32_LogicalDisk -Filter \"DeviceID='{letter}'\"; "
        "if (-not $d -or $d.DriveType -ne 2) "
        "{ throw 'Target is not a removable drive.' }; "
        f"$v=Get-Volume -DriveLetter '{drive_letter}'; "
        "if (-not $v) { throw 'Volume not found.' }; "
        f"Format-Volume -DriveLetter '{drive_letter}' "
        "-FileSystem 'exFAT' "
        "-NewFileSystemLabel 'Indominus' "
        "-Confirm:$false -Force -Full | Out-Null; "
        "Write-Output 'FORMAT_COMPLETED'"
    )

    output = run_powershell(script, timeout=7200)

    if "FORMAT_COMPLETED" not in output:
        raise RuntimeError(
            output or "Windows did not confirm formatting."
        )

    return f"Full format completed for {letter}."


class FormatWorker(QThread):
    result_ready = Signal(str)

    def __init__(self, letter, label, size_bytes):
        super().__init__()
        self.letter = letter
        self.label = label
        self.size_bytes = size_bytes

    def run(self):
        try:
            result = format_usb_drive(
                self.letter, self.label, self.size_bytes
            )
        except Exception as exc:
            result = f"Formatting failed: {exc}"

        self.result_ready.emit(result)


# ============================================================
# IMAGE SLIDESHOW
# ============================================================

class SlideshowDialog(QDialog):
    def __init__(self, images, interval_seconds=5, parent=None):
        super().__init__(parent)

        self.images = images
        self.index = 0

        self.setWindowTitle("ULTRON Image Slideshow")
        self.resize(900, 650)

        layout = QVBoxLayout(self)

        self.image_label = QLabel("Loading images...")
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image_label.setMinimumSize(600, 400)
        self.image_label.setStyleSheet(
            "background:#101820;color:white;"
        )
        layout.addWidget(self.image_label)

        self.caption = QLabel("")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.caption)

        controls = QHBoxLayout()

        previous_button = QPushButton("Previous")
        previous_button.clicked.connect(self.previous_image)

        next_button = QPushButton("Next")
        next_button.clicked.connect(self.next_image)

        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)

        controls.addWidget(previous_button)
        controls.addWidget(next_button)
        controls.addWidget(close_button)
        layout.addLayout(controls)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.next_image)
        self.timer.start(max(1, int(interval_seconds)) * 1000)

        self.show_image()

    def show_image(self):
        if not self.images:
            self.image_label.setText("No images found.")
            return

        path = self.images[self.index]
        pixmap = QPixmap(str(path))

        if pixmap.isNull():
            self.image_label.setText(f"Unable to display:\n{path}")
        else:
            self.image_label.setPixmap(
                pixmap.scaled(
                    self.image_label.size(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            )

        self.caption.setText(
            f"{self.index + 1}/{len(self.images)} — {path.name}"
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.show_image()

    def next_image(self):
        if self.images:
            self.index = (self.index + 1) % len(self.images)
            self.show_image()

    def previous_image(self):
        if self.images:
            self.index = (self.index - 1) % len(self.images)
            self.show_image()


# ============================================================
# APPLICATION LAUNCHER
# ============================================================

def open_application(app):
    app = str(app).lower().strip().replace(" ", "_")

    try:
        if app == "notepad":
            subprocess.Popen(["notepad.exe"])

        elif app == "calculator":
            subprocess.Popen(["calc.exe"])

        elif app == "paint":
            subprocess.Popen(["mspaint.exe"])

        elif app == "command_prompt":
            subprocess.Popen(["cmd.exe"])

        elif app == "explorer":
            subprocess.Popen(["explorer.exe"])

        elif app == "chrome":
            candidates = [
                shutil.which("chrome"),
                os.path.expandvars(
                    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"
                ),
                os.path.expandvars(
                    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
                ),
                os.path.expandvars(
                    r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
                ),
            ]

            executable = next(
                (p for p in candidates if p and os.path.isfile(p)), None
            )

            if executable:
                subprocess.Popen([executable])
            else:
                webbrowser.open("https://www.google.com/chrome/")
                return "Chrome wasn't found; opened its download page."

        elif app == "edge":
            candidates = [
                shutil.which("msedge"),
                os.path.expandvars(
                    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
                ),
                os.path.expandvars(
                    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
                ),
            ]

            executable = next(
                (p for p in candidates if p and os.path.isfile(p)), None
            )

            if executable:
                subprocess.Popen([executable])
            else:
                webbrowser.open("https://www.microsoft.com/edge")
                return "Edge wasn't found; opened its download page."

        elif app == "spotify":
            try:
                os.startfile("spotify:")
            except OSError:
                webbrowser.open("https://open.spotify.com/")

        elif app == "youtube":
            webbrowser.open("https://www.youtube.com/")

        elif app == "microsoft_store":
            os.startfile("ms-windows-store:")

        else:
            return f"Unsupported application: {app}"

        return f"Opening {app.replace('_', ' ').title()}."

    except Exception as exc:
        return f"Could not open {app}: {exc}"


# ============================================================
# COMPUTER TOOL DISPATCHER
# ============================================================

def computer_tool(name, args, window=None):
    args = args if isinstance(args, dict) else {}

    if name == "system_info":
        return (
            f"Computer: {os.environ.get('COMPUTERNAME', 'Windows PC')}\n"
            f"User folder: {HOME}\nPlatform: {sys.platform}"
        )

    if name == "open_app":
        app = str(args.get("app", "")).lower().strip()
        allowed = {
            "notepad", "calculator", "paint", "chrome", "edge",
            "explorer", "spotify", "youtube", "microsoft_store",
            "command_prompt"
        }

        if app not in allowed:
            return f"Unsupported application: {app}"

        if app == "command_prompt":
            return "Please explicitly request Command Prompt before I open it."

        return open_application(app)

    if name == "list_files":
        folder = resolve_path(args.get("path", "Desktop"))
        ensure_safe_path(folder)

        if not folder.is_dir():
            return f"Folder not found: {folder}"

        items = list(folder.iterdir())[:100]

        return (
            f"Contents of {folder}:\n"
            + (
                "\n".join(
                    ("[DIR] " if p.is_dir() else "[FILE] ") + p.name
                    for p in items
                )
                or "(empty folder)"
            )
        )

    if name == "search_files":
        term = str(args.get("name", "")).strip()

        if not term:
            return "Please specify a file name."

        root = resolve_path(args.get("path", str(HOME)))
        ensure_safe_path(root)

        if not root.is_dir():
            return f"Folder not found: {root}"

        found = []
        excluded = {
            ".git", "node_modules", ".venv", "venv",
            "__pycache__", "AppData"
        }

        for current, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in excluded]

            for filename in files:
                if term.casefold() in filename.casefold():
                    found.append(str(Path(current) / filename))

                    if len(found) >= 50:
                        break

            if len(found) >= 50:
                break

        return (
            "Matching files:\n" + "\n".join(found)
            if found else f"No files matching {term!r} were found."
        )

    if name == "create_folder":
        folder = resolve_path(args.get("path", ""))
        ensure_safe_path(folder)

        if folder.exists():
            return f"That path already exists: {folder}"

        folder.mkdir(parents=True)
        return f"Created folder: {folder}"

    if name == "open_file":
        path = resolve_path(args.get("path", ""))
        ensure_safe_path(path)

        if not path.exists():
            return f"File or folder not found: {path}"

        os.startfile(str(path))
        return f"Opened: {path}"

    if name == "open_website":
        url = str(args.get("url", "")).strip()

        if not url.lower().startswith(("https://", "http://")):
            return "Only HTTP and HTTPS websites are supported."

        webbrowser.open(url)
        return f"Opened website: {url}"

    if name == "search_web":
        query = str(args.get("query", "")).strip()

        if not query:
            return "Please specify a search query."

        webbrowser.open(
            "https://www.google.com/search?q=" + quote_plus(query)
        )
        return f"Searching for {query}."

    if name == "list_usb":
        drives = list_usb_drives()

        if not drives:
            return "No removable USB drives detected."

        return "Detected USB drives:\n" + "\n".join(
            f"{d.get('Letter')} | "
            f"Label: {d.get('Label') or '(no label)'} | "
            f"Size: {human_size(d.get('SizeBytes'))}"
            for d in drives
        )

    if name == "open_folder_slideshow":
        folder_name = str(args.get("folder_name", "")).strip()

        if not folder_name:
            return "Please specify the folder name."

        folder = find_named_folder(folder_name)

        if not folder:
            return (
                f"I couldn't find {folder_name!r} under your "
                "Desktop, Documents, Downloads, or user folder."
            )

        images = []

        for current, dirs, files in os.walk(folder):
            dirs[:] = [
                d for d in dirs
                if d not in {".git", "node_modules", ".venv", "venv"}
            ]

            for filename in files:
                path = Path(current) / filename

                if path.suffix.lower() in IMAGE_EXTENSIONS:
                    images.append(path)

                    if len(images) >= 500:
                        break

            if len(images) >= 500:
                break

        if not images:
            return f"Found {folder}, but no supported images were found."

        if window is None:
            return "The slideshow window is unavailable."

        interval = max(1, min(int(args.get("interval_seconds", 5)), 3600))
        window.show_slideshow(images, interval)

        return (
            f"Started slideshow with {len(images)} images from {folder}. "
            f"Changing every {interval} seconds."
        )

    if name == "lock_computer":
        subprocess.Popen([
            "rundll32.exe", "user32.dll,LockWorkStation"
        ])
        return "Computer locked."

    # Formatting is never allowed through a model-selected tool.
    if name == "format_usb":
        return (
            "Formatting must use the direct USB identification and "
            "confirmation flow. No action was performed."
        )

    return f"Tool '{name}' is not available. No action was performed."


# ============================================================
# DIRECT COMMAND ROUTER
# ============================================================

def direct_command(message):
    text = message.strip()
    lower = text.casefold()

    # Prevent negated launch commands from executing.
    if re.search(
        r"\b(do not|don't|dont|never)\s+(open|launch|start)\b",
        lower
    ):
        if "command prompt" in lower or re.search(r"\bcmd\b", lower):
            return True, "Understood. I will not open Command Prompt."

    # Slideshow request.
    if re.search(
        r"\b(swipe|slideshow|slide show|change.*picture|pictures?.*every)\b",
        lower
    ):
        match = re.search(
            r"\b(?:folder\s+named|folder\s+called|folder\s+)"
            r"([A-Za-z0-9 _-]+?)(?:\s+and\b|[,?.!]|$)",
            text, re.I
        )

        if not match:
            match = re.search(
                r"\b(?:named|called)\s+"
                r"([A-Za-z0-9 _-]+?)(?:\s+and\b|[,?.!]|$)",
                text, re.I
            )

        if not match:
            return True, (
                "Tell me the exact folder name, e.g. "
                "'Open the folder named Naincy and change pictures every 5 seconds'."
            )

        folder_name = match.group(1).strip()
        seconds_match = re.search(
            r"every\s+(\d+)\s*(?:seconds?|secs?|s)\b", lower
        )
        interval = int(seconds_match.group(1)) if seconds_match else 5
        interval = max(1, min(interval, 3600))

        return True, (
            "SLIDESHOW|"
            + json.dumps({
                "folder_name": folder_name,
                "interval_seconds": interval
            })
        )

    # USB format request: identify target, then require confirmation.
    if (
        re.search(r"\b(format|fully format|full format)\b", lower)
        and re.search(r"\b(pen ?drive|pendrive|usb|removable drive)\b", lower)
    ):
        match = re.search(
            r"\b(?:named|called|labelled|labeled)\s+"
            r"['\"]?([A-Za-z0-9 _-]+?)['\"]?"
            r"(?:\s+and\b|\s+then\b|[?.!,]|$)",
            text, re.I
        )

        if not match:
            return True, (
                "Please provide the pen drive name, e.g. "
                "'Format the pen drive named Indominus'."
            )

        requested_label = match.group(1).strip().rstrip(" .!?")

        try:
            drives = list_usb_drives()

            exact = [
                d for d in drives
                if str(d.get("Label") or "").strip().casefold()
                == requested_label.casefold()
            ]

            if len(exact) == 1:
                drive = exact[0]

            elif len(exact) > 1:
                return True, (
                    f"Multiple USB drives match {requested_label!r}. "
                    "Disconnect the other drives and retry."
                )

            elif len(drives) == 1:
                drive = drives[0]

                # A nickname may not match the actual Windows volume label.
                # Show the real drive identity and ask for confirmation.
                actual_label = str(drive.get("Label") or "")
                payload = {
                    "letter": drive.get("Letter"),
                    "label": actual_label,
                    "size": human_size(drive.get("SizeBytes")),
                    "size_bytes": int(drive.get("SizeBytes") or 0),
                    "requested_name": requested_label,
                }

                return True, "FORMAT_CONFIRMATION|" + json.dumps(payload)

            else:
                listing = "\n".join(
                    f"{d.get('Letter')} | "
                    f"Label: {d.get('Label') or '(no label)'} | "
                    f"Size: {human_size(d.get('SizeBytes'))}"
                    for d in drives
                ) or "No removable drives detected."

                return True, (
                    f"Couldn't match label {requested_label!r}.\n{listing}"
                )

            payload = {
                "letter": drive.get("Letter"),
                "label": str(drive.get("Label") or ""),
                "size": human_size(drive.get("SizeBytes")),
                "size_bytes": int(drive.get("SizeBytes") or 0),
                "requested_name": requested_label,
            }

            return True, "FORMAT_CONFIRMATION|" + json.dumps(payload)

        except Exception as exc:
            return True, f"USB detection failed: {exc}"

    # Known folders.
    folder_match = re.search(
        r"\b(open|show|go to)\s+(?:my\s+)?"
        r"(documents(?: folder)?|desktop|downloads(?: folder)?)\b",
        lower
    )

    if folder_match:
        target = folder_match.group(2)
        path = resolve_path(target)

        if not path.exists():
            return True, f"Folder does not exist: {path}"

        try:
            os.startfile(str(path))
            return True, f"Opened {target}: {path}"
        except Exception as exc:
            return True, f"Could not open {target}: {exc}"

    # USB inventory.
    if (
        re.search(r"\b(list|show|find|detect)\b", lower)
        and re.search(r"\b(usb|pen ?drive|pendrive|removable drive)\b", lower)
    ):
        try:
            return True, computer_tool("list_usb", {})
        except Exception as exc:
            return True, f"USB detection failed: {exc}"

    app_patterns = [
        (r"\b(open|launch|start)\s+(the\s+)?notepad\b", "notepad"),
        (r"\b(open|launch|start)\s+(the\s+)?(calculator|calc)\b", "calculator"),
        (r"\b(open|launch|start)\s+(the\s+)?(paint|mspaint)\b", "paint"),
        (r"\b(open|launch|start)\s+(the\s+)?(file explorer|explorer)\b", "explorer"),
        (r"\b(open|launch|start)\s+(the\s+)?(chrome|google chrome)\b", "chrome"),
        (r"\b(open|launch|start)\s+(the\s+)?(edge|microsoft edge)\b", "edge"),
        (r"\b(open|launch|start)\s+(the\s+)?spotify\b", "spotify"),
        (r"\b(open|launch|start)\s+(the\s+)?youtube\b", "youtube"),
        (r"\b(open|launch|start)\s+(the\s+)?(microsoft store|store)\b", "microsoft_store"),
        (r"\b(open|launch|start)\s+(the\s+)?(command prompt|cmd)\b", "command_prompt"),
    ]

    for pattern, app in app_patterns:
        if re.search(pattern, lower):
            return True, open_application(app)

    url_match = re.search(r"https?://\S+", text, re.I)

    if url_match and re.search(r"\b(open|visit|go to)\b", lower):
        url = url_match.group(0).rstrip(".,!?")
        webbrowser.open(url)
        return True, f"Opening {url}."

    if re.match(r"^\s*(search|google)\s+(for\s+)?", lower):
        query = re.sub(
            r"^\s*(search|google)\s+(for\s+)?",
            "", text, flags=re.I
        ).strip()

        if query:
            webbrowser.open(
                "https://www.google.com/search?q=" + quote_plus(query)
            )
            return True, f"Searching for {query}."

    if "instagram" in lower and re.search(r"\b(download|install)\b", lower):
        query = quote_plus("Instagram")

        try:
            os.startfile("ms-windows-store://search/?query=" + query)
            return True, "Opened Microsoft Store search for Instagram."
        except Exception:
            webbrowser.open(
                "https://apps.microsoft.com/search?query=" + query
            )
            return True, "Opened Microsoft Store website search."

    return False, None


# ============================================================
# OLLAMA AI WORKER
# ============================================================

class AIWorker(QThread):
    response_ready = Signal(str)
    error_occurred = Signal(str)

    def __init__(self, message, history):
        super().__init__()
        self.message = message
        self.history = list(history)

    def run(self):
        system_prompt = r"""
You are ULTRON, a Windows desktop assistant.
Return exactly one JSON object without Markdown.

Normal chat:
{"action":"chat","reply":"Short helpful response"}

Supported computer tools:
{"action":"computer_tool","tool":"system_info","args":{}}
{"action":"computer_tool","tool":"open_app","args":{"app":"notepad"}}
{"action":"computer_tool","tool":"list_files","args":{"path":"Documents"}}
{"action":"computer_tool","tool":"search_files","args":{"name":"resume","path":"Documents"}}
{"action":"computer_tool","tool":"create_folder","args":{"path":"Desktop\\Projects"}}
{"action":"computer_tool","tool":"open_file","args":{"path":"Documents\\notes.txt"}}
{"action":"computer_tool","tool":"open_website","args":{"url":"https://example.com"}}
{"action":"computer_tool","tool":"search_web","args":{"query":"Java interview questions"}}
{"action":"computer_tool","tool":"list_usb","args":{}}
{"action":"computer_tool","tool":"open_folder_slideshow","args":{"folder_name":"Naincy","interval_seconds":5}}
{"action":"computer_tool","tool":"lock_computer","args":{}}

Allowed tools:
system_info, open_app, list_files, search_files, create_folder,
open_file, open_website, search_web, list_usb,
open_folder_slideshow, lock_computer.

Never invent tools or execute shell commands.
Never format, erase, partition, or wipe a drive through an AI-selected tool.
Formatting must go through the application's direct identification and confirmation flow.
Never claim success unless a tool reports success.
Ask a concise question if a path or target is ambiguous.
"""

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self.history[-10:])
        messages.append({"role": "user", "content": self.message})

        try:
            response = requests.post(
                OLLAMA_URL,
                json={
                    "model": MODEL_NAME,
                    "messages": messages,
                    "stream": False,
                    "format": "json",
                },
                timeout=180
            )

            response.raise_for_status()

            answer = response.json().get(
                "message", {}
            ).get("content", "").strip()

            if not answer:
                self.error_occurred.emit("Ollama returned an empty response.")
            else:
                self.response_ready.emit(answer)

        except requests.exceptions.ConnectionError:
            self.error_occurred.emit(
                "Cannot connect to Ollama. Make sure Ollama is running."
            )
        except requests.exceptions.Timeout:
            self.error_occurred.emit("Ollama timed out.")
        except Exception as exc:
            self.error_occurred.emit(str(exc))


# ============================================================
# CUSTOM ULTRON VOICE
# ============================================================

class SpeechWorker(QThread):
    error_occurred = Signal(str)
    finished_speaking = Signal()

    def __init__(self, text):
        super().__init__()
        self.text = str(text)

    def run(self):
        try:
            from ultron_voice import speak
            if self.text.strip():
                speak(self.text)
        except Exception as exc:
            self.error_occurred.emit(f"ULTRON voice error: {exc}")
        finally:
            self.finished_speaking.emit()


# ============================================================
# MICROPHONE AND WHISPER
# ============================================================

class VoiceWorker(QThread):
    transcription_ready = Signal(str)
    status_changed = Signal(str)
    error_occurred = Signal(str)

    _model = None
    _model_lock = threading.Lock()

    def run(self):
        try:
            import sounddevice as sd
            import numpy as np
            from faster_whisper import WhisperModel

            sample_rate = 16000
            self.status_changed.emit("Recording... speak now.")

            recording = sd.rec(
                int(VOICE_RECORD_SECONDS * sample_rate),
                samplerate=sample_rate,
                channels=1,
                dtype="float32"
            )
            sd.wait()
            audio = np.squeeze(recording)

            with VoiceWorker._model_lock:
                if VoiceWorker._model is None:
                    self.status_changed.emit(
                        "Loading speech recognition model..."
                    )
                    VoiceWorker._model = WhisperModel(
                        WHISPER_MODEL_SIZE,
                        device="cpu",
                        compute_type="int8"
                    )

                model = VoiceWorker._model

            segments, _ = model.transcribe(
                audio,
                language="en",
                vad_filter=True
            )

            transcript = " ".join(
                segment.text.strip() for segment in segments
            ).strip()

            if transcript:
                self.transcription_ready.emit(transcript)
            else:
                self.error_occurred.emit(
                    "No speech detected. Please try again."
                )

        except Exception as exc:
            self.error_occurred.emit(f"Voice input failed: {exc}")


# ============================================================
# MAIN WINDOW
# ============================================================

class DesktopAssistant(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("ULTRON - AI Desktop Assistant")
        self.resize(1000, 720)

        self.history = []
        self.ai_worker = None
        self.speech_worker = None
        self.voice_worker = None
        self.format_worker = None
        self.slideshow_dialog = None
        self.current_user_message = ""

        self.setup_ui()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        title = QLabel("ULTRON • AI DESKTOP ASSISTANT")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            "font-size:25px;font-weight:bold;color:#00d4ff;padding:12px;"
        )
        layout.addWidget(title)

        self.status_label = QLabel(f"Local AI: {MODEL_NAME} | Ready")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setPlaceholderText(
            "Give ULTRON a computer command or ask a question."
        )
        self.chat_display.setStyleSheet("""
            QTextEdit {
                background:#101820;
                color:white;
                border:1px solid #00d4ff;
                border-radius:10px;
                padding:12px;
                font-size:15px;
            }
        """)
        layout.addWidget(self.chat_display)

        row = QHBoxLayout()

        self.input_box = QLineEdit()
        self.input_box.setPlaceholderText(
            "Try: Open Documents or show Naincy pictures every 5 seconds"
        )
        self.input_box.returnPressed.connect(self.send_message)
        row.addWidget(self.input_box)

        self.send_button = QPushButton("Send")
        self.send_button.clicked.connect(self.send_message)
        row.addWidget(self.send_button)
        layout.addLayout(row)

        self.voice_button = QPushButton(
            f"Voice Input ({VOICE_RECORD_SECONDS} seconds)"
        )
        self.voice_button.clicked.connect(self.start_voice_input)
        layout.addWidget(self.voice_button)

        clear_button = QPushButton("Clear Conversation")
        clear_button.clicked.connect(self.clear_conversation)
        layout.addWidget(clear_button)

        central.setStyleSheet(
            "QWidget {background:#0b1118;color:white;}"
        )

    def show_slideshow(self, images, interval_seconds=5):
        self.slideshow_dialog = SlideshowDialog(
            images, interval_seconds, self
        )
        self.slideshow_dialog.show()
        self.slideshow_dialog.raise_()
        self.slideshow_dialog.activateWindow()

    def add_chat(self, speaker, message, color):
        safe_message = html.escape(str(message)).replace("\n", "<br>")
        self.chat_display.append(
            f"<b style='color:{color}'>{html.escape(speaker)}:</b> "
            f"{safe_message}"
        )

    def send_message(self):
        message = self.input_box.text().strip()

        if not message:
            return

        if self.ai_worker and self.ai_worker.isRunning():
            self.status_label.setText("Please wait for the current response.")
            return

        self.current_user_message = message
        self.input_box.clear()
        self.add_chat("You", message, "#00d4ff")

        handled, reply = direct_command(message)

        if handled:
            if reply.startswith("FORMAT_CONFIRMATION|"):
                payload = json.loads(reply.split("|", 1)[1])
                self.confirm_format(payload)
                return

            if reply.startswith("SLIDESHOW|"):
                payload = json.loads(reply.split("|", 1)[1])

                try:
                    result = computer_tool(
                        "open_folder_slideshow", payload, self
                    )
                except Exception as exc:
                    result = f"Slideshow failed: {exc}"

                self.finish_reply(message, result)
                return

            self.finish_reply(message, reply)
            return

        self.status_label.setText("ULTRON is thinking...")
        self.send_button.setEnabled(False)
        self.voice_button.setEnabled(False)

        self.ai_worker = AIWorker(message, self.history)
        self.ai_worker.response_ready.connect(self.handle_ai_response)
        self.ai_worker.error_occurred.connect(self.handle_ai_error)
        self.ai_worker.finished.connect(self.restore_controls)
        self.ai_worker.start()

    def confirm_format(self, payload):
        letter = str(payload.get("letter", "")).upper()
        label = str(payload.get("label") or "")
        size = str(payload.get("size", "unknown"))
        requested = str(payload.get("requested_name") or label or "(no label)")

        message = (
            f"Detected drive: {letter}\n"
            f"Actual volume label: {label or '(no label)'}\n"
            f"Capacity: {size}\n"
            f"Requested name: {requested}\n\n"
            "A FULL FORMAT erases data on this drive. "
            "Continue only if the drive letter and capacity are correct."
        )

        answer = QMessageBox.warning(
            self,
            "Confirm USB full format",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:
            self.finish_reply(
                self.current_user_message,
                "Formatting cancelled. No changes were made."
            )
            return

        self.send_button.setEnabled(False)
        self.voice_button.setEnabled(False)
        self.status_label.setText("Formatting USB drive...")

        self.format_worker = FormatWorker(
            letter,
            label,
            int(payload.get("size_bytes") or 0)
        )
        self.format_worker.result_ready.connect(self.handle_format_result)
        self.format_worker.start()

    def handle_format_result(self, result):
        self.finish_reply(self.current_user_message, result)
        self.send_button.setEnabled(True)
        self.voice_button.setEnabled(True)

    def handle_ai_response(self, answer):
        try:
            data = json.loads(answer)
        except json.JSONDecodeError:
            self.finish_reply(
                self.current_user_message,
                "I couldn't interpret the AI response safely."
            )
            return

        if not isinstance(data, dict):
            self.finish_reply(
                self.current_user_message,
                "The AI returned an invalid response."
            )
            return

        action = str(data.get("action", "chat")).lower()

        if action == "chat":
            reply = str(
                data.get("reply", "I couldn't generate a response.")
            )

        elif action == "error":
            reply = str(
                data.get("message")
                or data.get("reply")
                or "The AI could not complete that request."
            )

        elif action == "computer_tool":
            tool = str(data.get("tool", "")).strip()
            args = data.get("args", {})

            if not isinstance(args, dict):
                reply = "Invalid tool arguments. Nothing was done."
            elif tool == "format_usb":
                reply = (
                    "Formatting must use the direct drive-identification "
                    "and confirmation flow."
                )
            elif (
                tool == "open_app"
                and str(args.get("app", "")).lower() == "command_prompt"
            ):
                reply = (
                    "Please explicitly request Command Prompt before I open it."
                )
            else:
                try:
                    reply = computer_tool(tool, args, self)
                except Exception as exc:
                    reply = f"Computer action failed: {exc}"

        elif action == "open_url":
            reply = computer_tool(
                "open_website", {"url": data.get("url", "")}, self
            )

        elif action == "search_web":
            reply = computer_tool(
                "search_web", {"query": data.get("query", "")}, self
            )

        elif action == "open_app":
            app = str(data.get("app", "")).lower().strip()

            if app == "command_prompt":
                reply = (
                    "Please explicitly request Command Prompt before I open it."
                )
            else:
                reply = open_application(app)

        else:
            reply = f"Unsupported action: {action}"

        self.finish_reply(self.current_user_message, reply)

    def finish_reply(self, user_message, reply):
        self.add_chat("ULTRON", reply, "#7CFC00")

        self.history.extend([
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": str(reply)}
        ])
        self.history = self.history[-20:]

        self.status_label.setText("Ready")
        self.speak_reply(reply)

    def handle_ai_error(self, error):
        self.add_chat("Error", error, "#ff6666")
        self.status_label.setText("Ready")

    def restore_controls(self):
        self.send_button.setEnabled(True)
        self.voice_button.setEnabled(True)

    def speak_reply(self, text):
        if not ENABLE_TTS or not str(text).strip():
            return

        if self.speech_worker and self.speech_worker.isRunning():
            return

        self.speech_worker = SpeechWorker(str(text))
        self.speech_worker.error_occurred.connect(self.handle_tts_error)
        self.speech_worker.finished_speaking.connect(
            self.handle_tts_finished
        )

        self.status_label.setText("ULTRON is speaking...")
        self.speech_worker.start()

    def handle_tts_error(self, error):
        self.add_chat("Voice error", error, "#ff9900")
        self.status_label.setText("Voice error")

    def handle_tts_finished(self):
        self.status_label.setText("Ready")

    def clear_conversation(self):
        self.history.clear()
        self.chat_display.clear()
        self.status_label.setText("Conversation cleared")

    def start_voice_input(self):
        if self.ai_worker and self.ai_worker.isRunning():
            return

        if self.voice_worker and self.voice_worker.isRunning():
            return

        self.voice_button.setEnabled(False)
        self.status_label.setText("Preparing microphone...")

        self.voice_worker = VoiceWorker()
        self.voice_worker.transcription_ready.connect(
            self.handle_transcription
        )
        self.voice_worker.status_changed.connect(
            self.show_voice_status
        )
        self.voice_worker.error_occurred.connect(
            self.show_voice_error
        )
        self.voice_worker.finished.connect(
            lambda: self.voice_button.setEnabled(True)
        )
        self.voice_worker.start()

    def show_voice_status(self, message):
        self.status_label.setText(message)

    def show_voice_error(self, message):
        self.add_chat("Voice", message, "#ff9900")
        self.status_label.setText(message)

    def handle_transcription(self, text):
        self.input_box.setText(text)
        self.add_chat("Heard", text, "#00d4ff")
        self.send_message()


# ============================================================
# START APPLICATION
# ============================================================

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = DesktopAssistant()
    window.show()
    sys.exit(app.exec())
