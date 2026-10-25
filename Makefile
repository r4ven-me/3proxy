.DEFAULT_GOAL := help
.PHONY: help test release

# Pass TAG as an environment value, never interpolate it into a shell command.
export TAG

help:
	@printf '%s\n' 'make test                 Run unit tests' 'make release TAG=v1.0.0   Build, commit, push Git and publish both registry images'

test:
	sh scripts/test.sh

release:
	python3 scripts/release.py
