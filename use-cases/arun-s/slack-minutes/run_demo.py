import json, pathlib
from minutes import structure, minutes_html
msgs = json.load(open(pathlib.Path(__file__).resolve().parent / "sample_thread.json"))["messages"]
s = structure(msgs)
print("attendees :", s["attendees"])
print("decisions :", [d["text"] for d in s["decisions"]])
print("actions   :", [(a["owner"], a["text"]) for a in s["actions"]])
print("\n--- minutes HTML ---\n", minutes_html(s, "Q3 Planning — minutes"))
