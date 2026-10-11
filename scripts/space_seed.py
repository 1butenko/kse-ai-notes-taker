"""Copy a finished notes run out of the uploads volume for the demo Space, without book text."""

import json
import shutil
import sys
from pathlib import Path

uploads, out = Path("/data/uploads"), Path("/seed")
for name in sys.argv[1:]:
    course, run = name.split("/")
    source, target = uploads / course / "notes" / run, out / course / "notes" / run
    target.mkdir(parents=True, exist_ok=True)
    for file in ["run.json", "notes.pdf", "notes.qmd"]:
        if (source / file).is_file():
            shutil.copy(source / file, target / file)
    for pdf in source.glob("topics/*/note.pdf"):
        (target / pdf.parent.relative_to(source)).mkdir(parents=True, exist_ok=True)
        shutil.copy(pdf, target / pdf.relative_to(source))
    document = json.loads((source / "notes.json").read_text())
    for section in document["sections"]:
        for topic in section["topics"]:
            for item in topic["evidence"]:
                item["text"] = ""
    (target / "notes.json").write_text(json.dumps(document, ensure_ascii=False))
    print(f"Seeded {name}")
