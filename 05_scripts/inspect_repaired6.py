import json
import sys

sys.path.insert(0, r".\05_scripts")
import sonora_msg_pipeline as p

original_path = r".\02_work\translated\sonora_qwen235b_1000.jsonl"
repaired_path = r".\02_work\translated\sonora_qwen235b_1000_repaired_v2.jsonl"

with open(original_path, encoding="utf-8") as f:
    original_rows = [json.loads(line) for line in f]

bad_keys = {
    (str(r.get("file")), str(r.get("line_no")), str(r.get("id")))
    for r in original_rows
    if r.get("status") == "translated"
    and r.get("cs", "").strip()
    and p.detect_repair_issues(r)
}

print("Repair keys:", len(bad_keys))

with open(repaired_path, encoding="utf-8") as f:
    repaired_rows = [json.loads(line) for line in f]

found = 0
for r in repaired_rows:
    key = (str(r.get("file")), str(r.get("line_no")), str(r.get("id")))
    if key in bad_keys:
        found += 1
        print()
        print(f"{r.get('file')} line={r.get('line_no')} id={r.get('id')}")
        print("EN:", r.get("en", ""))
        print("RU:", r.get("ru", ""))
        print("CS:", r.get("cs", ""))

print()
print("Found repaired rows:", found)
