# 这个脚本负责调用 SerpApi 在 Google 上搜索资料。
''' SerpApi Search Tool '''

# 作用：调用 SerpApi 这个第三方搜索服务，帮我们在 Google 上搜索内容
from serpapi import Client
from bid_agent.core import settings  # Load the project environment once.

# 导入 os 模块（读取环境变量）
import os
import re


# 定义一个搜索函数，名字叫做 search
# 输入：query = 你要搜索的问题（比如“Python 是什么”）
# 输出：返回一段文字，就是搜索到的结果

def search(query: str) -> str:
    query = query.strip()
    print(f"正在使用 SerpApi 搜索: {query}")

    try:
        # 从 .env 文件中读取 SerpApi 的 API 密钥
        # 如果没有这个密钥，就不能调用搜索服务
        api_key = os.getenv("SERPAPI_API_KEY")
        if not api_key:
            raise ValueError("SERPAPI_API_KEY 环境变量未设置，请在 .env 文件中定义它。")
        
        # 构造搜索参数（告诉Google要怎么搜）
        params = {
            "engine": "google",  # 使用 Google 搜索引擎
            "q": query,          # 搜索的内容
            "gl": "cn",          # 搜索区域（中国）
            "hl": "zh-cn",       # 搜索语言（简体中文）
        }

        # 创建搜索客户端，把参数传进去
        client = Client(api_key=api_key)

        # 发起搜索，拿到结果（字典形式）
        results = client.search(params)

        # ===================== 智能解析结果 =====================
        # 优先级：直接答案 > 知识图谱 > 普通搜索结果

        # 1. 优先看有没有【答案列表】（Google 直接给的标准答案）
        if "answer_box_list" in results:
            return "\n".join(results["answer_box_list"])
        
        # 2. 看有没有【单个答案框】（最精准的直接回答）
        if "answer_box" in results and "answer" in results["answer_box"]:
            return results["answer_box"]["answer"]
        
        # 3. 看有没有【知识图谱】（Google 侧边栏的总结信息）
        if "knowledge_graph" in results and "description" in results["knowledge_graph"]:
            return results["knowledge_graph"]["description"]
        
        # 4. 如果上面都没有，返回【前 3 条普通搜索结果】
        if "organic_results" in results and results["organic_results"]:
            # 只取前 3 条，拼接标题 + 摘要
            snippets = [
                f"[{i+1}]{res.get('title','')}\n{res.get('snippet','')}"
                for i, res in enumerate(results["organic_results"][:3])
            ]
            # 用空行分开，返回给LLM
            return "\n\n".join(snippets)
        
        # 5. 啥都没搜到，兜底策略
        return f" 对不起，没有找到关于 '{query}' 的相关信息。"
    
    # 如果搜索过程中出错（网络问题、密钥错误等）
    except Exception as e:
        error_message = re.sub(r"api_key=[^&\s]+", "api_key=***", str(e))
        return f"搜索时发生错误: {error_message}"
