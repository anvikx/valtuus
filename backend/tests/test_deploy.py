"""A failed deployment must skip migrations only while restarting the last healthy image."""

import os
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize("tag", ["healthy", "broken"])
def test_deploy_migration_flag(tmp_path, tag):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    source = Path(__file__).resolve().parents[2] / "scripts" / "deploy.sh"
    deploy = scripts / "deploy.sh"
    deploy.write_bytes(source.read_bytes())
    (tmp_path / ".last_good_tag").write_text("previous")
    docker = tmp_path / "docker"
    docker.write_text(
        "#!/bin/bash\n"
        'if [[ "$*" == "compose up "* ]]; then\n'
        '  echo "${IMAGE_TAG}:${SKIP_DATABASE_MIGRATIONS}" >> "$DEPLOY_TEST_LOG"\n'
        '  [[ "${IMAGE_TAG}" != "broken" ]]\n'
        "  exit $?\n"
        "fi\n"
    )
    docker.chmod(0o755)
    log = tmp_path / "starts"
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "REGISTRY": "test",
        "DEPLOY_TEST_LOG": str(log),
        # Normal deploy must override an inherited rollback flag.
        "SKIP_DATABASE_MIGRATIONS": "true",
    }

    result = subprocess.run(["bash", str(deploy), tag], env=env, capture_output=True, check=False)

    if tag == "broken":
        assert result.returncode == 1
        assert log.read_text().splitlines() == ["broken:false", "previous:true"]
        assert (tmp_path / ".last_good_tag").read_text() == "previous"
    else:
        assert result.returncode == 0
        assert log.read_text().splitlines() == ["healthy:false"]
        assert (tmp_path / ".last_good_tag").read_text().strip() == "healthy"
