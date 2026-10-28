import io
import json

from decision_guide.cli import EXIT_DATA, EXIT_OK, EXIT_PROVIDER, EXIT_USAGE, main


def run(*argv):
    out = io.StringIO()
    code = main(list(argv), out=out)
    return code, out.getvalue()


def test_validate():
    code, text = run("validate")
    assert code == EXIT_OK and "ok:" in text


def test_validate_bad_path():
    code, text = run("--catalog", "/nonexistent.json", "validate")
    assert code == EXIT_DATA and "not found" in text


def test_recommend_text():
    code, text = run("recommend", "--category", "chair", "--budget", "350", "--priority", "ergonomics")
    assert code == EXIT_OK and "#1 Halden ErgoFlex 2" in text and "Excluded chairs" in text


def test_recommend_json():
    code, text = run("recommend", "--category", "monitor", "--budget", "400", "--priority", "eye-comfort", "--must", "usb-c", "--json")
    data = json.loads(text)
    assert code == EXIT_OK and data["ranked"][0]["id"] == "mon-02"


def test_recommend_empty_state():
    code, text = run("recommend", "--category", "chair", "--budget", "20")
    assert code == EXIT_OK and "No items fit" in text


def test_recommend_unknown_category_and_priority():
    code, text = run("recommend", "--category", "yacht", "--priority", "speed")
    assert code == EXIT_USAGE and "unknown category" in text and "unknown priority" in text


def test_compare_unknown_id():
    code, text = run("compare", "mon-02", "zzz-00")
    assert code == EXIT_USAGE


def test_chat_script(tmp_path, monkeypatch):
    monkeypatch.setenv("DECISION_GUIDE_LLM_PROVIDER", "simulated")
    script = tmp_path / "q.txt"
    script.write_text("why not chr-03\nwhat is the moon\n")
    code, text = run("chat", "--category", "chair", "--budget", "350", "--script", str(script))
    assert code == EXIT_OK and "[why-not]" in text and "[out-of-scope]" in text


def test_chat_bad_provider(monkeypatch):
    monkeypatch.setenv("DECISION_GUIDE_LLM_PROVIDER", "oracle")
    code, text = run("chat", "--category", "chair")
    assert code == EXIT_PROVIDER and "unknown provider" in text
