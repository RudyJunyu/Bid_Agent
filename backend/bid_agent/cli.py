# 这个脚本是运行 Plan-and-Solve 智能体的命令行入口。
import argparse
import sys

from bid_agent.infrastructure.llm_client import LLM_Invoke
from bid_agent.agents.plan_and_solve import PlanAndSolveAgent


DEFAULT_QUESTION = (
    "我要对智能机器人的企业进行搜索匹配，可以从企业基本信息、经营信息、企业名称等字段进行匹配，"
    "请返回给我可以用于匹配的字段的关键词，例如企业名称——人形机器人，并以json格式返回。"
)


def read_question(args_question: str | None) -> str:
    if args_question:
        return args_question.strip()

    print("请输入你的问题，回车将使用下面的默认提示词：")
    print(DEFAULT_QUESTION)
    question = input("> ").strip()
    return question or DEFAULT_QUESTION


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Plan-and-Solve Agent")
    parser.add_argument("question", nargs="?", help="要让模型处理的问题；不传则进入输入模式")
    parser.add_argument("--model", default=None, help="可选：临时覆盖 .env 中的 LLM_MODEL_ID")
    args = parser.parse_args()

    question = read_question(args.question)
    llm_client = LLM_Invoke(model=args.model)
    agent = PlanAndSolveAgent(llm_client)
    agent.run(question)


if __name__ == "__main__":
    main()
