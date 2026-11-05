from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "streamlit_app.py")


def test_app_renders_and_answers():
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception
    at.chat_input[0].set_value("What is the TVPI of Meridian Partners II?").run()
    assert not at.exception
    assert any("tvpi" in m.value.lower() for m in at.chat_message[1].markdown)
