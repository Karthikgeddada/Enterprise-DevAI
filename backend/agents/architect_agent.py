from config.llm_config import generate_response

async def architect_agent(prompt: str, requirements: str) -> str:
    system_prompt = f"""You are the Architect Agent.
Based on the user's prompt and the extracted requirements, design the project structure, modules, dependencies, and folder tree.
Provide the folder structure and a brief description of each module.

User Prompt: {prompt}
Requirements: {requirements}
"""
    return await generate_response(system_prompt)
