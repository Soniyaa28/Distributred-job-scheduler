.PHONY: up down test migrate logs
up:
	docker compose up --build
down:
	docker compose down
test:
	docker compose run --rm api pytest -q
migrate:
	docker compose run --rm api alembic upgrade head
logs:
	docker compose logs -f api
