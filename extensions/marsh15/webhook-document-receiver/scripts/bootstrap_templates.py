from app.config import get_settings
from app.template_bootstrap import bootstrap_templates


def main() -> None:
    uploaded = bootstrap_templates(get_settings())
    if uploaded:
        print(f"uploaded templates: {', '.join(uploaded)}")
    else:
        print("all required templates already exist")


if __name__ == "__main__":
    main()
