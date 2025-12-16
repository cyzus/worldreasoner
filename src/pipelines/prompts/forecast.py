knowledge_only = \
"""
Forecast the outcome of this question. 
Use get_question to see the details, then submit your forecast.
Make reasonable forecasts based on your knowledge.
"""

real_time = \
"""
Forecast the outcome of this question. 
Use get_question to see the details, research if needed, and then submit your forecast.
Make reasonable forecasts based on what you learn.
"""

container = \
"""
Forecast the outcome of this question. 
Use get_question to see the details, research if needed, and then submit your forecast.
The information you have access to might be limited due to the simulated date or evidence collection process.
Make reasonable forecasts nonetheless.
"""

with_causal_tools = \
"""
Use the reasoning tools and graph inspector to build and refine an event reasoning graph before submitting your forecast.
"""

def get_forecast_instructions(mode: str, enable_causal_tools: bool) -> str:
    """
    Generate forecast instructions based on mode and causal tool settings.

    Args:
        mode: Forecasting mode ("knowledge_only", "real_time", "container")
        enable_causal_tools: Whether causal reasoning tools are enabled
    """
    if mode == "knowledge_only":
        instructions = knowledge_only
    elif mode == "real_time":
        instructions = real_time
    else:
        instructions = container

    if enable_causal_tools:
        instructions += "\n" + with_causal_tools

    return instructions