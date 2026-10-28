from core import advisor


def test_topics_detect_selling_marketing_and_planning():
    prompt = ("entro fine mese vorrei chiudere il progetto whitesoul, portarlo su Aruba e fare un pacchetto "
              "manutenzione più gestione Instagram con una fee mensile")
    assert advisor.topics(prompt) == ["vendita", "marketing", "pianificazione"]
    assert advisor.topics("per hosting e configurazione quanto posso chiedere?") == ["vendita"]
    assert advisor.topics("che ore sono?") == []
    assert advisor.guidance("che tempo fa domani") == ""


def test_guidance_adapts_to_voice():
    text = advisor.guidance("quanto posso chiedere al cliente?", voice=True)
    assert "tre pacchetti" in text and "A voce" in text
    assert "Marketing" not in text
