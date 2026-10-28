.PHONY: install test demo lint
install:
	pip install -e ".[dev]"
test:
	python -m pytest --cov=decision_guide --cov-report=term-missing
demo:
	decision-guide recommend --category monitor --budget 400 --priority eye-comfort --must usb-c
	decision-guide compare mon-02 mon-03
	decision-guide chat --category chair --budget 350 --priority ergonomics --script data/demo_script.txt
