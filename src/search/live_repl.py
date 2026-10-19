"""Adapter gọi Lean thật qua LeanInteract (Lean REPL) — thay LeanDojo, không cần trace mathlib.

Mỗi worker giữ 1 LeanServer: import header (vd `import Mathlib`) 1 lần thành env, rồi mở từng
định lý bằng `<statement> sorry` để lấy proof state gốc. Server được khởi động lại sau
`restart_every` định lý vì REPL giữ mọi proof state trong RAM.
"""
from __future__ import annotations

import shutil
import subprocess
import time

from src.search.core import Result

DEFAULT_CACHE = "/root/.cache/lean_interact"


class OpenError(RuntimeError):
    """Định lý không elaborate được (lỗi của statement, không phải REPL chết) -> không thử lại."""


def goals_pp(goals: list[str]) -> str:
    """Định dạng state giống LeanDojo: các goal nối bằng dòng trống."""
    return "\n\n".join(goals)


def _has_error(res) -> bool:
    return any(getattr(m, "severity", "") == "error" for m in (getattr(res, "messages", None) or []))


def make_repl_apply(server, init_proof_state: int, init_pp: str, tactic_timeout_s: float | None = None):
    from lean_interact import ProofStep
    from lean_interact.interface import LeanError

    states = {init_pp: init_proof_state}      # pp -> proof_state id trong REPL

    def apply(pp: str, tac: str) -> Result:
        t0 = time.perf_counter()
        try:
            res = server.run(ProofStep(proof_state=states[pp], tactic=tac), timeout=tactic_timeout_s)
        except Exception:                      # timeout / REPL chết -> coi là lỗi
            return Result("error", "", (time.perf_counter() - t0) * 1000)
        ms = (time.perf_counter() - t0) * 1000
        if isinstance(res, LeanError) or _has_error(res):
            return Result("error", "", ms)
        if not res.goals:
            return Result("finished", "", ms)
        new_pp = goals_pp(res.goals)
        states.setdefault(new_pp, res.proof_state)
        return Result("progress", new_pp, ms)

    return apply


class ReplSession:
    """1 LeanServer / process, tái dùng env đã import header."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.server = None
        self.envs: dict[str, int] = {}
        self.used = 0

    def _start(self):
        from lean_interact import LeanREPLConfig, LeanServer, TempRequireProject
        version = self.cfg.get("lean_version", "v4.9.0")
        cache = self.cfg.get("lean_cache_dir", DEFAULT_CACHE)
        if shutil.which("elan"):               # lake cần toolchain mặc định; tải 1 lần vào volume elan
            subprocess.run(["elan", "default", f"leanprover/lean4:{version}"], check=True,
                           stdout=subprocess.DEVNULL)
        if self.cfg.get("require_mathlib", True):
            config = LeanREPLConfig(project=TempRequireProject(lean_version=version, require="mathlib"),
                                    cache_dir=cache, verbose=False)
        else:
            config = LeanREPLConfig(lean_version=version, cache_dir=cache, verbose=False)
        self.server = LeanServer(config)
        self.envs = {}
        self.used = 0

    def _env(self, header: str) -> int | None:
        from lean_interact import Command
        if not header.strip():
            return None
        if header not in self.envs:
            res = self.server.run(Command(cmd=header), timeout=self.cfg.get("header_timeout_s", 900))
            if not hasattr(res, "env") or _has_error(res):
                raise RuntimeError(f"header failed: {res}")
            self.envs[header] = res.env
        return self.envs[header]

    def _restart(self):
        if self.server is not None:
            try:
                self.server.kill()
            except Exception:
                pass
        self._start()

    def open(self, statement: str, header: str = ""):
        """Trả về (proof_state, init_pp) của định lý `statement` (kết thúc bằng `:= by`).
        Nếu REPL đã chết (vd sau timeout ở định lý trước) thì khởi động lại và thử thêm 1 lần."""
        if self.server is None or self.used >= self.cfg.get("restart_every", 20):
            self._restart()
        self.used += 1
        try:
            return self._open(statement, header)
        except OpenError:
            raise
        except Exception:
            self._restart()
            self.used = 1
            return self._open(statement, header)

    def _open(self, statement: str, header: str):
        from lean_interact import Command
        env = self._env(header)
        cmd = statement.rstrip() + "\n  sorry"
        res = self.server.run(Command(cmd=cmd, env=env), timeout=self.cfg.get("open_timeout_s", 120))
        if not hasattr(res, "sorries") or _has_error(res) or not res.sorries:
            raise OpenError(f"cannot open theorem: {getattr(res, 'messages', res)}")
        s = res.sorries[0]
        return s.proof_state, s.goal

    def apply_fn(self, proof_state: int, init_pp: str):
        return make_repl_apply(self.server, proof_state, init_pp, self.cfg.get("tactic_timeout_s", 20))
