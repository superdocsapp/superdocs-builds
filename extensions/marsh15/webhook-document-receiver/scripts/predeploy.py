from bootstrap_templates import main as bootstrap_templates
from migrate import migrate

if __name__ == "__main__":
    migrate()
    bootstrap_templates()
