import json
import os
import logging

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RULES_PATH = os.path.join(BASE_DIR, "rules.json")

def load_rules():
    """Loads transfer rules from the JSON file."""
    if not os.path.exists(RULES_PATH):
        logger.warning(f"Transfer rules file not found at {RULES_PATH}. Using default behavior (transfer all).")
        return {"rules": [], "default_action": "transfer"}
    try:
        with open(RULES_PATH, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        logger.error(f"Error reading or parsing transfer rules file at {RULES_PATH}: {e}")
        return {"rules": [], "default_action": "transfer"}


def evaluate_rules(collected_data: dict, stage: str) -> str | None:
    """
    Evaluates rules for a specific stage against the collected data.

    Args:
        collected_data (dict): A dictionary containing all information
                               gathered during the call.
        stage (str): The stage of the call to evaluate rules for (e.g., 'spam_check', 'routing').

    Returns:
        str | None: The action to take, or None if no rule matched for the stage.
    """
    rules_config = load_rules()
    rules = rules_config.get("rules", [])
    default_action = rules_config.get("default_action", "transfer")

    for rule in rules:
        # Filter by stage
        if rule.get("stage") != stage:
            continue

        field = rule.get("field")
        operator = rule.get("operator")
        value = rule.get("value")
        action = rule.get("action")

        if not all([field, operator, value, action]):
            logger.warning(f"Skipping malformed rule: {rule}")
            continue

        data_to_check = str(collected_data.get(field, "") or "").lower()
        if not data_to_check:
            continue

        match = False
        if operator == "contains_any":
            if isinstance(value, list):
                if any(str(v).lower() in data_to_check for v in value):
                    match = True
            else:
                logger.warning(f"'contains_any' expects a list value. Skipping rule: {rule}")
        elif operator == "equals":
            if isinstance(value, str):
                if data_to_check == value.lower():
                    match = True
            else:
                logger.warning(f"'equals' expects a string value. Skipping rule: {rule}")
        else:
            logger.warning(f"Unsupported operator '{operator}'. Skipping rule: {rule}")
            continue

        if match:
            logger.info(f"Rule matched for stage '{stage}': {rule}. Returning action: {action}")
            return action

    # Only apply default action for the 'routing' stage
    if stage == "routing":
        logger.info(f"No rules matched for stage '{stage}'. Returning default action: {default_action}")
        return default_action

    # For other stages like 'spam_check', return None if no rule matches
    logger.debug(f"No rules matched for stage '{stage}'. No action taken.")
    return None 