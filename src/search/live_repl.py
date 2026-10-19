"""Adapter gọi Lean thật qua LeanInteract (Lean REPL) — thay LeanDojo, không cần trace mathlib.

Mỗi worker giữ 1 LeanServer: import header (vd `import Mathlib`) 1 lần thành env, rồi mở từng
định lý bằng `<statement> sorry` để lấy proof state gốc. Server được khởi động lại sau
`restart_every` định lý vì REPL giữ mọi proof state trong RAM.
"""
from __future__ import annotations

import re
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


class RebuildError(RuntimeError):
    """Không dựng lại được proof state sau khi REPL khởi động lại."""


def make_repl_apply(session, init_proof_state: int, init_pp: str, tactic_timeout_s: float | None = None):
    """session cần: .server, .generation, .restart(), .reopen() -> (proof_state, init_pp).

    Timeout cứng kill REPL và làm mất mọi proof state. Lời gọi bị timeout tính là "error"
    (hành vi thật của tactic); các lời gọi sau đó dựng lại state bằng cách mở lại định lý và
    chạy lại đường đi tactic từ gốc. Việc dựng lại là hạ tầng, KHÔNG tính vào budget/elapsed.
    Không dựng lại được -> "unknown" (search dừng, status unknown, ghi nhận là lỗi hạ tầng).
    """
    from lean_interact import ProofStep
    from lean_interact.interface import LeanError

    states = {init_pp: (session.generation, init_proof_state)}   # pp -> (thế hệ REPL, proof_state)
    paths = {init_pp: []}                                        # pp -> tactic từ gốc

    def resolve(pp: str) -> int:
        gen, ps = states[pp]
        if gen == session.generation:
            return ps
        ps, cur = session.reopen()
        for tac in paths[pp]:
            res = session.server.run(ProofStep(proof_state=ps, tactic=tac), timeout=tactic_timeout_s)
            if isinstance(res, LeanError) or _has_error(res):
                raise RebuildError(f"replay of {tac!r} failed")
            ps, cur = res.proof_state, goals_pp(res.goals)
        if cur != pp:
            raise RebuildError("rebuilt state differs")
        states[pp] = (session.generation, ps)
        return ps

    def apply(pp: str, tac: str) -> Result:
        try:
            ps = resolve(pp)
        except Exception:
            return Result("unknown")
        t0 = time.perf_counter()
        try:
            res = session.server.run(ProofStep(proof_state=ps, tactic=tac), timeout=tactic_timeout_s)
        except Exception:                      # timeout cứng -> REPL bị kill: tactic thất bại, khởi động lại
            ms = (time.perf_counter() - t0) * 1000
            try:
                session.restart()
            except Exception:                  # lần gọi sau sẽ không dựng lại được -> unknown
                pass
            return Result("error", "", ms)
        ms = (time.perf_counter() - t0) * 1000
        if isinstance(res, LeanError) or _has_error(res):
            return Result("error", "", ms)
        if not res.goals:
            return Result("finished", "", ms)
        new_pp = goals_pp(res.goals)
        states.setdefault(new_pp, (session.generation, res.proof_state))
        paths.setdefault(new_pp, paths[pp] + [tac])
        return Result("progress", new_pp, ms)

    return apply


class ReplSession:
    """1 LeanServer / process, tái dùng env đã import header."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.server = None
        self.envs: dict[str, int] = {}
        self.used = 0
        self.generation = 0                    # tăng mỗi lần REPL khởi động lại -> proof_state cũ hết hiệu lực
        self.current = None                    # (statement, header) của định lý đang search
        self.restarts = 0

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
        self.generation += 1

    def _env(self, header: str) -> int | None:
        from lean_interact import Command
        if not header.strip():
            return None
        if header not in self.envs:
            hb = self.cfg.get("max_heartbeats")
            cmd = re.sub(r"set_option maxHeartbeats \d+", f"set_option maxHeartbeats {hb}", header) \
                if hb is not None else header
            res = self.server.run(Command(cmd=cmd), timeout=self.cfg.get("header_timeout_s", 900))
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

    def restart(self):
        """Gọi khi REPL bị kill giữa chừng (timeout cứng của 1 tactic)."""
        self.restarts += 1
        self._restart()

    def reopen(self):
        """Mở lại định lý hiện tại trên REPL mới (dùng để dựng lại proof state)."""
        return self._open(*self.current)

    def open(self, statement: str, header: str = ""):
        """Trả về (proof_state, init_pp) của định lý `statement` (kết thúc bằng `:= by`).
        Nếu REPL đã chết (vd sau timeout ở định lý trước) thì khởi động lại và thử thêm 1 lần."""
        if self.server is None or self.used >= self.cfg.get("restart_every", 20):
            self._restart()
        self.used += 1
        self.current = (statement, header)
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
        hb = self.cfg.get("max_heartbeats")
        if hb is not None:                     # áp cả vào proof state -> tactic chậm báo lỗi thay vì treo REPL
            cmd = f"set_option maxHeartbeats {hb} in\n{cmd}"
        res = self.server.run(Command(cmd=cmd, env=env), timeout=self.cfg.get("open_timeout_s", 120))
        if not hasattr(res, "sorries") or _has_error(res) or not res.sorries:
            raise OpenError(f"cannot open theorem: {getattr(res, 'messages', res)}")
        s = res.sorries[0]
        return s.proof_state, s.goal

    def apply_fn(self, proof_state: int, init_pp: str):
        return make_repl_apply(self, proof_state, init_pp, self.cfg.get("tactic_timeout_s", 20))
