"""Minimal demonstration of the LangGraph agent."""

from agent_core.flows import run_agent

if __name__ == "__main__":
    question = "请读取 README.md 的前 20 行，并解释这个文件的主要内容"
    reply = run_agent(question)
    print("User:", question)
    print("Agent:", reply)
