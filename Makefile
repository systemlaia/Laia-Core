PYTHON=python3
CC=cc
CFLAGS=-std=c99 -Wall -Wextra -pedantic
LDFLAGS=-lm
C_TEST_BIN=c_core/test_stardate_core
UFBT_PY=.venv-flipper/bin/python
FLIPPER_APP_DIR=flipper_staging/laia_stardate

.PHONY: py-test c-test test example clean flipper-build flipper-clean full-test

py-test:
	$(PYTHON) -m py_compile stardate.py
	$(PYTHON) -m unittest test_stardate.py test_cli_ingest.py test_librarian_index.py test_librarian_route.py test_librarian_summarize.py test_librarian_classify.py test_librarian_review.py test_librarian_approve.py test_librarian_finalize.py test_librarian_catalog.py test_librarian_dedupe.py test_librarian_failures.py test_librarian_pending.py test_librarian_extract.py test_librarian_export.py test_librarian_extract_report.py test_librarian_correct_extract.py test_librarian_inspect_extract.py test_librarian_correct_classification.py test_grocy.py test_workflow_scan_document.py

c-test:
	$(CC) $(CFLAGS) c_core/stardate_core.c c_core/test_stardate_core.c -o $(C_TEST_BIN) $(LDFLAGS)
	./$(C_TEST_BIN)

test: py-test c-test

flipper-build:
	cd $(FLIPPER_APP_DIR) && ../../$(UFBT_PY) -m ufbt

flipper-clean:
	rm -rf $(FLIPPER_APP_DIR)/dist
	rm -f $(FLIPPER_APP_DIR)/.vscode/compile_commands.json

full-test: test flipper-build

example:
	$(PYTHON) stardate.py --date "2026-06-07 21:14" --color Yellow --tag Idea
	$(PYTHON) stardate.py --date "2026-06-07 21:14" --no-offset

clean:
	rm -f $(C_TEST_BIN)
	rm -rf __pycache__ .pytest_cache c_core/__pycache__ tests/__pycache__
