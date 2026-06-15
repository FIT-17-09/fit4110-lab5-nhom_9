IMAGE_NAME ?= fit4110/notification-service:lab05
CONTAINER_NAME ?= fit4110-notify-lab05
PORT ?= 8000

install:
	npm install

lint:
	npm run lint:openapi

mock:
	npm run mock:notify

test-mock:
	npm run test:mock

build:
	docker build -t $(IMAGE_NAME) .

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

logs:
	docker compose logs -f

test-compose:
	npm run test:local

health:
	curl http://localhost:$(PORT)/health

stop:
	docker compose down || true

clean-reports:
	rm -f reports/*.xml reports/*.html reports/*.json
