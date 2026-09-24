"""Write the OpenAPI schema without starting a server:
``python -m app.scripts.export_openapi ../frontend/openapi.json``

The frontend generates its TypeScript client from this file, and CI regenerates it to
prove the committed client matches the API.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from app.core.config import Settings
from app.main import create_app


def main() -> None:
    # Fixed settings so the schema does not depend on whoever runs the export.
    app = create_app(Settings(_env_file=None, app_env="test", metrics_enabled=False))
    schema = json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"
    if len(sys.argv) > 1:
        Path(sys.argv[1]).write_text(schema, encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(schema)


if __name__ == "__main__":
    main()
