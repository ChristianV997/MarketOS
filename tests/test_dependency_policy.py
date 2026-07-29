from pathlib import Path

import yaml


def test_dependabot_covers_python_docker_and_github_actions():
    policy = yaml.safe_load((Path(__file__).parents[1] / ".github" / "dependabot.yml").read_text(encoding="utf-8"))
    ecosystems = {entry["package-ecosystem"] for entry in policy["updates"]}
    assert ecosystems == {"pip", "docker", "github-actions"}


def test_ci_audits_installed_base_and_optional_agent_dependencies_without_reresolving():
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert workflow.count("pip-audit --local --strict") == 2
    assert "pip-audit -r requirements.txt" not in workflow
