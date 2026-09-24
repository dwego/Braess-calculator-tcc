"""Progresso de execução sem instrumentar ou modificar o solver."""
from contextlib import contextmanager
from datetime import datetime
from threading import Event, Thread
from time import perf_counter


def log_progress(message: str) -> None:
    print(f"[{datetime.now().astimezone().strftime('%H:%M:%S')}] {message}", flush=True)


@contextmanager
def progress_phase(label: str, *, interval: float = 15):
    """Informa atividade durante chamadas demoradas; não estima convergência."""
    started = perf_counter()
    stopped = Event()

    def heartbeat():
        while not stopped.wait(interval):
            log_progress(f"{label} | em execução há {perf_counter() - started:.1f}s")

    log_progress(f"{label} | início")
    worker = Thread(target=heartbeat, name="experiment-progress", daemon=True)
    worker.start()
    try:
        yield
    except BaseException:
        log_progress(f"{label} | interrompido após {perf_counter() - started:.1f}s")
        raise
    else:
        log_progress(f"{label} | concluído em {perf_counter() - started:.1f}s")
    finally:
        stopped.set()
        worker.join()
