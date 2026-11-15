# This Makefile is a proxy for the Justfile: `make <target>` runs `just <target>`.

.PHONY: default
default:
	@just --list

.PHONY: %
%:
	@just $@
