import json
from deepdiff import DeepDiff

def generate_plan_diff(plan_old_path, plan_new_path):
    with open(plan_old_path, 'r') as f:
        old_data = json.load(f)
    with open(plan_new_path, 'r') as f:
        new_data = json.load(f)
        
    diff = DeepDiff(old_data, new_data, ignore_order=True)
    return diff

def format_diff_as_text(diff):
    lines = []
    if 'values_changed' in diff:
        for path, changes in diff['values_changed'].items():
            clean_path = path.replace("root", "").replace("['", "").replace("']", " -> ")
            lines.append(f"- {clean_path}: Changed from {changes['old_value']} to {changes['new_value']}")
    
    if 'dictionary_item_added' in diff:
        for path in diff['dictionary_item_added']:
            clean_path = path.replace("root", "").replace("['", "").replace("']", "")
            lines.append(f"- {clean_path}: New item added")
            
    return "\n".join(lines)

def generate_superdocs_instructions(plan_old_path, plan_new_path, employee=None):
    diff = generate_plan_diff(plan_old_path, plan_new_path)
    diff_text = format_diff_as_text(diff)
    
    instructions = [
        f"Update the year references from 2025 to 2026.",
        f"Generate a 'What changed since last year' section using the following diff:\n{diff_text}",
        f"Update all comparison tables to reflect the new 2026 data."
    ]
    
    if employee:
        instructions.append(
            f"Generate a personalized enrollment letter for {employee['name']}. "
            f"Their current elections are: {', '.join(employee['current_elections'])}. "
            f"They are in {employee['location']}, employment type: {employee['employment_type']}, "
            f"union status: {employee['union_status']}."
        )
        
    return "\n".join(instructions)
