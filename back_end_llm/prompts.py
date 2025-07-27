#back_end_llm/prompts.py
def get_application_extraction_prompt(chatml_conversation: str) -> str:
    return f"""
    You are given a ChatML conversation about a product. Your task is to extract ONLY extremely specific, product-level, real-world application areas of the product discussed.

    EXTREMELY STRICT GUIDELINES:
    - ONLY include granular, concrete use-cases — specific physical products or engineered processes where the product plays a direct, technical role.
    - DO NOT mention any industry (e.g., automotive, medical, packaging, etc.).
    - DO NOT include any vague functional benefits (e.g., "improves strength", "enhances adhesion", "boosts resistance", "improves performance").
    - For each output, specify the **exact application**, **target component or material**, and **the functional role of the product**.
    - Strictly Include at least 20 granular, product-level applications, output as many as possible, but DO NOT fill the list with generic, business, or industry terms.

    VALID EXAMPLES:
    - "adhesion promoter in polypropylene/glass fiber composite bumpers for injection molding"
    - "compatibilizer in recycled polyethylene/polypropylene multilayer film extrusion"
    - "coupling agent for polypropylene/hemp fiber biocomposites used in outdoor decking tiles"
    - "reactive modifier in polypropylene-based filaments for fused deposition modeling (FDM) 3D printing"

    INSTRUCTIONS:
    - Include applications where the product is used as an intermediary or in combination with other products.
    - Include both established and plausible, unexplored applications based on research or product databases.
    - Output ONLY a comma-separated list of unique, granular, product-level applications. No explanations, no generic terms, no duplicates, no industry or business phrases.

    {chatml_conversation}
    """

def get_google_search_prompt(application: str) -> str:
    return f"""
        You are a B2B technical sales researcher.

        APPLICATION: {application}

        TASK:
        Generate atleast 20 highly effective Google search phrases as possible to find companies, manufacturers, OEMs, or research labs involved in this application. Focus on the material, process, and functional role.

        USE THESE GUIDELINES:
        - Include modifiers like: "supplier", "manufacturer", "OEM", "compounder"
        - Focus only on search terms that would be effective on Google.

        FORMAT:
        Return ONLY a list like this:
        ["<search 1>", "<search 2>", "<search 3>", "<search 4>"]
        """

# def get_brochure_extraction_prompt(text: str) -> str:
#     return f"""You are an expert assistant helping extract both explicit and inferred product applications from brochures.

# Given the following technical brochure content, do the following:
# 1. List all *explicitly mentioned* product applications 
# 2. Infer *potential or alternative applications* even if not directly mentioned, based on your understanding of the product's properties 

# Brochure Text:
# \"\"\"
# {text}
# \"\"\"

# Output format in JSON:
# {{
#   "explicit_applications": [...],
#   "inferred_applications": [...]
# }}

# EXTREMELY STRICT GUIDELINES for inferred_applications:
#     - ONLY include granular, concrete use-cases — specific physical products or engineered processes where the product plays a direct, technical role.
#     - DO NOT mention any industry (e.g., automotive, medical, packaging, etc.).
#     - DO NOT include any vague functional benefits (e.g., "improves strength", "enhances adhesion", "boosts resistance", "improves performance").
#     - For each output, specify the **exact application**, **target component or material**, and **the functional role of the product**.

#     VALID EXAMPLES:
#     - "adhesion promoter in polypropylene/glass fiber composite bumpers for injection molding"
#     - "compatibilizer in recycled polyethylene/polypropylene multilayer film extrusion"
#     - "coupling agent for polypropylene/hemp fiber biocomposites used in outdoor decking tiles"
#     - "reactive modifier in polypropylene-based filaments for fused deposition modeling (FDM) 3D printing"

#     INSTRUCTIONS:
#     - Include applications where the product is used as an intermediary or in combination with other products.
#     - Include both established and plausible, unexplored applications based on research or product databases.
#     - Strictly Include at least 20 granular, product-level applications, output as many as possible, but DO NOT fill the list with generic, business, or industry terms.
#     - Output ONLY a comma-separated list of unique, granular, product-level applications. No explanations, no generic terms, no duplicates, no industry or business phrases.

# """










