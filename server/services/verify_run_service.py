from __future__ import annotations

import os
import sys
import json
import uuid
import time
import asyncio
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 获取工程根目录
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
HISTORY_FILE = PROJECT_ROOT / "output" / "verify_runs" / "history.json"
HISTORY_LOCK = asyncio.Lock()


def load_history() -> dict[str, Any]:
    if not HISTORY_FILE.exists():
        return {}
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_history(history: dict[str, Any]):
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


class VerifyRunService:
    def list_verify_runs(self, limit: int = 50, offset: int = 0) -> list[dict]:
        history = load_history()
        # 按开始时间逆序排列
        sorted_runs = sorted(
            history.values(),
            key=lambda x: x.get("started_at", ""),
            reverse=True
        )
        return sorted_runs[offset : offset + limit]

    def get_verify_run(self, run_id: str) -> dict | None:
        history = load_history()
        return history.get(run_id)

    def delete_verify_run(self, run_id: str) -> bool:
        history = load_history()
        if run_id in history:
            del history[run_id]
            save_history(history)
            return True
        return False

    async def start_verification(
        self,
        scripts: list[str],
        ab_config: list[str] | None = None,
        scenarios: list[str] | None = None,
        dry_run: bool = False,
        repeat: int = 1,
    ) -> dict:
        run_id = f"vrun_{uuid.uuid4().hex[:8]}"
        run_dir = PROJECT_ROOT / "output" / "verify_runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # 校验 script keys 是否合法
        valid_keys = {"mece_main", "log_replay", "short_model_matrix"}
        filtered_scripts = [s for s in scripts if s in valid_keys]
        if not filtered_scripts:
            filtered_scripts = ["mece_main"]  # 默认

        run_info = {
            "run_id": run_id,
            "status": "queued",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "completed_at": None,
            "duration_s": 0.0,
            "overall_verification_result": "fail",
            "scripts": {
                s: {
                    "status": "queued",
                    "scenarios_passed": 0,
                    "scenarios_failed": 0,
                    "log_file": str(run_dir / f"{s}.log"),
                }
                for s in filtered_scripts
            },
            "result_summary": "",
        }

        async with HISTORY_LOCK:
            history = load_history()
            history[run_id] = run_info
            save_history(history)

        # 异步启动任务
        asyncio.create_task(
            self._execute_runs_async(
                run_id=run_id,
                run_dir=run_dir,
                scripts=filtered_scripts,
                ab_config=ab_config,
                scenarios=scenarios,
                dry_run=dry_run,
                repeat=repeat,
            )
        )

        return run_info

    async def _execute_runs_async(
        self,
        run_id: str,
        run_dir: Path,
        scripts: list[str],
        ab_config: list[str] | None,
        scenarios: list[str] | None,
        dry_run: bool,
        repeat: int,
    ):
        start_time = time.time()
        logger.info("开始执行验证运行 task_id=%s", run_id)

        async with HISTORY_LOCK:
            history = load_history()
            if run_id in history:
                history[run_id]["status"] = "running"
                save_history(history)

        all_success = True
        accumulated_summary = [f"# 验证任务 {run_id} 汇总报告\n"]

        for script_key in scripts:
            async with HISTORY_LOCK:
                history = load_history()
                if run_id in history:
                    history[run_id]["scripts"][script_key]["status"] = "running"
                    save_history(history)

            script_path = ""
            cmd_args = []
            output_subdir = run_dir / script_key

            if script_key == "mece_main":
                script_path = "scripts/verify_mode_switching.py"
                cmd_args = ["--output-dir", str(output_subdir)]
                if ab_config:
                    cmd_args.extend(["--ab"] + ab_config)
                if scenarios:
                    cmd_args.extend(["--scenarios"] + scenarios)
                if dry_run:
                    cmd_args.append("--dry-run")
                if repeat > 1:
                    cmd_args.extend(["--repeat", str(repeat)])

            elif script_key == "log_replay":
                script_path = "scripts/verify_mode_switching_log_replay.py"
                cmd_args = ["--output-dir", str(output_subdir)]
                if ab_config:
                    cmd_args.extend(["--ab"] + ab_config)
                if scenarios:
                    cmd_args.extend(["--scenarios"] + scenarios)
                if dry_run:
                    cmd_args.append("--dry-run")

            elif script_key == "short_model_matrix":
                script_path = "scripts/verify_mode_switching_short_model_matrix.py"
                cmd_args = ["--output-dir", str(output_subdir)]
                if scenarios:
                    cmd_args.extend(["--scenarios"] + scenarios)
                if dry_run:
                    cmd_args.append("--dry-run")

            log_file_path = run_dir / f"{script_key}.log"
            try:
                # 运行子进程
                cmd = [sys.executable, str(PROJECT_ROOT / script_path)] + cmd_args
                logger.info("运行命令: %s", " ".join(cmd))
                with log_file_path.open("w", encoding="utf-8") as log_f:
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=log_f,
                        stderr=log_f,
                        cwd=str(PROJECT_ROOT),
                    )
                    await process.wait()
                    exit_code = process.returncode

                # 分析结果
                passed, failed = self._analyze_script_results(script_key, output_subdir)
                status = "completed" if exit_code == 0 else "failed"
                if exit_code != 0:
                    all_success = False

                # 读取生成的报告
                report_md = f"## {script_key} 执行结果\n退出码: {exit_code}\n\n"
                summary_files = list(output_subdir.glob("summary.md")) + list(output_subdir.glob("switching_report_*.md"))
                if summary_files:
                    try:
                        report_md += summary_files[0].read_text(encoding="utf-8")
                    except Exception as e:
                        report_md += f"读取报告出错: {e}\n"
                else:
                    report_md += "未找到生成的 markdown 报告。\n"

                accumulated_summary.append(report_md)

                async with HISTORY_LOCK:
                    history = load_history()
                    if run_id in history:
                        history[run_id]["scripts"][script_key].update({
                            "status": status,
                            "scenarios_passed": passed,
                            "scenarios_failed": failed,
                        })
                        save_history(history)

            except Exception as e:
                logger.exception("执行脚本 %s 出错: %s", script_key, e)
                all_success = False
                async with HISTORY_LOCK:
                    history = load_history()
                    if run_id in history:
                        history[run_id]["scripts"][script_key].update({
                            "status": "failed",
                            "scenarios_passed": 0,
                            "scenarios_failed": 1,
                        })
                        save_history(history)

        duration = round(time.time() - start_time, 2)
        overall_result = "pass" if all_success else "fail"

        async with HISTORY_LOCK:
            history = load_history()
            if run_id in history:
                history[run_id].update({
                    "status": "completed" if all_success else "failed",
                    "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "duration_s": duration,
                    "overall_verification_result": overall_result,
                    "result_summary": "\n\n".join(accumulated_summary),
                })
                save_history(history)

        logger.info("验证运行完成 task_id=%s, result=%s", run_id, overall_result)

    def _analyze_script_results(self, script_key: str, output_subdir: Path) -> tuple[int, int]:
        passed = 0
        failed = 0
        try:
            if script_key == "mece_main":
                # 寻找 switching_results_*.json
                json_files = list(output_subdir.glob("switching_results_*.json"))
                if json_files:
                    data = json.loads(json_files[0].read_text(encoding="utf-8"))
                    for scenario in data:
                        turns = scenario.get("turns", [])
                        has_leakage = any(len(t.get("leakage", [])) > 0 for t in turns)
                        if not has_leakage:
                            passed += 1
                        else:
                            failed += 1
                else:
                    failed = 1
            elif script_key in {"log_replay", "short_model_matrix"}:
                results_file = output_subdir / "results.jsonl"
                if results_file.exists():
                    with results_file.open("r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            record = json.loads(line)
                            if script_key == "log_replay":
                                success = record.get("success", False)
                                issues = record.get("metrics", {}).get("format_issues", [])
                                if success and not issues:
                                    passed += 1
                                else:
                                    failed += 1
                            else:
                                # short_model_matrix
                                success = record.get("summary_success", False) and record.get("points_success", True)
                                json_ok = record.get("summary_json_ok", True)
                                if success and json_ok:
                                    passed += 1
                                else:
                                    failed += 1
                else:
                    failed = 1
        except Exception as e:
            logger.error("分析脚本结果错误 %s: %s", script_key, e)
            failed = 1
        return passed, failed
