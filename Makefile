COMPOSE_INFRA=docker-compose -f docker-compose.yml

infra-up:
	${COMPOSE_INFRA} up -d

infra-logs:
	${COMPOSE_INFRA_DEV} logs -f

infra-down:
	${COMPOSE_INFRA_DEV} down --volumes --remove-orphans

lint:
	black .
	mypy .
	ruff check .