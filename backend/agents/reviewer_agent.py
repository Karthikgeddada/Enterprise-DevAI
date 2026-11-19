from config.llm_config import generate_response
import json

async def reviewer_agent(code_files: list) -> str:
    files_str = json.dumps(code_files, indent=2)
    system_prompt = f"""You are the Reviewer Agent.
Review the provided code files for best practices, structure, naming conventions, and logic issues.
List the potential issues or suggestions for improvement. If the code is good, say "LGTM".

Code Files: {files_str}
"""
    return await generate_response(system_prompt)
