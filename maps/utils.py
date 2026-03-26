import time
from datetime import timedelta

t0 = time.perf_counter()
step_times: list[tuple[str, float]] = []

def fmt_seconds(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds)))

def log(msg: str) -> None:
    elapsed = time.perf_counter() - t0
    print(f"[{fmt_seconds(elapsed)}] {msg}", flush=True)

def run_step(step_name: str, func):
    log(f"Iniciando: {step_name}")
    s = time.perf_counter()
    result = func()
    dt = time.perf_counter() - s
    step_times.append((step_name, dt))
    log(f"Concluído: {step_name} ({dt:.1f}s)")
    return result

def eta_after_current(current_step_index: int, total_steps: int) -> str:
    if not step_times:
        return "ETA desconhecido"
    avg = sum(dt for _, dt in step_times) / len(step_times)
    remaining_steps = total_steps - current_step_index
    eta = avg * remaining_steps
    return f"ETA aproximado: {fmt_seconds(eta)}"