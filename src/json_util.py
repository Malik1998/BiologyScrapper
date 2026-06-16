"""Small helper shared by LLM-backed filters/stages for parsing model output."""


def extract_json(text: str) -> str:
    """Pull the first top-level {...} object out of an LLM response.

    Models often wrap JSON in markdown code fences or add surrounding prose;
    this grabs the substring between the first '{' and the last '}'.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]
    return text
