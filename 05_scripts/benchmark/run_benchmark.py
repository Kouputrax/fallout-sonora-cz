import os
import sys
import subprocess
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent.parent.parent
PIPELINE = ROOT / "05_scripts" / "sonora_msg_pipeline.py"
TEST_SET = ROOT / "02_work" / "benchmark" / "test_set.jsonl"
EVALUATOR = ROOT / "05_scripts" / "benchmark" / "evaluate_benchmark.py"

MODELS = [
    {"provider": "openrouter", "model": "openrouter/owl-alpha"},
    {"provider": "openrouter", "model": "tencent/hy3-preview"},
    {"provider": "openrouter", "model": "anthropic/claude-3-haiku"},
    {"provider": "openrouter", "model": "qwen/qwen-2.5-72b-instruct"},
    {"provider": "ollama", "model": "qwen2.5:7b", "host": "http://localhost:11434"}
]

import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", help="List of model IDs to test")
    args = parser.parse_args()
    
    print("Starting Model Benchmark...")
    if not TEST_SET.exists():
        print("Creating test set...")
        create_script = ROOT / "05_scripts" / "benchmark" / "create_benchmark_set.py"
        subprocess.run([sys.executable, str(create_script)], check=True)
        
    models_to_run = MODELS
    if args.models:
        models_to_run = []
        for m in args.models:
            provider = "openrouter"
            if m.startswith("ollama/"):
                provider = "ollama"
                m = m.replace("ollama/", "")
            models_to_run.append({"provider": provider, "model": m, "host": "http://localhost:11434"})
            
    procs = []
    for m in models_to_run:
        provider = m["provider"]
        model_id = m["model"]
        safe_name = model_id.replace("/", "_").replace(":", "_").replace("-", "_")
        out_file = ROOT / "02_work" / "benchmark" / f"results_{safe_name}.jsonl"
        
        print(f"\n[START] Benchmarking Model: {model_id} ({provider})")
        
        args_cmd = [
            sys.executable, str(PIPELINE),
            "translate",
            "--input", str(TEST_SET),
            "--out", str(out_file),
            "--provider", provider,
            "--model", model_id,
            "--limit", "170",
            "--batch-size", "10"
        ]
        
        if provider == "ollama":
            args_cmd.extend(["--host", m["host"]])
            
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        p = subprocess.Popen(args_cmd, env=env)
        procs.append((model_id, p))
        time.sleep(1) # stagger starts slightly
        
    for model_id, p in procs:
        p.wait()
        print(f"\n[DONE] Model: {model_id}")
        
    print("\nRunning Evaluation...")
    subprocess.run([sys.executable, str(EVALUATOR)], check=True)
    
if __name__ == "__main__":
    main()
