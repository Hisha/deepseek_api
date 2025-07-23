from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from db import add_job, init_db, get_all_jobs, get_job
from threading import Thread
import subprocess, time
from datetime import datetime

app = FastAPI()
templates = Jinja2Templates(directory="templates")
templates.env.globals['now'] = datetime.now
init_db()

LLAMA_PATH = "/home/smithkt/llama.cpp/build/bin/llama-cli"
MODEL_PATH = "/home/smithkt/models/deepseek/deepseek-coder-6.7b-instruct.Q4_K_M.gguf"

def worker():
    while True:
        conn = sqlite3.connect("jobs.db")
        c = conn.cursor()
        c.execute("SELECT id, prompt FROM jobs WHERE status = 'queued' ORDER BY id ASC LIMIT 1")
        job = c.fetchone()
        conn.close()

        if job:
            job_id, prompt = job
            update_job_status(job_id, "processing")

            cmd = [
                LLAMA_PATH, "-m", MODEL_PATH, "-t", "24", "--ctx-size", "4096",
                "--n-predict", "768", "--temp", "0.2", "--repeat-penalty", "1.1",
                "--top-p", "0.95", "-p", prompt
            ]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                output = result.stdout
                update_job_status(job_id, "done", output)
            except subprocess.TimeoutExpired:
                update_job_status(job_id, "error", "Job timed out.")
        else:
            time.sleep(3)

Thread(target=worker, daemon=True).start()

#####################################################################################
#                                   GET                                             #
#####################################################################################

@app.get("/", response_class=HTMLResponse)
async def get_chat(request: Request):
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "prompt": "",
        "output": ""
    })

@app.get("/jobs", response_class=HTMLResponse)
async def jobs_page(request: Request):
    jobs = get_all_jobs()
    return templates.TemplateResponse("jobs.html", {"request": request, "jobs": jobs})

#####################################################################################
#                                   POST                                            #
#####################################################################################

@app.post("/", response_class=HTMLResponse)
async def post_chat(request: Request, prompt: str = Form(...)):
    job_id = add_job(prompt)
    message = f"Your job has been queued. Job ID: {job_id}"
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "prompt": "",
        "output": message
    })
