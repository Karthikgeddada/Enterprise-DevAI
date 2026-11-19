import json
from config.llm_config import generate_response
from utils.json_parser import parse_json_response

async def documentation_agent(code_files: list, requirements: str) -> list:
    system_prompt = f"""You are the Documentation Agent.
Write the README.md, setup guide, and API docs based on the requirements and generated code.
You MUST output ONLY valid JSON in the following format. Do not include markdown blocks.
{{
    "files": [
        {{
            "path": "README.md",
            "content": "markdown content..."
        }}
    ]
}}

Requirements: {requirements}
"""
    response = await generate_response(system_prompt)
    data = parse_json_response(response)
    return data.get("files", [])
