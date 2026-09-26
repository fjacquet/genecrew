.PHONY: install security vuln

install:
	uv sync --all-extras --all-groups

security:  # advisory: reports findings but never blocks the build (CodeQL/osv are the blocking gates)
	uvx semgrep scan --config auto --skip-unknown-extensions || true

vuln:
	uvx osv-scanner scan --lockfile=uv.lock || true
