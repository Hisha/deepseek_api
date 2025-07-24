import subprocess
import logging
import re

def clean_code_output(raw_output):
    """Clean LLM output for Quick Mode: remove preamble, fences, and extra artifacts."""
    # 1. Remove everything before and including 'assistant'
    cleaned = re.sub(r'^.*assistant\s*', '', raw_output, flags=re.DOTALL)

    # 2. Remove lines like 'user', 'assistant'
    cleaned = re.sub(r'^(user|assistant)\s*', '', cleaned, flags=re.MULTILINE)

    # 3. Remove markdown code fences
    cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned.strip(), flags=re.MULTILINE)
    cleaned = re.sub(r"```$", "", cleaned, flags=re.MULTILINE)

    # 4. Remove trailing artifacts like '> EOF by user'
    cleaned = re.sub(r'> EOF by user', '', cleaned)

    # 5. Trim leading junk before first code-like keyword
    code_start = re.search(r'(#include|def |class |import |int main|public |function|\w+\s*=\s*)', cleaned)
    if code_start:
        cleaned = cleaned[code_start.start():]

    return cleaned.strip()

def generate_quick_code(job_id, prompt, LLAMA_PATH, MODEL_CODE_PATH, update_job_status):
    """Generates a single code snippet for quick mode jobs."""
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
        update_job_status(job_id, "error", "Failed to generate quick snippet.")
        return False
