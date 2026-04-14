#  main.py
#  Routes terminal commands to the right backend functions

import argparse
from src.function_manager import sync_to_repo
from src.repo_summary import summarize_repo
from src.config import GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH

def main():
    parser = argparse.ArgumentParser(description="Agentic CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- PLAN (NEW — review before execute) ---
    plan_parser = subparsers.add_parser("plan",
        help="Create a risk-assessed plan, review it, then execute")
    plan_parser.add_argument("goal", help="Natural language goal")
    plan_parser.add_argument("--execute", "-x", action="store_true",
        help="Execute the plan after showing it")
    plan_parser.add_argument("--auto", "-y", action="store_true",
        help="Skip confirmation prompt")
    plan_parser.add_argument("--quiet", "-q", action="store_true",
        help="Less verbose output")
    plan_parser.add_argument("--refine", type=str, default=None,
        help="Feedback to refine an existing plan (requires --load)")
    plan_parser.add_argument("--load", type=str, default=None,
        help="Load a previously saved plan JSON")

    # --- RUN (existing — plan + execute in one shot) ---
    run_parser = subparsers.add_parser("run",
        help="Plan and execute in one shot (no review step)")
    run_parser.add_argument("prompt", help="Natural language request")
    run_parser.add_argument("--quiet", "-q", action="store_true")
    run_parser.add_argument("--auto", "-y", action="store_true")

    # --- SUMMARIZE ---
    p_sum = subparsers.add_parser("summarize",
        help="Generate Gemini summaries and push to README")
    p_sum.add_argument("--output", help="Also save locally to this path")
    p_sum.add_argument("--force", "-f", action="store_true")

    # --- LANGCHAIN ---
    lc = subparsers.add_parser("langchain",
        help="LangChain agent mode (interactive or single-shot)")
    lc.add_argument("prompt", nargs='?', help="Natural language request")
    lc.add_argument("--chat", action="store_true")
    lc.add_argument("--stats", action="store_true")
    lc.add_argument("--temperature", type=float, default=0.7)

    # --- REVIEW ---
    rev = subparsers.add_parser("review", help="Review code quality")
    rev.add_argument("file_path", help="File to review")

    # --- SYNC ---
    subparsers.add_parser("sync", help="Sync generated/ to GitHub")

    args = parser.parse_args()

    # ==================================================================

    if args.command == "sync":
        sync_to_repo()

    elif args.command == "summarize":
        res = summarize_repo(
            owner=GITHUB_OWNER, repo=GITHUB_REPO, branch=GITHUB_BRANCH,
            output_path=getattr(args, 'output', None),
            force_full=getattr(args, 'force', False),
        )
        print(f"Summaries pushed to: {res}")

    elif args.command == "run":
        from src.multi_file_agent import multi_file_execute
        result = multi_file_execute(
            args.prompt,
            verbose=not args.quiet,
            auto_approve=getattr(args, 'auto', False),
        )
        print(f"\n{result}")

    # ------------------------------------------------------------------
    # PLAN (new)
    # ------------------------------------------------------------------
    elif args.command == "plan":
        from src.langchain_agent.planning_agent import (
            plan_cli, load_plan, assess_plan_risk, refine_plan,
            print_plan, save_plan,
        )
        from src.multi_file_agent import MultiFileAgentV2

        if args.load:
            plan = load_plan(args.load)
            plan = assess_plan_risk(plan)

            if args.refine:
                plan = refine_plan(plan, args.refine)

            print_plan(plan)

            if args.execute:
                total = len(plan.get("files_to_create", [])) + len(plan.get("files_to_edit", []))
                if not getattr(args, 'auto', False):
                    try:
                        resp = input(f"Execute {total} operations? [y/N]: ").strip()
                        if resp.lower() not in ('y', 'yes'):
                            print("Cancelled."); return
                    except (EOFError, KeyboardInterrupt):
                        print("Cancelled."); return

                try:
                    from src.agent_os.version_control import VersionControl
                    use_vc = True
                except ImportError:
                    use_vc = False
                agent = MultiFileAgentV2(use_version_control=use_vc)
                results = agent.execute_plan(plan, verbose=not args.quiet)
                save_plan(plan, args.load)
                created = len([r for r in results.get("created", [])
                               if hasattr(r, "success") and r.success])
                edited = len([r for r in results.get("edited", [])
                              if hasattr(r, "success") and r.success])
                print(f"\nDone. Created {created}, edited {edited} file(s).")
            else:
                save_plan(plan)
                print("Plan loaded. Add --execute to run it.")
        else:
            result = plan_cli(
                goal=args.goal,
                execute=args.execute,
                auto_approve=getattr(args, 'auto', False),
                verbose=not getattr(args, 'quiet', False),
            )
            print(f"\n{result}")

    # ------------------------------------------------------------------
    # REVIEW
    # ------------------------------------------------------------------
    elif args.command == "review":
        from src.langchain_agent.code_review_agent import CodeReviewAgentV2

        file_path = args.file_path
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code_content = f.read()
        except FileNotFoundError:
            from src.github_manager import get_file
            code_content, _ = get_file(file_path, GITHUB_OWNER, GITHUB_REPO, GITHUB_BRANCH)
            if not code_content:
                print(f"File not found: {file_path}"); return

        agent = CodeReviewAgentV2()
        agent.review_code(file_path, code_content)
        print(agent.generate_report())

    # ------------------------------------------------------------------
    # LANGCHAIN
    # ------------------------------------------------------------------
    elif args.command == "langchain":
        print("\nInitializing LangChain Agent...\n")

        from src.langchain_agent.langchain_agent_simplified import create_simplified_agent
        try:
            from src.langchain_agent.planning_agent import register_planning_tools
            register_planning_tools()
        except Exception:
            pass

        agent = create_simplified_agent(temperature=args.temperature)

        if args.chat:
            print("Chat Mode  (type 'exit' to quit, 'tools' to list tools)")
            print("="*60)
            while True:
                try:
                    user_input = input("\nYou: ").strip()
                    if user_input.lower() in ('exit', 'quit', 'q'):
                        break
                    if user_input.lower() == 'tools':
                        for t in agent.tools:
                            print(f"  {t.name}: {t.description}")
                        continue
                    if not user_input:
                        continue
                    print(f"\nAgent:\n{agent.execute(user_input)}")
                except (KeyboardInterrupt, EOFError):
                    break
            print("\nGoodbye!")
        else:
            if not args.prompt:
                print("Error: prompt required (or use --chat)")
                return
            response = agent.execute(args.prompt)
            print(f"\n{response}")

        if args.stats:
            for k, v in agent.get_stats().items():
                print(f"  {k}: {v}")

    else:
        parser.print_help()

if __name__ == "__main__":
    main()