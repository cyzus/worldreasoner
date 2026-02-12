KNOWLEDGE_ONLY = """
Forecast the outcome of this question. 
Use get_question to see the details, then submit your forecast.
Make reasonable forecasts based on your knowledge.
"""

REAL_TIME = """
Forecast the outcome of this question. 
Use get_question to see the details, research if needed, and then submit your forecast.
Make reasonable forecasts based on what you learn.
"""

CONTAINER = """
Forecast the outcome of this question. 
Use get_question to see the details, research if needed, and then submit your forecast.
The information you have access to might be limited due to the simulated date or evidence collection process.
Make reasonable forecasts nonetheless.
"""

WITH_CAUSAL_TOOLS = """
Use the reasoning tools and graph inspector to build and refine an event reasoning graph before submitting your forecast.

OUTCOME IMPACT ANALYSIS (Optional but Recommended):
When building your reasoning graph, consider analyzing how each significant event impacts EACH possible outcome:
- For binary questions: How does the event affect "Yes" vs "No" likelihood?
- For MCQ questions: How does it affect each option's likelihood?
- Use event_identifier with outcome_impacts parameter to record your assessments
- This structured analysis helps avoid hindsight bias and consider all evidence systematically

When you identify an event, you can record its impact:
  outcome_impacts='[{"outcome_event_id": "evt_...", "direction": "positive", "magnitude": 0.7, "confidence": 0.8, "reasoning": "..."}]'

An event that makes one outcome MORE likely often makes the opposite LESS likely.
Use graph_inspector to view your outcome impact analysis.
"""


CONDITION_PREAMBLES = {
    "vanilla_llm": (
        "You are making a forecast based purely on your training knowledge. "
        "You do NOT have access to any external search tools or web browsing capabilities. "
        "Rely entirely on what you already know to make your prediction.\n\n"
    ),
    "structured_scenario": (
        "You have access to causal reasoning tools but no external search. "
        "Use the causal reasoning tools to build an explicit event graph representing "
        "possible future scenarios before making your prediction. Generate at least 3 events "
        "and connect them causally to model how the situation might unfold.\n\n"
    ),
    "search_enabled": (
        "You have access to search and article retrieval tools. "
        "Use the search and article retrieval tools to gather relevant evidence "
        "before making your forecast. Focus on finding the most recent and relevant information.\n\n"
    ),
    "worldreasoner": (
        "You have access to both search tools and causal reasoning tools. "
        "First, search for relevant evidence. Then, structure your findings using the "
        "causal reasoning tools to build an event graph that maps out causal relationships "
        "and possible scenarios before making your prediction.\n\n"
    ),
    "oracle": (
        "You have access to information very close to the question's resolution date. "
        "Search thoroughly for the most recent evidence available. Use the causal reasoning "
        "tools to structure your analysis. Your goal is to find definitive or near-definitive "
        "evidence about the outcome.\n\n"
    ),
}


def get_forecast_instructions(
    mode: str,
    enable_causal_tools: bool,
    condition_name: str | None = None,
) -> str:
    """
    Generate forecast instructions based on mode and causal tool settings.

    Args:
        mode: Forecasting mode ("knowledge_only", "real_time", "container")
        enable_causal_tools: Whether causal reasoning tools are enabled
        condition_name: Optional condition name to prepend a condition-specific preamble
    """
    if mode == "knowledge_only":
        instructions = KNOWLEDGE_ONLY
    elif mode == "real_time":
        instructions = REAL_TIME
    else:
        instructions = CONTAINER
    if enable_causal_tools:
        instructions += "\n" + WITH_CAUSAL_TOOLS

    if condition_name and condition_name in CONDITION_PREAMBLES:
        instructions = CONDITION_PREAMBLES[condition_name] + instructions

    return instructions
