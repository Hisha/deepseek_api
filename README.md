# DeepSeek Chat Web Interface

A lightweight FastAPI web application for running **DeepSeek-Coder 6.7B** locally using `llama.cpp`.  
Provides a simple interactive interface for code generation and integrates with Nginx for reverse proxy access.

---

## 🚀 Features
- **Local LLM inference** with `llama.cpp` (no GPU required)
- Simple **web interface** for prompting and viewing output
- Optimized for **high-core CPU servers** (tuned threading)
- Secure access via **reverse proxy (Nginx + HTTPS)**
- Ready for future enhancements:
  - ✅ Navigation to other apps (e.g., `/flux/`)
  - ✅ Job queue with status indicators
  - ✅ API endpoints for n8n automation

---

## 🛠 Requirements
- Linux server (tested on Ubuntu)
- Python 3.9+
- `llama.cpp` compiled with CMake
- DeepSeek model (GGUF format)

---

## 📂 Project Structure
deepseek_api/
├── main.py # FastAPI app
├── templates/
│ └── chat.html # Frontend UI
├── venv/ # Python virtual environment
└── README.md

---

## 🔧 Installation

### 1. Clone repository

git clone https://github.com/<your-username>/deepseek-web.git
cd deepseek-web

2. Create virtual environment & install dependencies

python3 -m venv venv
source venv/bin/activate

pip install fastapi uvicorn jinja2

3. Download DeepSeek model
Place your model in:

/home/<user>/models/deepseek/deepseek-coder-6.7b-instruct.Q4_K_M.gguf

4. Run the app
uvicorn main:app --host 0.0.0.0 --port 8000

🔒 Systemd Service Setup
To run as a service:

sudo nano /etc/systemd/system/deepseek-api.service

Example:

[Unit]
Description=DeepSeek Chat API
After=network.target

[Service]
User=yourusername
WorkingDirectory=/home/yourusername/deepseek_api
ExecStart=/home/yourusername/deepseek_api/venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
Enable and start:

sudo systemctl daemon-reload
sudo systemctl enable deepseek-api
sudo systemctl start deepseek-api

🌍 Reverse Proxy Setup (Nginx)
Example for /chat:

location /chat/ {
    rewrite ^/chat/(.*)$ /$1 break;
    proxy_pass http://192.168.1.4:8000/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout       300;
    proxy_send_timeout          300;
    proxy_read_timeout          300;
    send_timeout                300;
}

✅ To-Do
 Add navigation between /chat/ and /flux/

 Implement job queue system with progress status

 Add API endpoints for automation (n8n integration)

 Enhance UI with better layout and live updates

📜 License
MIT License
