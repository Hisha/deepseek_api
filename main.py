from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import subprocess

app = FastAPI()
templates = Jinja2Templates(directory="templates")

LLAMA_PATH = "/home/smithkt/llama.cpp/build/bin/llama-cli"
MODEL_PATH = "/home/smithkt/models/deepseek/deepseek-coder-6.7b-instruct.Q4_K_M.gguf"

@app.get("/", response_class=HTMLResponse)
async def get_chat(request: Request):
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "prompt": "",
        "output": ""
    })

@app.post("/", response_class=HTMLResponse)
async def post_chat(request: Request, prompt: str = Form(...)):
    cmd = [
        LLAMA_PATH,
        "-m", MODEL_PATH,
        "-t", "32",                    # Use more threads (your server is beefy)
        "--ctx-size", "4096",         # Allow longer context
        "--n-predict", "768",         # Generate more tokens (adjust as needed)
        "--temp", "0.2",              # Deterministic for code
        "--repeat-penalty", "1.1",    # Reduce repetition
        "--top-p", "0.95",            # Some variety
        "-p", prompt
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=280)
        output = result.stdout
    except subprocess.TimeoutExpired:
        output = "⏱️ Model took too long and was terminated (timeout). Try shortening your prompt or increasing Nginx/uvicorn timeouts."

    return templates.TemplateResponse("chat.html", {
        "request": request,
        "prompt": prompt,
        "output": output
    })
