"""Standalone CPU concurrency benchmarks; no GUI, GPU, hardware, or third-party imports."""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import threading
import time


def calculate(kind, iterations, seed):
    if kind == 'native':
        # OpenSSL CPU work can run outside CPython's GIL.
        return hashlib.pbkdf2_hmac('sha256', str(seed).encode(), b'crocker-cpu-test',
                                   iterations, dklen=32).hex()
    value = seed + 1
    for _ in range(iterations):
        value = (1664525 * value + 1013904223) & 0xffffffff
    return value


def job(arguments):
    kind, iterations, seed = arguments
    started = time.thread_time()
    result = calculate(kind, iterations, seed)
    return result, time.thread_time() - started, os.getpid(), threading.get_ident()


def measure(kind, iterations, tasks, workers, repeats):
    arguments = [(kind, iterations, seed) for seed in range(tasks)]
    rows = []
    expected = None
    for mode in ('serial', 'threads', 'processes'):
        executor = None
        setup = time.perf_counter()
        if mode != 'serial':
            factory = ThreadPoolExecutor if mode == 'threads' else ProcessPoolExecutor
            executor = factory(max_workers=workers)
        try:
            # Untimed warmup also validates every mode against the same workload.
            warm = list(map(job, arguments) if executor is None else executor.map(job, arguments))
            setup = time.perf_counter() - setup
            results = [item[0] for item in warm]
            if expected is None:
                expected = results
            if results != expected:
                raise RuntimeError(f'{kind}/{mode}: warmup result mismatch')
            samples = []
            identities = set()
            for _ in range(repeats):
                started = time.perf_counter()
                output = list(map(job, arguments) if executor is None else executor.map(job, arguments))
                elapsed = time.perf_counter() - started
                if [item[0] for item in output] != expected:
                    raise RuntimeError(f'{kind}/{mode}: result mismatch')
                cpu = sum(item[1] for item in output)
                identities.update((item[2], item[3]) for item in output)
                samples.append({'wall_seconds': elapsed, 'worker_cpu_seconds': cpu,
                                'effective_cores': cpu / elapsed})
            wall = statistics.median(s['wall_seconds'] for s in samples)
            rows.append(dict(workload=kind, mode=mode, workers=1 if mode == 'serial' else workers,
                             observed_workers=len(identities), wall_seconds=wall,
                             jobs_per_second=tasks / wall,
                             effective_cores=statistics.median(s['effective_cores'] for s in samples),
                             setup_and_warmup_seconds=setup, samples=samples))
        finally:
            if executor is not None:
                executor.shutdown(wait=True, cancel_futures=True)
    for row in rows:
        row['speedup'] = rows[0]['wall_seconds'] / row['wall_seconds']
    return rows


def timed_workers(workers, duration, rate, iterations):
    """Instrument intentional waits, not inferred OS scheduler thread states."""
    barrier = threading.Barrier(workers)
    stop = threading.Event()

    def loop(index):
        barrier.wait(timeout=30)
        started = time.perf_counter()
        cpu_started = time.thread_time()
        deadline = started + duration
        next_tick = started
        ticks = missed = 0
        waiting = busy = 0.0
        while time.perf_counter() < deadline:
            before = time.perf_counter()
            calculate('python', iterations, index)
            busy += time.perf_counter() - before
            ticks += 1
            next_tick += 1.0 / rate
            now = time.perf_counter()
            if now > next_tick:
                skipped = int((now - next_tick) * rate) + 1
                missed += skipped
                next_tick += skipped / rate
            before = time.perf_counter()
            stop.wait(max(0.0, min(next_tick, deadline) - before))
            waiting += time.perf_counter() - before
        elapsed = time.perf_counter() - started
        return dict(worker=index, ticks=ticks, missed_intervals=missed,
                    wall_seconds=elapsed, cpu_seconds=time.thread_time() - cpu_started,
                    work_wall_seconds=busy, explicit_wait_seconds=waiting,
                    explicit_wait_percent=100.0 * waiting / elapsed)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(loop, range(workers)))


def positive_int(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return value


def positive_float(value):
    value = float(value)
    if not 0 < value < float('inf'):
        raise argparse.ArgumentTypeError('must be positive and finite')
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers', type=positive_int, default=min(4, os.cpu_count() or 1))
    parser.add_argument('--tasks', type=positive_int, default=16,
                        help='Fixed job count shared by all execution modes (default: 16)')
    parser.add_argument('--repeats', type=positive_int, default=3)
    parser.add_argument('--python-iterations', type=positive_int, default=300000)
    parser.add_argument('--native-iterations', type=positive_int, default=150000)
    parser.add_argument('--duration', type=positive_float, default=2.0,
                        help='Timed-loop duration in seconds')
    parser.add_argument('--rate', type=positive_float, default=20.0,
                        help='Requested ticks per second per timed worker')
    parser.add_argument('--tick-iterations', type=positive_int, default=5000)
    parser.add_argument('--json', type=Path, help='Optional machine-readable report path')
    args = parser.parse_args()
    gil = getattr(sys, '_is_gil_enabled', lambda: None)()
    metadata = dict(python=sys.version, executable=sys.executable, platform=platform.platform(),
                    logical_cpus=os.cpu_count(), gil_enabled=gil,
                    configuration={k: str(v) if isinstance(v, Path) else v
                                   for k, v in vars(args).items()})
    print(f'CPU-only benchmark | Python {platform.python_version()} | '
          f'{os.cpu_count()} logical CPUs | GIL: {gil if gil is not None else "not reported"}', flush=True)
    print(f'{args.tasks} identical jobs per mode, {args.workers} workers, '
          f'{args.repeats} measured repeats; warmup excluded.\n', flush=True)
    rows = []
    for kind, iterations in [('python', args.python_iterations), ('native', args.native_iterations)]:
        print(f'Running {kind} CPU workload...', flush=True)
        measured = measure(kind, iterations, args.tasks, args.workers, args.repeats)
        rows.extend(measured)
        print(f'{"Mode":<12} {"Wall (s)":>10} {"Jobs/s":>10} {"Speedup":>9} {"CPU cores*":>11} {"Workers seen":>13}')
        for row in measured:
            print(f'{row["mode"]:<12} {row["wall_seconds"]:>10.3f} '
                  f'{row["jobs_per_second"]:>10.1f} {row["speedup"]:>8.2f}x '
                  f'{row["effective_cores"]:>11.2f} {row["observed_workers"]:>13}')
        print(flush=True)
    print('Running timed CPU workers (similar scheduling to control loops)...', flush=True)
    ticks = timed_workers(args.workers, args.duration, args.rate, args.tick_iterations)
    print(f'{"Worker":<8} {"Ticks":>8} {"Missed":>8} {"CPU (s)":>10} {"Explicit wait":>15}')
    for row in ticks:
        print(f'{row["worker"]:<8} {row["ticks"]:>8} {row["missed_intervals"]:>8} '
              f'{row["cpu_seconds"]:>10.3f} {row["explicit_wait_percent"]:>14.1f}%')
    print('\n* CPU cores = sum of job thread CPU time / elapsed wall time. '
          'Above 1 indicates simultaneous CPU execution; excludes dispatcher/IPC CPU cost.\n'
          'Python threads may not accelerate Python loops with the GIL enabled. Native CPU\n'
          'work and processes can scale, but job size and CPU limits matter. Speedup is\n'
          'relative to serial execution of the same jobs. Startup/warmup is recorded in JSON.\n'
          'High explicit wait with advancing ticks is normal. Work wall time can include\n'
          'GIL/scheduler delays; wait percentage is instrumented, not an OS thread-state trace.\n'
          'These synthetic tests do not diagnose a running GUI, locks, or hardware traffic.')
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(dict(metadata=metadata, benchmarks=rows,
                                             timed_workers=ticks), indent=2), encoding='utf-8')
        print(f'Report: {args.json.resolve()}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
