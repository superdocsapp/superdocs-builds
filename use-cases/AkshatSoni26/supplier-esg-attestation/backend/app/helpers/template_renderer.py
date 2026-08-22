import os
import jinja2
from app.core.config import settings


class TemplateRenderer:
    """
    Data-driven template rendering engine using Jinja2.
    Loads templates directly from the configured templates directory.
    """

    _env: jinja2.Environment | None = None

    @classmethod
    def get_environment(cls) -> jinja2.Environment:
        if cls._env is None:
            templates_path = settings.TEMPLATES_DIR
            if not os.path.exists(templates_path):
                # Fallback to local app/templates
                templates_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "templates")
            cls._env = jinja2.Environment(
                loader=jinja2.FileSystemLoader(templates_path),
                autoescape=False,
                trim_blocks=True,
                lstrip_blocks=True,
            )
        return cls._env

    @classmethod
    def render(cls, template_name: str, **context) -> str:
        """Renders a Jinja2 template with the provided context dictionary."""
        env = cls.get_environment()
        template = env.get_template(template_name)
        return template.render(**context)
