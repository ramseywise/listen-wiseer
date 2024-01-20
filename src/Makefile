lint:
	black --check --diff --color ./listen-wiseer ./tests
	mypy ./listen-wiseer --strict --implicit-reexport
	mypy ./tests
	ruff check ./listen-wiseer ./tests

format:
	black ./listen-wiseer ./tests
	ruff check ./listen-wiseer ./tests --fix

test:
	pytest --log-cli-level=info --cov=./listen-wiseer --cov-fail-under=90 --cov-report term-missing ./tests

test-unit:
	pytest -m unit --log-cli-level=info --cov=./listen-wiseer --cov-report term-missing ./tests/unit

make app-run:
	uvicorn app --host 0.0.0.0 --port 8080 --log-config=uvicorn-logger.yml
