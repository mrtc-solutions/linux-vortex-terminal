.PHONY: test lint preview

test:
	python3 -m unittest discover -s tests -v

lint:
	python3 -m compileall -q backend cli

audit:
	@echo "Run cargo-audit/cargo-deny only if a future Rust auxiliary is introduced."

preview:
	python3 backend/vortex_backend.py --host 0.0.0.0 --port 4173
