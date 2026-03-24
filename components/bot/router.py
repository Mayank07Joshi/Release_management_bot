# components/bot/router.py

from .nlp import extract_entities
import components.bot.intents as intents  # <— safer than from .intents import classify_intent
from .executor import execute_intent
from .formatter import format_response

def bot_answer(user_query: str, df):
    """
    Main bot controller:
      - Extract entities
      - Classify intent
      - Execute
      - Format
    """
    entities = extract_entities(user_query)
    intent = intents.classify_intent(user_query, entities)  # <— call through module
    result = execute_intent(intent, entities, df, user_query)
    final = format_response(intent, result, entities)
    return final