"""The lecture-notes agent's skills: Langfuse Skills, with the repo copies as the fallback.

Each skill is a directory under `skills/` with a `SKILL.md` (YAML frontmatter `name`, equal to
the directory name, and `description`) and optional supporting files. In Langfuse each is a Skill
of the same name, tagged `lecture-notes`; the agent gets its `production` version. When Langfuse
is off or a skill there is missing or malformed, the repo copy is used.

They are placed in the agent's virtual filesystem at `/skills/<name>/...`, where deepagents'
`SkillsMiddleware` lists them in the system prompt and the agent reads them on demand.

`push` and `pull` run from `python -m app.prompts push|pull`.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from deepagents.backends.utils import create_file_data

from app import prompts
from app.prompts import LABEL

SKILLS_DIR = Path(__file__).parent / "skills"
TAG = "lecture-notes"
SKILLS_ROOT = "/skills/"


@dataclass
class Skill:
    name: str
    files: dict[str, str]  # relative path -> text
    version: int | None = None  # the Langfuse version; None for the repo copy


def frontmatter_name(text: str) -> str | None:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    if not match:
        return None
    name = re.search(r"^name:\s*['\"]?([\w-]+)['\"]?\s*$", match[1], re.M)
    return name[1] if name else None


def valid(name: str, files: dict[str, str]) -> bool:
    skill = files.get("SKILL.md")
    return skill is not None and frontmatter_name(skill) == name


def local_skills(root: Path = SKILLS_DIR) -> dict[str, dict[str, str]]:
    found = {}
    for directory in sorted(p for p in root.iterdir() if (p / "SKILL.md").is_file()):
        found[directory.name] = {
            file.relative_to(directory).as_posix(): file.read_text(encoding="utf-8")
            for file in sorted(directory.rglob("*"))
            if file.is_file()
        }
    return found


def remote_skill(client: Any, name: str) -> Skill | None:
    try:
        version = client.api.skills.get(name, label=LABEL, include_content=True)
    except Exception as error:
        print(f"Skill {name}: using the repo copy ({type(error).__name__})")
        return None
    files = {f.path: f.content for f in version.files if f.content is not None}
    if not valid(name, files):
        print(f"Skill {name}: Langfuse version {version.version} is malformed; using the repo copy")
        return None
    return Skill(name, files, version.version)


def load_skills(root: Path = SKILLS_DIR) -> list[Skill]:
    client = prompts.langfuse_client()
    skills = []
    for name, files in local_skills(root).items():
        remote = remote_skill(client, name) if client is not None else None
        skills.append(remote or Skill(name, files))
    return skills


def seed_files(skills: list[Skill]) -> dict[str, dict]:
    return {
        f"{SKILLS_ROOT}{skill.name}/{path}": create_file_data(text)
        for skill in skills
        for path, text in skill.files.items()
    }


def references(skills: list[Skill]) -> list[dict]:
    """For the trace's `skills_available` and the run's record of versions."""
    return [
        {"name": s.name, **({"version": s.version} if s.version is not None else {})}
        for s in skills
    ]


def push(client: Any, force: bool = False, root: Path = SKILLS_DIR) -> None:
    """Create Langfuse Skills that do not exist yet; like prompts, an existing skill that differs
    is left alone unless `force`."""
    from langfuse.api.skills import SkillVersionFileInput

    for name, files in local_skills(root).items():
        try:
            current = client.api.skills.get(name, label=LABEL, include_content=True)
        except Exception:
            current = None
        if current is not None:
            remote = {f.path: f.content for f in current.files}
            if remote == files:
                print(f"skill {name}: unchanged (version {current.version})")
                continue
            if not force:
                print(
                    f"skill {name}: differs from Langfuse version {current.version}; "
                    "run pull or push --force"
                )
                continue
        created = client.api.skills.create_version(
            files=[SkillVersionFileInput(path=path, content=text) for path, text in files.items()],
            commit_message=f"Upload {root.name}/{name}",
        )
        client.api.skills.set_labels(created.name, created.version, labels=[LABEL])
        client.api.skills.update(created.name, tags=[TAG])
        print(f"skill {name}: created version {created.version}")


def pull(client: Any, root: Path = SKILLS_DIR) -> None:
    """Write each skill's Langfuse `production` files over the repo copy."""
    for name, files in local_skills(root).items():
        remote = remote_skill(client, name)
        if remote is None:
            print(f"skill {name}: not in Langfuse yet; run push")
        elif remote.files == files:
            print(f"skill {name}: unchanged (version {remote.version})")
        else:
            directory = root / name
            for path, text in remote.files.items():
                target = (directory / path).resolve()
                if not target.is_relative_to(directory.resolve()):
                    print(f"skill {name}: skipped {path!r} (outside the skill)")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            print(f"skill {name}: updated from version {remote.version}")
