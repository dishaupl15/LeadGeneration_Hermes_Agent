"""Test calling Hermes CLI via piped stdin (non-interactive headless mode)."""
import subprocess, sys, time

# The correct way to call Hermes headlessly:
# pipe the prompt via stdin with --cli --yolo --skills lead-generation-search
# Hermes reads from stdin when not a TTY

hermes_env = {
    **__import__('os').environ.copy(),
    "PYTHONIOENCODING": "utf-8",
    "PYTHONUTF8": "1",
}

prompt = "Find 2 real estate companies in Pune. Use lead-generation-search skill. Output ONLY JSON."

cmd = [
    "hermes",
    "--cli",
    "--yolo", 
    "--skills", "lead-generation-search",
    "-z", prompt,
]

print(f"Running: {' '.join(cmd)}")
print("Waiting for Hermes response (this may take 2-5 minutes)...")

try:
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        env=hermes_env,
    )
    print("STDOUT:", result.stdout[:2000])
    print("STDERR:", result.stderr[:500])
    print("Return code:", result.returncode)
except subprocess.TimeoutExpired:
    print("TIMED OUT after 300s")
except Exception as e:
    print(f"ERROR: {type(e).__name__}: {e}")
