.PHONY: test ui demo

test:
	PYTHONPATH=src pytest

ui:
	streamlit run app.py

demo:
	PYTHONPATH=src python scripts/export_demo.py
