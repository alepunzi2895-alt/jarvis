import threading

from core import progress


def test_report_without_reporter_is_noop_and_reporter_reaches_threads():
    progress.report("niente", 10)
    seen = []
    token = progress.bind(lambda label, percent: seen.append((label, percent)))
    try:
        reporter = progress.current()
        threading.Thread(target=lambda: reporter("thread", 150)).start()
        progress.report("diretto", -5)
    finally:
        progress.reset(token)
    progress.report("dopo", 1)
    assert ("diretto", 0) in seen and ("thread", 150) in seen and ("dopo", 1) not in seen


def test_acks_and_tool_percent():
    assert "mail e calendario" in progress.ack_for("Jarvis, buongiorno")
    assert progress.ack_for("quante mail non lette?") == "Controllo la posta, un momento."
    assert progress.ack_for("raccontami una barzelletta") == progress.GENERIC_ACK
    values = [progress.tool_percent(step) for step in range(1, 12)]
    assert values == sorted(values) and values[0] > 15 and values[-1] <= 90
    assert progress.tool_label("list_emails") == "controllo la posta"
