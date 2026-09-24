"""Stress real application workers concurrently, CPU only, with a parent watchdog.

Run from any directory: py -3.13 <path>/MultithreadStressTest.py --seconds 30
Requires PySide6 and a built CycloViz. No GUI windows or hardware connections.
"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import subprocess
import sys
import threading
import time
import traceback
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError('must be at least 1')
    return value


def summary(values):
    values = sorted(values)
    return dict(count=len(values), median_ms=statistics.median(values) if values else None,
                p95_ms=values[math.ceil(.95*len(values))-1] if values else None,
                max_ms=max(values) if values else None)


def child(args):
    sys.path.insert(0, str(ROOT))
    for folder in ('Debug', 'Release', 'build/Debug', 'build/Release'):
        sys.path.insert(0, str(ROOT/folder))
    import CycloViz
    from PySide6.QtCore import QCoreApplication, QTimer
    from source.Python.Data.async_writer import AsyncSQLiteWriter, Statement
    from source.Python.Data.file_writer import FileWriter

    app = QCoreApplication([])
    stop = threading.Event()
    gate = threading.Event()
    errors = []
    mutex = threading.Lock()
    report = dict(scope='Real C++ simulator/PID, AsyncSQLiteWriter, FileWriter, Qt event loop; CPU only',
                  native_module=CycloViz.__file__, python=sys.version, errors=errors,
                  configuration={k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()})
    sys.excepthook = lambda *exc: errors.append(''.join(traceback.format_exception(*exc)))
    writers, threads, file_futures = [], [], []
    service = CycloViz.ControlService()
    files = FileWriter('stress-file-writer')
    paths = [args.output/f'{name}.sqlite3' for name in ('A', 'B')]
    accepted = [set(), set()]
    rejected = [0, 0]
    maximum_queue = [0, 0]
    producer_totals = {}
    cpu_totals = {}
    lock_result = {}
    heartbeat = []
    progress = []
    latencies = []
    start = time.perf_counter()

    def launch(name, function, *values):
        def guarded():
            try:
                function(*values)
            except Exception:
                with mutex:
                    errors.append(f'{name}: {traceback.format_exc()}')
                stop.set()
        worker = threading.Thread(target=guarded, name=name, daemon=True)
        threads.append(worker)
        worker.start()

    def initialize(connection):
        connection.execute('CREATE TABLE IF NOT EXISTS samples (producer INTEGER, sequence INTEGER, value REAL, '
                           'PRIMARY KEY(producer, sequence))')

    def append_marker(text):
        with (args.output/'file-worker.txt').open('a', encoding='utf-8') as handle:
            handle.write(text+'\n')

    def producer(index):
        gate.wait()
        number = 0
        cpu_start = time.thread_time()
        while not stop.is_set():
            before = time.perf_counter()
            statement = Statement('INSERT INTO samples VALUES (?,?,?)', ((index, number, float(number)),))
            outcomes = [writer.submit([statement]) for writer in writers]
            with mutex:
                for which, ok in enumerate(outcomes):
                    if ok:
                        accepted[which].add((index, number))
                    else:
                        rejected[which] += 1
                latencies.append((time.perf_counter()-before)*1000)
            if number % 50 == 0:
                future = files.submit(append_marker, f'{index}:{number}')
                with mutex:
                    file_futures.append(future)
            number += 1
            # Fixed delay avoids an unbounded catch-up burst after scheduling stalls.
            stop.wait(max(0, 1/args.rate-(time.perf_counter()-before)))
        with mutex:
            producer_totals[index] = dict(iterations=number, cpu_seconds=time.thread_time()-cpu_start)

    def cpu_load(index):
        gate.wait()
        count = 0
        cpu_start = time.thread_time()
        while not stop.is_set():
            hashlib.pbkdf2_hmac('sha256', b'cpu-only-stress', b'crocker', 20000)
            count += 1
        with mutex:
            cpu_totals[index] = dict(jobs=count, cpu_seconds=time.thread_time()-cpu_start)

    def lock_database():
        gate.wait()
        if stop.wait(args.seconds/3):
            return
        with closing(sqlite3.connect(paths[0], timeout=2)) as connection:
            connection.execute('BEGIN IMMEDIATE')
            lock_result.update(started=time.perf_counter()-start,
                               b_before=writers[1].written,
                               pid_before=service.PidTrialStatus()['iterations'],
                               heartbeats_before=len(heartbeat))
            stop.wait(args.lock_seconds)
            lock_result.update(b_after=writers[1].written,
                               pid_after=service.PidTrialStatus()['iterations'],
                               heartbeats_after=len(heartbeat))
            connection.rollback()
            lock_result['released'] = True

    try:
        for index, path in enumerate(paths):
            writer = AsyncSQLiteWriter(path, initialize, name=f'stress-database-{index}')
            writers.append(writer)
            writer.submit([Statement('INSERT INTO samples VALUES (?,?,?)', ((-1, -1, 0.),))])
        deadline = time.monotonic()+5
        while not all(w.written for w in writers):
            if time.monotonic() > deadline:
                raise RuntimeError(f'Database startup timeout: {[w.status() for w in writers]}')
            time.sleep(.01)
        service.StartSimulator(200)
        service.StartPidTrial(dict(controller_kind='nla', measurement_channel=0, setpoint=10.,
            kp=.8, ki=.05, kd=0., update_rate_hz=100., duration_seconds=args.seconds+10,
            continuous=True, telemetry_timeout_seconds=2., allocation=[1.]+[0.]*13,
            command_bias=[0.]*14, minimum_command=[0.]*14, maximum_command=[100.]*14,
            maximum_slew_per_second=[100.]*14, allocation_calibrated=False,
            hardware_armed=False, dry_run=True))
        for index in range(args.producers):
            launch(f'producer-{index}', producer, index)
        for index in range(args.cpu_workers):
            launch(f'cpu-{index}', cpu_load, index)
        if args.lock_seconds:
            launch('database-lock-injector', lock_database)
        previous = time.perf_counter()
        def tick():
            nonlocal previous
            now = time.perf_counter()
            heartbeat.append(max(0, (now-previous)*1000-10))
            previous = now
            for index, writer in enumerate(writers):
                maximum_queue[index] = max(maximum_queue[index], writer.status()['queue_depth'])
            if stop.is_set():
                app.quit()
        def display():
            entry = dict(elapsed=round(time.perf_counter()-start, 1),
                         queues=[w.status()['queue_depth'] for w in writers],
                         written=[w.written for w in writers],
                         rejected=[w.rejected for w in writers],
                         simulator_sequence=service.LatestSnapshot()['sequence_number'],
                         pid_iterations=service.PidTrialStatus()['iterations'])
            progress.append(entry)
            print(json.dumps(entry), flush=True)
        beat, monitor, finish = QTimer(), QTimer(), QTimer()
        beat.timeout.connect(tick)
        monitor.timeout.connect(display)
        finish.setSingleShot(True)
        finish.timeout.connect(app.quit)
        start = previous = time.perf_counter()
        process_start = time.process_time()
        gate.set()
        beat.start(10)
        monitor.start(1000)
        finish.start(args.seconds*1000)
        app.exec()
        for timer in (beat, monitor, finish):
            timer.stop()
        display()
        report.update(wall_seconds=time.perf_counter()-start,
                      process_cpu_seconds=time.process_time()-process_start,
                      heartbeat_lateness=summary(heartbeat), progress=progress,
                      pid_status=service.PidTrialStatus())
    except Exception:
        errors.append(traceback.format_exc())
    finally:
        stop.set()
        gate.set()
        shutdown = time.perf_counter()
        deadline = time.monotonic()+args.shutdown_timeout
        for worker in threads:
            worker.join(max(0, deadline-time.monotonic()))
            if worker.is_alive():
                errors.append(f'Worker failed to stop: {worker.name}')
        service.Stop()
        for writer in writers:
            writer.close(timeout=max(.1, deadline-time.monotonic()))
        files.close()
        for writer in writers:
            if not writer.done.wait(max(0, deadline-time.monotonic())):
                errors.append(f'Writer shutdown timed out: {writer.name}')
        if not files.done.wait(max(0, deadline-time.monotonic())):
            errors.append('File writer shutdown timed out')
        report['shutdown_seconds'] = time.perf_counter()-shutdown

    checks = {}
    for index, writer in enumerate(writers):
        try:
            with closing(sqlite3.connect(paths[index], timeout=1)) as connection:
                actual = set(connection.execute('SELECT producer,sequence FROM samples WHERE producer>=0'))
                checks[f'database_{index}_exact_records'] = actual == accepted[index]
                checks[f'database_{index}_integrity'] = connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
            checks[f'database_{index}_drained'] = writer.done.is_set() and not writer.pending and not writer.error
        except Exception:
            errors.append(traceback.format_exc())
    checks['no_rejected_records'] = not any(rejected)
    checks['every_producer_progressed'] = len(producer_totals) == args.producers and all(x['iterations'] for x in producer_totals.values())
    checks['cpu_workers_progressed'] = len(cpu_totals) == args.cpu_workers and all(x['jobs'] for x in cpu_totals.values())
    checks['file_jobs_completed'] = bool(file_futures) and all(f.done() and f.exception() is None for f in file_futures)
    if checks['file_jobs_completed']:
        checks['file_records_complete'] = len((args.output/'file-worker.txt').read_text().splitlines()) == len(file_futures)
    checks['heartbeat_progressed'] = len(heartbeat) > args.seconds*5
    checks['heartbeat_within_budget'] = bool(heartbeat) and max(heartbeat) <= args.max_heartbeat_ms
    checks['native_pid_progressed'] = report.get('pid_status', {}).get('iterations', 0) > 0 and report.get('pid_status', {}).get('state') == 'Running'
    if len(progress) >= 3:
        checks['simulator_kept_progressing'] = all(b['simulator_sequence'] > a['simulator_sequence']
                                                  for a, b in zip(progress[:-2], progress[1:-1]))
        checks['pid_kept_progressing'] = all(b['pid_iterations'] > a['pid_iterations']
                                            for a, b in zip(progress[:-2], progress[1:-1]))
    if args.lock_seconds:
        checks['lock_released'] = lock_result.get('released', False)
        for label, key in [('independent_database_progress', 'b'), ('pid_progress_during_lock', 'pid'),
                           ('heartbeat_progress_during_lock', 'heartbeats')]:
            checks[label] = lock_result.get(key+'_after', 0) > lock_result.get(key+'_before', 0)
    report.update(checks=checks, producers=producer_totals, cpu_workers=cpu_totals,
                  lock_test=lock_result, submission_latency=summary(latencies),
                  accepted=[len(s) for s in accepted], rejected=rejected,
                  max_observed_queue=maximum_queue, writers=[w.status() for w in writers],
                  file_jobs=len(file_futures), passed=not errors and all(checks.values()))
    (args.output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f'\n{"PASS" if report["passed"] else "FAIL"}: {args.output / "report.json"}', flush=True)
    for name, ok in checks.items():
        print(f'  {"PASS" if ok else "FAIL"} {name}', flush=True)
    for error in errors:
        print(error, file=sys.stderr)
    return 0 if report['passed'] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seconds', type=positive, default=30)
    parser.add_argument('--producers', type=positive, default=4)
    parser.add_argument('--rate', type=positive, default=250, help='Jobs/sec per producer per database')
    parser.add_argument('--cpu-workers', type=int, default=2, help='Additional native CPU load threads; 0 disables')
    parser.add_argument('--lock-seconds', type=int, default=2, help='Hold database A write lock; 0 disables')
    parser.add_argument('--shutdown-timeout', type=positive, default=15)
    parser.add_argument('--max-heartbeat-ms', type=positive, default=500)
    parser.add_argument('--output', type=Path, default=ROOT/'logs'/'multithread-stress')
    parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.cpu_workers < 0 or not 0 <= args.lock_seconds < args.seconds/2:
        parser.error('cpu-workers must be nonnegative; lock-seconds must be less than half the duration')
    if args.child:
        return child(args)
    args.output = args.output.resolve()/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    args.output.mkdir(parents=True)
    command = [sys.executable, str(Path(__file__).resolve()), *sys.argv[1:],
               '--output', str(args.output), '--child']
    print(f'CPU-only concurrent stress run; artifacts: {args.output}', flush=True)
    print('Real simulator + dry-run PID, two database writers, file writer, producers, CPU load, Qt heartbeat.', flush=True)
    try:
        result = subprocess.run(command, timeout=args.seconds+args.shutdown_timeout+20)
        if not (args.output/'report.json').exists():
            (args.output/'report.json').write_text(json.dumps(dict(passed=False,
                error='Worker process exited before reporting', exit_code=result.returncode)), encoding='utf-8')
        return result.returncode
    except subprocess.TimeoutExpired:
        (args.output/'report.json').write_text(json.dumps(dict(passed=False,
            error='Parent watchdog terminated a hung or overdue test process')), encoding='utf-8')
        print('FAIL: watchdog timeout', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
