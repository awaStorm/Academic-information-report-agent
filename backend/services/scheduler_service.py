"""
backend/services/scheduler_service.py - 调度器服务
管理定时任务的启动、停止、状态查询
"""
import sys
from pathlib import Path
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.utils.config_loader import CONFIG
from src.agent.analyzer import run_analysis_flow
from src.agent.pusher import Pusher
from src.agent.database import AgentMemory
from datetime import datetime

logger = logging.getLogger("backend.scheduler")


class SchedulerService:
    """定时任务调度器服务"""

    def __init__(self):
        self.scheduler = None
        self.is_running = False
        self.last_run_time = None
        self.last_run_result = None
        self.failure_count = 0

    def start(self):
        """启动调度器"""
        self.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self._apply_schedule()
        self.scheduler.start()
        self.is_running = True
        logger.info("✅ 调度器已启动")

    def stop(self):
        """停止调度器"""
        if self.scheduler and self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            logger.info("🛑 调度器已停止")

    def _apply_schedule(self):
        """根据配置应用定时任务"""
        self.scheduler.remove_all_jobs()
        scheduler_config = CONFIG.get("scheduler", {})
        if not scheduler_config.get("enabled", False):
            logger.info("定时任务未启用")
            return
        run_times = scheduler_config.get("run_times", ["08:00"])
        for time_str in run_times:
            try:
                hour, minute = map(int, time_str.strip().split(":"))
                job_id = f"daily_report_{time_str.replace(':', '')}"
                self.scheduler.add_job(
                    self._run_task,
                    CronTrigger(hour=hour, minute=minute),
                    id=job_id,
                    replace_existing=True,
                )
                logger.info(f"✅ 已添加定时任务: 每天 {hour:02d}:{minute:02d}")
            except Exception as e:
                logger.error(f"添加定时任务失败 {time_str}: {e}")

    def _run_task(self):
        """执行定时任务"""
        logger.info(f"⏰ 定时任务开始执行 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.last_run_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            result = run_analysis_flow()
            success = result.get("success", False) if isinstance(result, dict) else bool(result)
            if success:
                self.failure_count = 0
                self.last_run_result = "成功"
            else:
                self.failure_count += 1
                self.last_run_result = "失败"
            # 保存日志
            self._save_log(success, result)
            logger.info(f"✅ 定时任务执行完成: {self.last_run_result}")
        except Exception as e:
            self.failure_count += 1
            self.last_run_result = f"异常: {str(e)[:50]}"
            self._save_log(False, {"message": str(e)})
            logger.error(f"❌ 定时任务执行异常: {e}")

    def _save_log(self, success: bool, result: dict):
        """保存执行日志到数据库"""
        try:
            memory = AgentMemory()
            memory.save_pushed_record(
                title=f"定时任务 - {'成功' if success else '失败'}",
                platform="system",
                category="系统日志",
                brief=f"{result.get('message', '')} | 推送: {result.get('pushed', 0)} 条",
                link="",
                status="log",
            )
            memory.close()
        except Exception as e:
            logger.warning(f"保存日志失败: {e}")

    def get_status(self):
        """获取调度器状态"""
        jobs = self.scheduler.get_jobs() if self.scheduler else []
        return {
            "enabled": CONFIG.get("scheduler", {}).get("enabled", False),
            "running": self.is_running,
            "jobs": [j.id for j in jobs],
            "last_run_time": self.last_run_time,
            "last_run_result": self.last_run_result,
            "failure_count": self.failure_count,
        }

    def update_schedule(self):
        """更新调度配置（配置变更后调用）"""
        if self.scheduler:
            self._apply_schedule()
