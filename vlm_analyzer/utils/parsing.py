import json

def safe_parse_model_answer(raw):
    try:
        raw = raw.replace("json", '').replace("```", "")
        parsed = json.loads(raw)
        if "regions" in parsed:
            return parsed
    except Exception:
        pass
    return None

def parse_inner_llm_json(file_path, output_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    for item in data:
        item["model_parsed"] = safe_parse_model_answer(item.get("model_answer"))
    
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
