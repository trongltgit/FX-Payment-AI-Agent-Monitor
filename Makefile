.PHONY: install test train backtest docs run docker
install:
	pip install -r requirements.txt -r requirements-dev.txt
test:
	python -m pytest tests -q
train:
	python -m agentmon.train_cli
backtest:
	python -m agentmon.backtest --synthetic --domain PAY && python -m agentmon.backtest --synthetic --domain FX
docs:
	python -m tools.gen_docs
run:
	python app.py
docker:
	docker compose up --build
