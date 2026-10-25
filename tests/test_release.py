"""Release workflow tests; all external commands are mocked."""

import importlib.util
import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import call, patch


SPEC = importlib.util.spec_from_file_location(
    "release_script", Path(__file__).resolve().parents[1] / "scripts" / "release.py"
)
release_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_script)


class ValidateTagTests(unittest.TestCase):
    def test_valid_tags(self):
        for tag in ("v1.2.3", "1", "_release", "Release-1_2.3", "a" * 128):
            with self.subTest(tag=tag):
                self.assertEqual(release_script.validate_tag(tag), tag)

    def test_invalid_tags(self):
        for tag in ("", "a" * 129, ".version", "-version", "v 1", "v/1",
                    "v:1", "v\n", "версия", "v;echo"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                release_script.validate_tag(tag)

    def test_latest_is_reserved(self):
        with self.assertRaisesRegex(ValueError, "latest"):
            release_script.validate_tag("latest")


class ReleaseTests(unittest.TestCase):
    TAG = "v1.2.3"
    REFERENCES = (
        "docker.io/r4venme/3proxy:v1.2.3",
        "docker.io/r4venme/3proxy:latest",
        "ghcr.io/r4ven-me/3proxy:v1.2.3",
        "ghcr.io/r4ven-me/3proxy:latest",
    )

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        root_patch = patch.object(release_script, "ROOT", self.root)
        root_patch.start()
        self.addCleanup(root_patch.stop)
        run_patch = patch.object(release_script, "run", side_effect=self.command_output)
        self.run = run_patch.start()
        self.addCleanup(run_patch.stop)
        output = redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        self.outputs = {
            ("git", "rev-parse", "--show-toplevel"): str(self.root) + "\n",
            ("git", "symbolic-ref", "--quiet", "--short", "HEAD"): "release-branch\n",
            ("git", "diff", "--cached", "--name-only"): "README.md\n",
            ("git", "rev-parse", "--verify", "HEAD"): "abc123\n",
            ("git", "var", "GIT_AUTHOR_IDENT"): "Author <author@example.com>\n",
            ("git", "var", "GIT_COMMITTER_IDENT"): "Committer <committer@example.com>\n",
        }
        self.failure = None

    def command_output(self, *command, **kwargs):
        if command == self.failure:
            raise subprocess.CalledProcessError(1, command)
        if command[:3] == ("git", "rev-parse", "--git-path"):
            return ".git/" + command[3] + "\n"
        return self.outputs.get(command, "")

    def build_command(self):
        command = ["docker", "build", "--file", "docker/Dockerfile"]
        for reference in self.REFERENCES:
            command.extend(("--tag", reference))
        return tuple(command + ["."])

    def atomic_push_command(self):
        return ("git", "push", "--atomic", "origin",
                "HEAD:refs/heads/release-branch", "refs/tags/" + self.TAG)

    def commands(self):
        return [invocation.args for invocation in self.run.call_args_list]

    def assert_no_git_mutations(self):
        for command in self.commands():
            if command[0] == "git":
                self.assertNotIn(command[1], ("add", "commit", "push"))
                self.assertNotEqual(command[:3], ("git", "tag", "--annotate"))

    def assert_no_docker_pushes(self):
        self.assertFalse(any(command[:2] == ("docker", "push")
                             for command in self.commands()))

    def test_release_builds_once_then_publishes_all_four_tags(self):
        release_script.release(self.TAG)
        commands = self.commands()
        build = self.build_command()
        self.assertEqual([command for command in commands
                          if command[:2] == ("docker", "build")], [build])
        self.assertIn(call(*build, timeout=900), self.run.call_args_list)
        mutations = [
            ("git", "add", "--all"),
            ("git", "commit", "-m", "chore(release): " + self.TAG),
            ("git", "tag", "--annotate", self.TAG, "--message", "Release " + self.TAG),
            self.atomic_push_command(),
        ]
        positions = [commands.index(build)] + [commands.index(command) for command in mutations]
        self.assertEqual(positions, sorted(positions))
        self.assertLess(commands.index(("sh", "scripts/test.sh")), commands.index(build))
        self.assertLess(commands.index(("docker", "compose", "config", "--quiet")),
                        commands.index(build))
        pushes = [call("docker", "push", reference, timeout=900)
                  for reference in self.REFERENCES]
        self.assertEqual([invocation for invocation in self.run.call_args_list
                          if invocation.args[:2] == ("docker", "push")], pushes)
        self.assertEqual(commands[commands.index(self.atomic_push_command()) + 1:],
                         [invocation.args for invocation in pushes])

    def test_tag_collisions_fail_before_build_or_git_mutation(self):
        for location, command, output in (
            ("locally", ("git", "tag", "--list", self.TAG), self.TAG + "\n"),
            ("on origin", ("git", "ls-remote", "--tags", "origin", "refs/tags/" + self.TAG),
             "abc123\trefs/tags/" + self.TAG + "\n"),
        ):
            with self.subTest(location=location):
                self.run.reset_mock()
                self.outputs[command] = output
                try:
                    with self.assertRaisesRegex(ValueError, location):
                        release_script.release(self.TAG)
                    self.assertEqual(self.commands()[-1], command)
                    self.assert_no_git_mutations()
                    self.assert_no_docker_pushes()
                    self.assertFalse(any(item[:2] == ("docker", "build")
                                         for item in self.commands()))
                    self.assertNotIn(("sh", "scripts/test.sh"), self.commands())
                finally:
                    del self.outputs[command]

    def test_build_failure_does_not_mutate_git(self):
        self.failure = self.build_command()
        with self.assertRaises(subprocess.CalledProcessError):
            release_script.release(self.TAG)
        self.assertEqual(self.commands()[-1], self.failure)
        self.assert_no_git_mutations()
        self.assert_no_docker_pushes()

    def test_no_staged_changes_skips_commit(self):
        self.outputs[("git", "diff", "--cached", "--name-only")] = ""
        release_script.release(self.TAG)
        commands = self.commands()
        self.assertIn(("git", "add", "--all"), commands)
        self.assertIn(("git", "rev-parse", "--verify", "HEAD"), commands)
        self.assertFalse(any(command[:2] == ("git", "commit") for command in commands))
        self.assertIn(("git", "tag", "--annotate", self.TAG,
                       "--message", "Release " + self.TAG), commands)
        self.assertIn(self.atomic_push_command(), commands)
        self.assertEqual([command for command in commands if command[:2] == ("docker", "push")],
                         [("docker", "push", reference) for reference in self.REFERENCES])

    def test_git_push_failure_prevents_docker_pushes(self):
        self.failure = self.atomic_push_command()
        with self.assertRaises(subprocess.CalledProcessError):
            release_script.release(self.TAG)
        self.assertEqual(self.commands()[-1], self.failure)
        self.assertIn(self.build_command(), self.commands())
        self.assert_no_docker_pushes()

    def test_main_invalid_tag_returns_one_without_commands(self):
        for tag in ("", "invalid/tag", "latest"):
            with self.subTest(tag=tag), patch.dict(os.environ, {"TAG": tag}), \
                    redirect_stderr(io.StringIO()) as errors:
                self.run.reset_mock()
                self.assertEqual(release_script.main(), 1)
                self.run.assert_not_called()
                self.assertIn("release:", errors.getvalue())
