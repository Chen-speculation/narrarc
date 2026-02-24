import re
path = r'c:\Users\Administrator\narrarc\backend\scripts\run_realtalk_eval.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add params to run_single_eval_batch
content = content.replace(
    'def run_single_eval_batch(input_path, self_id, talker_id, arc_cases_path, limit_cases, mode, output_json):',
    'def run_single_eval_batch(input_path, self_id, talker_id, arc_cases_path, limit_cases, mode, output_json, debug_retrieval=False, output_debug_json=None):'
)

# 2. Add debug args to cmd in run_single_eval_batch
content = content.replace(
    '''    print(\"=== Step 3: Run eval pipeline ===\")
    cmd = [sys.executable, str(ROOT / \"scripts\" / \"eval_realtalk_accuracy.py\"), \"--chat-id\", talker_id, \"--mode\", mode, \"--output-json\", output_json]
    r = subprocess.run(cmd, cwd=str(ROOT))''',
    '''    print(\"=== Step 3: Run eval pipeline ===\")
    cmd = [sys.executable, str(ROOT / \"scripts\" / \"eval_realtalk_accuracy.py\"), \"--chat-id\", talker_id, \"--mode\", mode, \"--output-json\", output_json]
    if debug_retrieval:
        cmd.extend([\"--debug-retrieval\"])
    if output_debug_json:
        cmd.extend([\"--output-debug-json\", output_debug_json])
    r = subprocess.run(cmd, cwd=str(ROOT))'''
)

# 3. Add parser args
content = content.replace(
    'parser.add_argument(\"--config-changes\", default=\"\", help=\"Config change description\")\n    args = parser.parse_args()',
    'parser.add_argument(\"--config-changes\", default=\"\", help=\"Config change description\")\n    parser.add_argument(\"--debug-retrieval\", action=\"store_true\", help=\"Log retrieval checkpoints\")\n    parser.add_argument(\"--output-debug-json\", help=\"Write retrieval debug logs to JSON file\")\n    args = parser.parse_args()'
)

# 4. Pass debug args in batch loop - need to find the call and add params
# When output_debug_json is provided, use it; when debug_retrieval only, use experiments/debug_baseline.json
content = content.replace(
    'code = run_single_eval_batch(str(chat_path), self_id, talker_id, arc_str, args.limit_cases, args.mode, out_json)',
    '''debug_out = args.output_debug_json or (str(ROOT / \"experiments\" / \"debug_baseline.json\") if args.debug_retrieval else None)
            code = run_single_eval_batch(str(chat_path), self_id, talker_id, arc_str, args.limit_cases, args.mode, out_json, debug_retrieval=args.debug_retrieval, output_debug_json=debug_out)'''
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print('Patched successfully')
