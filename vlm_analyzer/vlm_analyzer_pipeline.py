import os
import json
import asyncio
import io
import PIL.Image
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from data_utils.fgnet_reader import iter_fgnet_by_id
from llm_utils.llm import query_vlm, OpenRouterError
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from utils.parsing import parse_inner_llm_json

import argparse

parser = argparse.ArgumentParser()
parser.add_argument(
    "--model-name",
    type=str,
    help="Your name",
    default="nvidia/nemotron-nano-12b-v2-vl:free"
)
parser.add_argument(
    "--prompt-name",
    type=str,
    help="Your name",
    default="v2_prompt_analyze_by_age_json_problem_zones_find_all_changes.txt"
)
parser.add_argument(
    "--data-root",
    type=str,
    help="FGNET directory with images/ and points/",
    default="../assets/data/FGNET"
)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)


# --- Assuming these are imported from your existing modules ---
# from your_module import iter_fgnet_by_id, query_vlm, OpenRouterError

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
RESULT_LLM_JSON_FILE = "final_results.json"
HERE = Path(__file__).resolve().parent


def image_to_bytes(img: PIL.Image.Image) -> bytes:
    """Helper to convert PIL Image to bytes for query_vlm."""
    buf = io.BytesIO()
    # Convert to RGB if necessary (e.g., if image is RGBA or Grayscale)
    if img.mode != 'RGB':
        img = img.convert('RGB')
    img.save(buf, format='JPEG')
    return buf.getvalue()



async def process_single_image(item, person_id, system_prompt, api_key, model_name):
    """
    Вспомогательная функция для обработки одного изображения
    """
    img_bytes = image_to_bytes(item["image"])
    age = item["age"]
    
    try:
        logger.info(f"  [Task Start] Person {person_id}, Age {age}")
        
        response_text = await query_vlm(
            api_key=api_key,
            prompt=system_prompt,
            image_bytes=img_bytes,
            extra_text=f"Context: The person in this image is {age} years old.",
            model_name=model_name
        )
        
        logger.info(f"  [Task Success] Person {person_id}, Age {age}")
        
        return {
            "id": person_id,
            "age": age,
            "model_answer": response_text,
            "model_name": model_name,
            "prompt_name": Path(model_name).stem # или передать prompt_stem
        }
    except Exception as e:
        logger.error(f"  [Task Error] Person {person_id}, Age {age}: {e}")
        return None


async def run_experiment(
    prompt_file_name: str, 
    model_name: str, 
    api_key: str,
    root_dir: str = "../assets/data/FGNET",
    version: str = "v1",
    max_concurrent_requests: int = 5 # Ограничение, чтобы не "положить" API
):
    # 1. Setup Naming and Paths
    safe_model_name = model_name.replace("/", "_").replace(":", "_")
    prompt_stem = Path(prompt_file_name).stem
    
    experiment_name = f"{safe_model_name}_{prompt_stem}_{version}"
    run_dir = HERE / "runs" / experiment_name
    cache_dir = run_dir / "cache"
    
    final_output_path = run_dir / RESULT_LLM_JSON_FILE
    if os.path.exists(final_output_path):
        logger.info(f"=== Finished! Use cached {final_output_path} ===")
        return run_dir
    
    run_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 2. Load Prompt
    prompt_path = HERE / "prompts" / prompt_file_name
    if not prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found: {prompt_path}")
    
    with open(prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read()

    logger.info(f"=== Starting Experiment: {experiment_name} ===")
    final_data = []

    # Semaphore для контроля нагрузки на API (аналог пула потоков)
    semaphore = asyncio.Semaphore(max_concurrent_requests)

    async def sem_process(item, p_id):
        async with semaphore:
            res = await process_single_image(item, p_id, system_prompt, api_key, model_name)
            if res:
                res["prompt_name"] = prompt_stem
            return res

    # 3. Process Data
    for group in iter_fgnet_by_id(root_dir=root_dir):
        person_id = group[0]["id"]
        cache_file = cache_dir / f"{person_id}.json"

        if cache_file.exists():
            logger.info(f"Skipping person {person_id}, loading from cache.")
            with open(cache_file, "r") as f:
                cached_group = json.load(f)
                final_data.extend(cached_group)
            continue

        logger.info(f"Processing Person ID: {person_id} ({len(group)} images) in parallel...")

        # Создаем список задач для всей группы (второй цикл теперь параллельный)
        tasks = [sem_process(item, person_id) for item in group]
        
        # Выполняем задачи параллельно
        group_results_raw = await asyncio.gather(*tasks)
        
        # Отфильтровываем None (ошибки)
        group_results = [r for r in group_results_raw if r is not None]

        # Save individual group to cache
        if group_results:
            with open(cache_file, "w+", encoding="utf-8") as f:
                json.dump(group_results, f, indent=4)
            final_data.extend(group_results)
            logger.info(f"Finished group {person_id}: {len(group_results)} results saved.")

    # 4. Finalize
    
    with open(final_output_path, "w", encoding="utf-8") as f:
        json.dump(final_data, f, indent=4)
    
    logger.info(f"=== Finished! Results saved to {final_output_path} ===")
    return run_dir
    

# --- Main execution block ---
if __name__ == "__main__":
    args = parser.parse_args()
    API_KEY = OPENROUTER_API_KEY
    if not API_KEY:
        raise SystemExit("set OPENROUTER_API_KEY")
    MODEL = args.model_name
    PROMPT_FILE = args.prompt_name

   
    run_dir = asyncio.run(run_experiment(
        prompt_file_name=PROMPT_FILE,
        model_name=MODEL,
        api_key=API_KEY,
        root_dir=args.data_root,
    ))
    
    parsed_result_filename = run_dir / "parsed_results.json"
    if not parsed_result_filename.exists():
        parse_inner_llm_json(run_dir / RESULT_LLM_JSON_FILE, parsed_result_filename)