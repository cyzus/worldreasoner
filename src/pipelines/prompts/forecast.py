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


def get_forecast_instructions(mode: str, enable_causal_tools: bool) -> str:
    """
    Generate forecast instructions based on mode and causal tool settings.

    Args:
        mode: Forecasting mode ("knowledge_only", "real_time", "container")
        enable_causal_tools: Whether causal reasoning tools are enabled
    """
    if mode == "knowledge_only":
        instructions = KNOWLEDGE_ONLY
    elif mode == "real_time":
        instructions = REAL_TIME
    else:
        instructions = CONTAINER
    if enable_causal_tools:
        instructions += "\n" + WITH_CAUSAL_TOOLS

    return instructions
