from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from db import add_job, init_db, get_all_jobs, get_job, update_job_status
from threading import Thread
from datetime import datetime
import subprocess
import time
import sqlite3
import logging
import pytz
import os
import psutil
from dateutil import parser

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

app = FastAPI(root_path="/chat")
templates = Jinja2Templates(directory="templates")
templates.env.globals["now"] = datetime.now
eastern = pytz.timezone("US/Eastern")

# Initialize database
init_db()

LLAMA_PATH = "/home/smithkt/llama.cpp/build/bin/llama-cli"
MODEL_PATH = "/home/smithkt/models/deepseek/deepseek-coder-6.7b-instruct.Q4_K_M.gguf"

def format_local_time(iso_str):
    if not iso_str:
        return "—"
    try:
        utc_time = parser.isoparse(iso_str)
        local_time = utc_time.astimezone(eastern)
        return local_time.strftime("%b %d, %Y %I:%M %p %Z")  # e.g., Jul 23, 2025 11:20 AM EDT
    except Exception:
        return iso_str

templates.env.filters["localtime"] = format_local_time

def get_autotune_settings(prompt):
    cpu_threads = os.cpu_count()
    available_ram_gb = psutil.virtual_memory().available / (1024**3)

    # Base values
    ctx_size = 4096
    n_predict = 1024
    batch_size = 512

    # Adjust n_predict based on RAM
    if available_ram_gb > 128:  # Huge server
        n_predict = 4096
        batch_size = 1024
    elif available_ram_gb > 64:
        n_predict = 3072
        batch_size = 768
    elif available_ram_gb > 32:
        n_predict = 2048
        batch_size = 512
    else:  # Low memory
        n_predict = 1024
        batch_size = 256

    # For very long prompts, increase n_predict
    if len(prompt) > 1000 and n_predict < 4096:
        n_predict = min(4096, n_predict + 512)

    return {
        "threads": str(cpu_threads),
        "ctx_size": str(ctx_size),
        "n_predict": str(n_predict),
        "batch_size": str(batch_size)
    }

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

@app.get("/jobs/table", response_class=HTMLResponse)
async def jobs_table(request: Request):
    jobs = get_all_jobs()
    return templates.TemplateResponse("partials/job_table.html", {"request": request, "jobs": jobs})

@app.get("/job/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: int):
    job = get_job(job_id)
    return templates.TemplateResponse("partials/job_detail.html", {"request": request, "job": job})

@app.get("/status")
async def status():
    """Quick health check for worker"""
    return JSONResponse({"status": "running", "worker": "active"})

#####################################################################################
#                                   POST                                            #
#####################################################################################

@app.post("/", response_class=HTMLResponse)
async def post_chat(request: Request, prompt: str = Form(...), generate_project: str = Form(None)):
    job_type = "project" if generate_project else "chat"
    job_id = add_job(prompt, job_type)
    message = f"Your {job_type} job has been queued. Job ID: {job_id}"
    return templates.TemplateResponse("chat.html", {
        "request": request,
        "prompt": "",
        "output": message
    })

#####################################################################################
#                                  Worker                                           #
#####################################################################################

def worker():
    logging.info("Worker thread started (Auto-Tune enabled)")
    while True:
        try:
            conn = sqlite3.connect("jobs.db")
            c = conn.cursor()
            c.execute("SELECT id, prompt FROM jobs WHERE status = 'queued' ORDER BY id ASC LIMIT 1")
            job = c.fetchone()
            conn.close()

            if job:
                job_id, prompt = job
                logging.info(f"Picked job {job_id} for processing")
                update_job_status(job_id, "processing")

                # Auto-tune settings
                settings = get_autotune_settings(prompt)
                logging.info(f"Applied Auto-Tune: Threads={settings['threads']} n_predict={settings['n_predict']} Batch={settings['batch_size']}")

                cmd = [
                    LLAMA_PATH, "-m", MODEL_PATH,
                    "-t", settings["threads"],
                    "--ctx-size", settings["ctx_size"],
                    "--n-predict", settings["n_predict"],
                    "--batch-size", settings["batch_size"],
                    "--temp", "0.2", "--repeat-penalty", "1.1",
                    "--top-p", "0.95", "-p", prompt
                ]

                try:
                    logging.info(f"Running llama-cli for job {job_id}")
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=1200)
                    output = result.stdout
                    logging.info(f"Job {job_id} completed successfully")
                    update_job_status(job_id, "done", output)
                except subprocess.TimeoutExpired:
                    logging.error(f"Job {job_id} timed out")
                    update_job_status(job_id, "error", "Job timed out.")
            else:
                time.sleep(3)
        except Exception as e:
            logging.error(f"Worker encountered an error: {e}")
            time.sleep(5)

# Start the worker in a background thread
Thread(target=worker, daemon=True).start()
