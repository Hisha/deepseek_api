import subprocess
import logging
import re

def clean_code_output(raw_output):
    """Remove extra text, markdown fences, and system prompts from LLM output."""
    # Remove user/assistant markers and EOF markers
    cleaned = re.sub(r"(user|assistant).*?\n", "", raw_output, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"> EOF by user", "", cleaned)
    # Remove markdown code fences
    cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"```$", "", cleaned)
    return cleaned.strip()

def generate_quick_code(job_id, prompt, LLAMA_PATH, MODEL_CODE_PATH, update_job_status):
    update_job_status(job_id, "processing", "Generating quick snippet...")
    logging.info(f"[QuickMode Job {job_id}] Generating code snippet...")

    cmd = [
        LLAMA_PATH, "-m", MODEL_CODE_PATH,
        "-t", "28",
        "--ctx-size", "4096",
        "--n-predict", "2048",
        "--temp", "0.3",
        "--top-p", "0.9",
        "--repeat-penalty", "1.05",
        "-p", f"You are a senior developer. Generate ONLY code for: {prompt}"
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        raw_output = result.stdout.strip()
        cleaned_output = clean_code_output(raw_output)

        if not cleaned_output:
            cleaned_output = "# ERROR: Empty snippet generated."

        update_job_status(job_id, "completed", cleaned_output)
        logging.info(f"[QuickMode Job {job_id}] Quick code generated successfully.")
        return True
    except Exception as e:
        logging.error(f"[QuickMode Job {job_id}] Error: {e}")
        update_job_status(job_id, "error", f"Failed to generate quick snippet.")
        return False
