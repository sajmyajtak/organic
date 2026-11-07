import os

from igbot.config import load_dotenv


def test_load_dotenv_parses_values_and_keeps_existing_env(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "IGBOT_T_PLAIN=abc\n"
        "IGBOT_T_COMMENT=key123              # volitelné\n"
        "IGBOT_T_EMPTY=              # nic\n"
        "IGBOT_T_QUOTED=\"a # not a comment\"\n"
        "export IGBOT_T_EXPORT=yes\n"
        "IGBOT_T_SET=from-file\n",
        encoding="utf-8",
    )
    for key in ("PLAIN", "COMMENT", "EMPTY", "QUOTED", "EXPORT"):
        monkeypatch.delenv(f"IGBOT_T_{key}", raising=False)
    monkeypatch.setenv("IGBOT_T_SET", "from-env")

    load_dotenv(env_file)

    assert os.environ["IGBOT_T_PLAIN"] == "abc"
    assert os.environ["IGBOT_T_COMMENT"] == "key123"
    assert "IGBOT_T_EMPTY" not in os.environ
    assert os.environ["IGBOT_T_QUOTED"] == "a # not a comment"
    assert os.environ["IGBOT_T_EXPORT"] == "yes"
    assert os.environ["IGBOT_T_SET"] == "from-env"
    for key in ("PLAIN", "COMMENT", "QUOTED", "EXPORT"):
        monkeypatch.delenv(f"IGBOT_T_{key}")


def test_load_dotenv_without_file_is_a_no_op(tmp_path):
    load_dotenv(tmp_path / "missing.env")
