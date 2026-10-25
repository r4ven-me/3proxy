#!/usr/bin/env python3
"""Validate, build, commit and publish a release. Invoked by make release TAG=... ."""

import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
REPOSITORIES = ("docker.io/r4venme/3proxy", "ghcr.io/r4ven-me/3proxy")


def run(*command, capture=False, timeout=300):
    print("+ " + shlex.join(command), flush=True)
    environment = os.environ.copy()
    environment.update(GIT_EDITOR="true", GIT_TERMINAL_PROMPT="0")
    return subprocess.run(command, cwd=ROOT, env=environment, check=True,
                          text=True, stdout=subprocess.PIPE if capture else None,
                          timeout=timeout).stdout


def validate_tag(tag):
    if not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag):
        raise ValueError("set TAG to a valid Docker tag (1–128 ASCII characters), e.g. make release TAG=v1.0.0")
    if tag == "latest":
        raise ValueError("TAG must be a version, not latest; latest is published automatically")
    return tag


def release(tag):
    validate_tag(tag)
    root = Path(run("git", "rev-parse", "--show-toplevel", capture=True).strip())
    if root.resolve() != ROOT:
        raise ValueError("the project must be the root of its own Git repository")
    branch = run("git", "symbolic-ref", "--quiet", "--short", "HEAD", capture=True).strip()
    run("git", "check-ref-format", "refs/tags/" + tag)
    if run("git", "tag", "--list", tag, capture=True).strip():
        raise ValueError(f"Git tag {tag} already exists locally")
    if run("git", "ls-files", "--unmerged", capture=True).strip():
        raise ValueError("resolve Git merge conflicts before releasing")
    for marker in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply"):
        path = Path(run("git", "rev-parse", "--git-path", marker, capture=True).strip())
        if not path.is_absolute():
            path = ROOT / path
        if path.exists():
            raise ValueError("finish the active Git merge/rebase/cherry-pick/revert before releasing")
    run("git", "var", "GIT_AUTHOR_IDENT", capture=True)
    run("git", "var", "GIT_COMMITTER_IDENT", capture=True)
    run("docker", "info", capture=True, timeout=30)
    run("git", "remote", "get-url", "origin")
    # This also checks repository access, including an empty remote repository.
    if run("git", "ls-remote", "--tags", "origin", "refs/tags/" + tag,
           capture=True, timeout=30).strip():
        raise ValueError(f"Git tag {tag} already exists on origin")

    run("sh", "scripts/test.sh")
    run("docker", "compose", "config", "--quiet")
    references = [f"{repository}:{version}"
                  for repository in REPOSITORIES for version in (tag, "latest")]
    build = ["docker", "build", "--file", "docker/Dockerfile"]
    for reference in references:
        build.extend(("--tag", reference))
    # Build once, before changing Git history or publishing anything.
    run(*build, ".", timeout=900)

    # Deliberately include all non-ignored project changes, including new files.
    run("git", "add", "--all")
    if run("git", "diff", "--cached", "--name-only", capture=True).strip():
        run("git", "commit", "-m", f"chore(release): {tag}")
    else:
        run("git", "rev-parse", "--verify", "HEAD", capture=True)
        print("No changes to commit; releasing the current commit.", flush=True)
    run("git", "tag", "--annotate", tag, "--message", f"Release {tag}")
    # Neither the remote branch nor the Git tag is updated if either push fails.
    run("git", "push", "--atomic", "origin", f"HEAD:refs/heads/{branch}", f"refs/tags/{tag}")
    for reference in references:
        run("docker", "push", reference, timeout=900)
    print("\nRelease published:\n" + "\n".join(references), flush=True)


def main():
    try:
        release(os.environ.get("TAG", ""))
    except (ValueError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"release: {error}", file=sys.stderr)
        print("Stopped without rollback. If publication started, inspect Git and both registries before retrying.",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
