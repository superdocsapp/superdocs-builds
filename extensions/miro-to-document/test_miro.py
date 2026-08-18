from miro_parser import get_board_items, parse_items, print_structure


print("Fetching Miro board...")

raw_items = get_board_items()

print(f"\nMiro board connected successfully!")
print(f"Items found: {len(raw_items)}")

parsed_items = parse_items(raw_items)

print_structure(parsed_items)

print("\nDone.")