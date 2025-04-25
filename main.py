import argparse
import asyncio

from app.agent.manus import Manus
from app.logger import logger


async def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="Manus Agent CLI")
    parser.add_argument(
        "--disable-evaluation", action="store_true", help="禁用自我评估功能"
    )
    parser.add_argument(
        "--disable-improvement", action="store_true", help="禁用自动改进功能"
    )
    parser.add_argument(
        "--max-iterations", type=int, default=1, help="最大自动改进迭代次数"
    )
    args = parser.parse_args()

    # 创建agent实例，设置参数
    agent = Manus(
        use_self_evaluation=not args.disable_evaluation,
        enable_auto_improvement=not args.disable_improvement,
        max_improvement_iterations=args.max_iterations,
    )

    try:
        prompt = input("请输入你的指令: ")
        if not prompt.strip():
            logger.warning("提供的指令为空。")
            return

        logger.info("正在处理你的请求...")
        await agent.run(prompt)
        logger.info("请求处理完成。")
    except KeyboardInterrupt:
        logger.warning("操作被中断。")
    except Exception as e:
        logger.error(f"发生错误: {e}")
    finally:
        # 确保agent资源在退出前被清理
        await agent.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
