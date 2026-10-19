"""Write the table of config options in docs/Configuration.md from PvPiConfig's descriptions."""

import json
from pathlib import Path

from pvpi.config import PvPiConfig

PAGE = Path(__file__).resolve().parent.parent / "docs" / "Configuration.md"
START, END = "<!-- options -->", "<!-- /options -->"


def table() -> str:
    lines = ["| Option | Default | What it's for |", "|---|---|---|"]
    for name, field in PvPiConfig.model_fields.items():
        default = "set automatically" if field.default_factory else f"`{json.dumps(field.default)}`"  # as in config.json
        lines.append(f"| `{name}` | {default} | {field.description} |")
    return "\n".join(lines)


if __name__ == "__main__":
    text = PAGE.read_text()
    before, rest = text.split(START)
    after = rest.split(END)[1]
    PAGE.write_text(f"{before}{START}\n{table()}\n{END}{after}")
