KEEP_TYPES = {
    "Starting XI", "Shot", "Duel", "Clearance", "Interception",
    "Dribble", "Foul Committed", "Bad Behaviour", "Substitution",
    "Goal Keeper", "Own Goal For", "Own Goal Against", "Pass",
}

TOP_KEYS = (
    "id", "index", "period", "timestamp", "minute", "second", "type",
    "possession", "possession_team", "play_pattern", "team", "player",
    "position", "location", "under_pressure", "counterpress", "tactics",
)

PASS_KEYS = (
    "shot_assist", "goal_assist", "assisted_shot_id",
    "recipient", "end_location", "outcome",
)

SUB_KEYS = {"Goal Keeper": "goalkeeper", "Starting XI": None}


def slim_event(event):
    type_name = (event.get("type") or {}).get("name")
    if type_name not in KEEP_TYPES:
        return None

    slim = {k: event[k] for k in TOP_KEYS if k in event}

    if type_name == "Pass":
        p = event.get("pass") or {}
        if not (p.get("shot_assist") or p.get("goal_assist")):
            return None
        slim["pass"] = {k: p[k] for k in PASS_KEYS if k in p}
        return slim

    sub_key = SUB_KEYS.get(type_name, type_name.lower().replace(" ", "_"))
    if sub_key and sub_key in event:
        sub = event[sub_key]
        if sub_key == "shot" and isinstance(sub, dict):
            sub = {k: v for k, v in sub.items() if k != "freeze_frame"}
        slim[sub_key] = sub

    return slim
