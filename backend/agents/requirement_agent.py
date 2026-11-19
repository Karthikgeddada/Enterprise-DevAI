from config.llm_config import generate_response

async def requirement_agent(prompt: str) -> str:
    system_prompt = f"""You are the Requirement Analyzer Agent.
Analyze the user's prompt and extract the core features, application type, and tech stack needed.
Provide a structured list of functional and non-functional requirements.

User Prompt: {prompt}
"""
    return await generate_response(system_prompt)
