import asyncio

from core.browser import BrowserAgent


def test_open_refuses_localhost_without_touching_playwright():
    agent = BrowserAgent()
    result = asyncio.run(agent.open("http://localhost:3000/"))
    assert "non apro" in result.lower()
    assert agent._context is None  # mai avviato Playwright per un indirizzo locale


def test_open_refuses_127_0_0_1():
    agent = BrowserAgent()
    result = asyncio.run(agent.open("http://127.0.0.1:8080/"))
    assert "non apro" in result.lower()


def test_open_refuses_localhost_regardless_of_port_or_path():
    agent = BrowserAgent()
    result = asyncio.run(agent.open("http://localhost/second-brain"))
    assert "non apro" in result.lower()
