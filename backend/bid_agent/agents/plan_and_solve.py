# 这个脚本实现 Plan-and-Solve 智能体的规划和执行流程。
import ast
import re
from typing import List


PLANNER_PROMPT_TEMPLATE = """
你是一个严谨的 AI 规划专家。请把用户问题拆成清晰、可执行、按顺序排列的步骤。

要求：
1. 只输出一个 Python list，每个元素是一条步骤说明。
2. 必须放在 ```python 和 ``` 代码块里。
3. 不要输出多余解释。

用户问题：
{question}

输出格式示例：
```python
["理解问题", "拆解关键点", "逐步求解", "汇总最终答案"]
```
"""


EXECUTOR_PROMPT_TEMPLATE = """
你是一个严谨的 AI 执行专家。请根据原始问题、完整计划、历史执行结果，完成当前步骤。

原始问题：
{question}

完整计划：
{plan}

历史步骤与结果：
{history}

当前步骤：
{current_step}

请只输出当前步骤的执行结果。
"""


class Planner:
    def __init__(self, llm_client):
        self.llm_client = llm_client

    def plan(self, question: str) -> List[str]:
        prompt = PLANNER_PROMPT_TEMPLATE.format(question=question)
        print("\n========== 1. 生成计划 ==========")
        response_text = self.llm_client.think([{"role": "user", "content": prompt}]) or ""

        plan = self._parse_plan(response_text)
        print("\n[解析后的计划]")
        for index, step in enumerate(plan, start=1):
            print(f"{index}. {step}")
        return plan

    @staticmethod
    def _parse_plan(response_text: str) -> List[str]:
        match = re.search(r"```python\s*(.*?)\s*```", response_text, re.DOTALL)
        plan_text = match.group(1).strip() if match else response_text.strip()
        plan = ast.literal_eval(plan_text)
        if not isinstance(plan, list) or not all(isinstance(step, str) for step in plan):
            raise ValueError("模型返回的计划不是字符串列表。")
        return plan


class Executor:
    def __init__(self, llm_client):
        self.llm_client = llm_client

    def execute(self, question: str, plan: List[str]) -> str:
        print("\n========== 2. 执行计划 ==========")
        history = ""
        final_answer = ""

        for index, step in enumerate(plan, start=1):
            print(f"\n----- Step {index}/{len(plan)} -----")
            print(f"[当前步骤] {step}")

            prompt = EXECUTOR_PROMPT_TEMPLATE.format(
                question=question,
                plan=plan,
                history=history if history else "暂无",
                current_step=step,
            )
            result = self.llm_client.think([{"role": "user", "content": prompt}]) or ""
            history += f"Step {index}: {step}\nResult: {result}\n\n"
            final_answer = result

            print(f"\n[步骤结果] {result}")

        return final_answer


class PlanAndSolveAgent:
    def __init__(self, llm_client):
        self.planner = Planner(llm_client)
        self.executor = Executor(llm_client)

    def run(self, question: str) -> str:
        print("\n========== Plan-and-Solve Agent ==========")
        print(f"[用户问题] {question}")

        plan = self.planner.plan(question)
        final_answer = self.executor.execute(question, plan)

        print("\n========== 3. 最终结果 ==========")
        print(final_answer)
        return final_answer
