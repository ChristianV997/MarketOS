from pathlib import Path

import yaml


def test_dependabot_covers_python_docker_and_github_actions():
    policy = yaml.safe_load((Path(__file__).parents[1] / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    ecosystems = {entry["package-ecosystem"] for entry in policy["updates"]}
    assert ecosystems == {"pip", "docker", "github-actions"}
