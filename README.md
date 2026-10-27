# AI Voice-Based Desktop Assistant 🎙️

An AI-powered voice-based desktop assistant built with Python, designed to understand voice commands, generate intelligent responses using a locally running Large Language Model (LLM), and help users interact with their Windows computer.

## 🚀 Project Overview

The AI Voice-Based Desktop Assistant aims to make computer interaction more natural through voice commands and AI-powered assistance. It combines speech processing, natural language understanding, and desktop automation to create a hands-free assistant experience.

The project uses **Ollama** to run language models locally, reducing the need to send prompts to an external AI API.

## ✨ Features

- 🎤 **Voice Input:** Capture spoken commands through a microphone.
- 🧠 **Local AI Intelligence:** Generate responses using locally hosted language models through Ollama.
- 🗣️ **Speech Interaction:** Support voice-based interaction with the assistant.
- 💻 **Windows Integration:** Designed to assist with desktop tasks through commands.
- 🔒 **Local Model Support:** Run supported AI models locally using Ollama.
- 🐍 **Python-Based Architecture:** Built using Python and supporting libraries.

*Note: Features depend on the modules currently implemented in the project.*

## 🛠️ Technology Stack

- **Programming Language:** Python
- **LLM Runtime:** Ollama
- **Speech Processing:** Python audio and speech-processing libraries
- **Operating System:** Windows
- **Development Environment:** Visual Studio Code

## 📁 Project Structure

```text
AI Voice-Based Desktop Assistant/
│
├── main.py
├── mic_test.py
├── ultron_voice.py
├── models/
├── .gitignore
└── README.md
```

The `ai-voice-assistant/` directory may contain additional application files and dependencies, depending on the current project structure.

## ⚙️ Prerequisites

Before running the project, ensure you have:

- Windows 10 or Windows 11
- Python installed
- Git installed (optional, for cloning)
- Ollama installed and running
- A supported Ollama model downloaded
- A working microphone

## 📥 Installation and Setup

### 1. Install Ollama

Download Ollama from:

https://ollama.com/

Install it and download a supported model. For example:

```powershell
ollama pull phi
```

Alternatively, use another model supported by your system.

### 2. Clone the repository

```bash
git clone https://github.com/Deveshkumar80/AI-Desktop-Assistant.git
```

### 3. Navigate to the project directory

```powershell
cd AI-Desktop-Assistant
```

### 4. Create a virtual environment

```powershell
python -m venv .venv
```

### 5. Activate the virtual environment

```powershell
.\.venv\Scripts\Activate.ps1
```

### 6. Install dependencies

If a `requirements.txt` file is available, run:

```powershell
pip install -r requirements.txt
```

Otherwise, install the packages required by the project's Python modules.

### 7. Run the assistant

```powershell
python main.py
```

Ensure Ollama is running and the configured model is available before starting the assistant.

## 🎯 Project Goals

- Improve hands-free interaction with computers.
- Integrate local LLMs into a desktop application.
- Explore speech recognition and speech synthesis.
- Build a foundation for an intelligent desktop agent.
- Expand desktop automation capabilities through modular tools.

## 🔮 Future Enhancements

- Add more reliable speech recognition.
- Improve natural and customizable voice output.
- Support multi-step task execution.
- Add application launching and file search capabilities.
- Introduce action verification and error handling.
- Develop a graphical user interface.
- Explore mobile integration and cloud deployment.

## 🔐 Security and Privacy

- Never commit passwords, API keys, tokens, or private configuration files.
- Keep virtual environments and unnecessary generated files out of version control.
- Review desktop automation actions carefully before granting permissions.
- Local LLM execution does not automatically guarantee that every component of the application operates offline.

## 👨‍💻 Author

**Deveshkumar80**

GitHub: https://github.com/Deveshkumar80

## 📄 License

No license has been specified yet. All rights are reserved by default unless a license is added to the repository.

---

⭐ If you find this project interesting, consider starring the repository.
